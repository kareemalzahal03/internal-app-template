# api

The backend: FastAPI and Beanie (async PyMongo) over MongoDB. It signs users
in, serves the API, and serves the built frontend. This file explains the
design choices the code cannot explain about itself. Sign-in has its own
file, [AUTH.md](AUTH.md), and so do the tests, [TESTING.md](TESTING.md).

## Layout

`app/core/` is the template: what every app needs, from sign-in to logging.
`app/domain/` is what this app is for; clients and orders are a placeholder.
App behaviour goes in the domain, machinery in the core, and the core never
imports the domain. `scripts/` holds tools run on the host, outside `app/`,
so the image never ships them.

## Layering

There is none. Each route holds its own queries and logic.

A service and repository layer was built first and removed: about a third
of its methods were one-line passthroughs, and reading one endpoint meant
opening three files. The three jobs the layers did went elsewhere:

- **A rule shared between routes** is a FastAPI dependency. "This client
  must exist, or 404" is part of each route's signature.
- **Translating driver errors** is an exception handler, registered once. A
  duplicate key becomes a 409 everywhere.
- **Choosing a status** stays where the failure is understood: a route
  raises `HTTPException(404, …)` because it knows why.

The cost is that business operations are route functions, so a cron job or
a queue worker cannot call them without HTTP. When a second entry point
appears, bring back a module per domain object, holding queries and rules,
not three layers of passthrough.

## Configuration and startup

Each piece of the app reads its own settings from the environment, defined
beside it, with no defaults. `.env.dev` lists every variable. Startup opens
MongoDB and creates the declared indexes, then loads and checks the
provider's discovery document. Any failure stops the process, so a bad
deploy fails before it serves anyone.

A router can carry its own startup in `APIRouter(lifespan=...)`. Including
the router adds it to the app's own, run once the database is ready. This
is how the core starts sign-in, and how the domain can add a startup
without touching the app's assembly.

That holds only with uvicorn's lifespan set to `on`. In its default mode, a
failure while the middleware is built is read as "this app has no
lifespan", and the process serves a 500 on every request. The image sets
uvicorn's shared settings as `UVICORN_` variables, that one included, so
every command is `uvicorn app.main:app` plus only what differs.

`/api/health` answers `{"status": "ok"}` and checks nothing else. The load
balancer probes it, and the platform replaces any copy that fails. A probe that
checked the database would fail every task at once during an outage, and
restarting cannot fix a database. Startup already checks the provider and
the database, so a copy never becomes healthy without them. This is the
shallow check of AWS's Builders' Library, "Implementing health checks".

## The database

One `AsyncMongoClient` is opened at startup and shared by every request,
because the client holds its own connection pool. Opening the database and
binding the models to it **never drop data**: they ship in the image, so
nothing in them can empty a database.

**`MONGODB_URL` carries the driver's options**, so each deployment sets its
own without a code change. The dev URL sets two:

- `timeoutMS=10000`: each operation, from finding the server to its reply,
  gets ten seconds. It bounds how long a request waits on a database in
  trouble before it answers 500. Ten is far above any query here, and keeps
  a request of a few calls inside a load balancer's idle timeout (60 seconds
  on AWS by default) and the 20 seconds running requests get at shutdown.
- `appName=devApp`: the server writes it into its logs and slow-query logs,
  so the app's connections are told apart from anyone else's.

**Documents and DTOs are separate classes, kept together per entity.** A
Beanie `Document` is what MongoDB stores; the Pydantic DTOs beside it are
what HTTP accepts and returns. One shared class would make every change to
the stored shape a change to the API, and the first field that differs,
such as a timestamp the API must not accept, breaks that. The OpenAPI
schema, and so the generated client, is built from the DTOs only. They
share a file because a change to one entity touches both.

The example domain shows the two ways to relate documents:

- **Embed** what is always read with its parent, never queried alone, and
  bounded: a client's contacts. One read fetches it all, and one write
  updates it atomically.
- **Reference** what is unbounded or queried on its own: a client's orders.
  Their compound index follows the ESR rule (equality, then sort, then
  range), so listing a client's orders, newest first, reads one sorted
  slice of the index.

Every listing sorts last by `_id`. MongoDB does not promise an order among
equal values, so without it a page could repeat or skip a row.

A reference needs the app to keep it consistent. Deleting a client deletes
its orders in a second write, not atomically, because MongoDB runs
standalone here and transactions need a replica set (`docs/decisions.md`,
"Deliberately omitted").

### Indexes

**Indexes are declared on the models, and only there.** Startup creates
each declared index the database lacks and drops none, which is
`init_beanie` with its defaults. In a rolling deploy the old and new
versions run side by side, and each would otherwise drop the indexes only
the other declares; a dropped unique index lets duplicates in until it is
back.

**Dropping or changing an index is done by hand**, with `mongosh`, after
trying the same commands on the dev Mongo
(`docker compose exec mongo mongosh appdb`). Nothing drops one for you:
"drop whatever the code does not declare" would also drop one an operator
or Atlas's Performance Advisor added.

- **An index the code no longer declares** stays until dropped. Drop it
  after the deploy, once no old copy needs it:
  `db.orders.dropIndex("old_1")`.
- **An index whose settings change** fails startup until the database
  matches, so change it before the deploy. `collMod` changes some settings
  in place, such as `unique` and a TTL's `expireAfterSeconds`. Anything else
  is `dropIndex` then `createIndex`, and between the two nothing enforces it.
- **A new index on a large collection**: create it by hand before the
  deploy. Startup builds a new index under the same ten seconds as any
  operation, and fails if the build takes longer.

**Making an index unique in place** (MongoDB 6.0+): `collMod` with
`prepareUnique: true` refuses new duplicates. Settle the duplicates already
stored, set `unique: true`, then deploy the code that declares it. From the
first step an old copy that restarts cannot start, so keep the steps and the
deploy close together. Only the first step can be undone.

## Serving the SPA

The API serves the built frontend from `frontend/` beside the package,
mounted after every API route. On a bare host that folder holds a committed
stand-in page.

- `index.html` is returned only to navigations that accept HTML, so a
  `fetch` for a missing file gets a 404. Anything in front of the API must
  pass the `Accept` header through, or every deep link becomes a 404.
- An unknown `/api` path is a JSON 404 for a `fetch` and any other method.
  Typed into the address bar, it gets the SPA, which shows its own
  not-found page (`docs/decisions.md`, "Deliberately omitted").
- It is mounted on the app, never on a router with dependencies: the
  sign-in page is part of this bundle.
- A missing folder, or one without `index.html`, fails at import.
- Hashed files under `/assets/` are cached forever, HTML never, and
  responses are gzipped.

## Security headers

Every response, API and SPA alike, carries:

| Header | Value | Effect |
|---|---|---|
| `Content-Security-Policy` | `default-src 'self'`, plus `object-src`, `base-uri`, `form-action` and `frame-ancestors` | Code loads only from this origin, and no other site can frame the app |
| `X-Content-Type-Options` | `nosniff` | A JSON response is never run as a script |
| `Referrer-Policy` | `same-origin` | Other sites are not sent this app's URLs |
| `Cross-Origin-Opener-Policy` | `same-origin` | A window from another site that opens the app, or that it opens, gets no handle on it |
| `Strict-Transport-Security` | Only when the request came over HTTPS (RFC 6797 §7.2) | The browser uses HTTPS from then on |

The CSP matters because the session cookie is `HttpOnly`: injected script
cannot read it, but could still use it by calling the API (RFC 10017 §5).
The policy allows no inline code and no other origin, which fits the Vite
build as it is. `just up` serves the real build under the real policy, so a
violation shows in the browser console; `just hmr` does not, because Vite's
dev server needs inline scripts. Widening the policy is a design decision,
not a fix for a console error.

A response that sets its own policy keeps it. The front-channel logout page
must be framed by the provider's logout page, and the API docs load Swagger
UI from its CDN. That page runs beside the signed-in session, so it loads
one pinned version, and the browser checks each file against its hash. No
dependency tool sees that pin, so upgrading it is by hand.

Behind a load balancer that ends HTTPS, the app learns the browser used
HTTPS from `X-Forwarded-Proto`. uvicorn trusts that header only from the
addresses in `FORWARDED_ALLOW_IPS`. Set it to the load balancer's
addresses, or to `*` only where nothing but the load balancer can reach the
app.

## Logging

Logs are JSON, one object per line, on stderr, uvicorn's own lines
included. The logging config is Python's
[dictConfig format](https://docs.python.org/3/library/logging.config.html#logging-config-dictschema),
applied by uvicorn as it starts. Its `disable_existing_loggers` must stay
`false`, or loggers created before it is read go silent.

Every line has `level`, `message`, `logger` and `time`. A line written
during a request also has the request's `request_id`, also sent as the
`X-Request-ID` response header, and `elapsed_ms`, how long the request has
run. Everything else goes in `attributes`, named as in
[OpenTelemetry's conventions](https://opentelemetry.io/docs/specs/semconv/),
so the names match other services' logs and any tracing added later.

Each request writes exactly one line of its own, with its method, path,
query, status, client address and protocol version. Its `message` is a
fixed sentence, never containing a value, saying how far the response got
and whether the app raised, so a log tool can group lines by message. A
client that left mid-response is normal, so that line is INFO or WARNING
rather than ERROR.

```json
{"level": "ERROR", "message": "The app raised before responding. Error response sent.",
 "logger": "app.core.logging", "time": "2026-01-02T10:00:00.000+00:00",
 "request_id": "9f3c…", "elapsed_ms": 12.3,
 "attributes": {"http.request.method": "POST", "url.path": "/api/auth/backchannel-logout",
   "http.response.status_code": 500, "client.address": "10.0.0.7",
   "network.protocol.version": "1.1", "exception.type": "httpx2.ConnectError",
   "exception.message": "…", "exception.stacktrace": "Traceback …"}}
```

In `url.query`, the values of keys that carry a credential, such as a
sign-in's `code` and `state`, are written as `REDACTED`, as OpenTelemetry
redacts. A route that takes a credential in its query adds its key to that
list. This covers the app's own lines only: a load balancer's access log
records the full URL.

Any code can add attributes: `log.info("Order shipped.",
extra={"attributes": {"order.id": ...}})`. Use an OpenTelemetry name where
one exists, and a dotted lowercase name otherwise. Any other key in `extra`
is not written, and nothing checks names, so a misspelled one becomes a new
attribute. Log an exception with `log.exception(...)` or `exc_info=exc`,
never `str(exc)`: it adds `exception.type`, `exception.message` and
`exception.stacktrace`, the three OpenTelemetry defines.

## Errors on the wire

Every non-2xx response has two members, named as in
[RFC 9457](https://www.rfc-editor.org/rfc/rfc9457): `status`, the HTTP
status repeated, and `detail`, a sentence that can be shown to a user as it
is. Validation failures flatten Pydantic's errors into one sentence:

```json
{ "status": 422, "detail": "email: Field required", "fields": { "email": "Field required" } }
```

The rest of RFC 9457 is left out (`docs/decisions.md`, "Deliberately
omitted").

`detail` alone can render any failure, so a client never has to branch on
shape. A status that carries more gets a subclass with that field required,
never an optional field on the base. Today there is one: `fields`, which
maps each bad input to what is wrong with it, for both 422 and 409. The
catch-all 500 says nothing of the bug; the bug is on the request's log line.

Starlette answers an unhandled exception in its outermost layer, above
every middleware the app adds, so by default the 500 carries none of their
headers. Instead, the layer that writes the request's log line also catches
any exception from below and sends the 500 itself. So a middleware that
only adds headers goes above that layer, and anything that can raise goes
below it.

### Declaring errors in the OpenAPI schema

What holds for every route is declared once, on the app:

```python
responses = {
    422: {"model": FieldErrorModel},
    "default": {"model": ErrorModel},
}
```

`default` means "any status not listed", which is what the handlers
guarantee. Declaring 422 also stops FastAPI injecting its own validation
schema, which describes a `detail` the app never sends.

A status that depends on where the request went is declared on that router:

```python
items_router = APIRouter(..., responses={409: {"model": FieldErrorModel}})
```

The rule: **declare a shape at the narrowest scope where it is true**,
router or app, never per route. A 409 belongs only on a router with a
unique index a caller can collide with.

## The generated client

Every route sets an explicit `operation_id`, which becomes the TypeScript
function's name, so editing a path never renames a frontend function. The
rest is in [services/web/README.md](../web/README.md).

## Calling other services

The API can call other services in two ways. Most internal apps need only
the first.

| | As the app | As the user |
|---|---|---|
| What the other service sees | "internal-app is calling" | "this person is calling, through internal-app" |
| Credential | The app's own: an AWS IAM role, or a client-credentials token ([RFC 6749 §4.4](https://www.rfc-editor.org/rfc/rfc6749#section-4.4)) | The user's access token for that service |
| Who decides what the user may do | This app | The other service |
| User tokens stored | None | Yes: the full BFF of RFC 10017 §6.1 |

**As the app** needs nothing from sign-in. For AWS services, grant the
app's IAM role access (an ECS task role, say) and call the SDK. For a
company API behind the same provider, register this app as its client and
request a token with the client-credentials grant; Authlib does this.
Being on the company's network is not a credential; ask the API's owners
for a token or an IAM identity.

**As the user** is needed when the other service must decide per person:
someone's mail in Microsoft Graph, or a system whose audit log must name
them. It is the part of RFC 10017 §6.1 this template leaves out. Adding it
means:

1. Changing the rule, in `AGENTS.md` and AUTH.md, that no token is stored.
2. Requesting that service's scopes, and `offline_access` if needed, and
   updating what is registered with the provider to match.
3. Storing the access token, refresh token and expiry on the session,
   encrypted.
4. Refreshing when a token expires (§6.1.2.2), once per session at a time:
   with refresh-token rotation, a second refresh at the same moment fails
   ([RFC 9700 §2.2.2](https://www.rfc-editor.org/rfc/rfc9700.html#section-2.2.2)).
5. Calling the service from route code with a fixed URL. A generic
   forwarding route MUST check an allowlist of destinations (§6.1.3.6).
6. Revoking the refresh token at sign-out
   ([RFC 7009](https://www.rfc-editor.org/rfc/rfc7009)).
