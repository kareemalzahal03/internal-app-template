# Adopting the template

Whether the template fits your app, how to make a copy of it your own, and
how to run it day to day. The README's Quickstart gets the stack running;
this picks up from there.

## Is it a fit?

Each row is something an internal app might need, and what this template
does about it.

| The app needs to… | This template |
|---|---|
| Let staff sign in with their company account | Built in. Any OpenID Connect provider (Entra, Okta, Keycloak, Cognito), set by three variables. |
| Keep tokens out of reach of scripts on the page | Built in. The browser holds an HttpOnly session cookie only. |
| Show and edit company data for a small team | Built in. That is what the example domain shows. |
| Call AWS services, or company APIs as the app | Supported. An IAM role or a client-credentials token, with no user token stored (`services/api/README.md`, "Calling other services"). |
| Act as the user on another API (their mail in Microsoft Graph, say) | Not yet. It needs stored user tokens: the full BFF. `services/api/README.md` lists the steps. |
| Give some users more rights than others | Not yet. Nobody reads the provider's role claims (`docs/decisions.md`, "Current gaps"). |
| Be called by scripts, other services or a mobile app | Not a fit. The API accepts a browser session only, never a bearer token. |
| Let the public sign up | Not a fit. There is no registration, on purpose. |
| Render on the server, for search engines | Not a fit. It is a single-page app. |
| Use transactions across documents | Not as set up. Mongo runs standalone (`docs/decisions.md` says how to change that). |

## Your copy is yours

The template is a starting point, not a dependency. Make a copy with
GitHub's **Use this template**, or clone it and start a new history. From
then on the code is yours: the tools, the libraries and the auth. Nothing
links the copy back here, and nothing updates it. Change anything,
including what the template chose.

That includes fixes. When a security flaw is found in the template, it is
fixed here and announced as a GitHub security advisory that names the
commit with the fix (`.github/SECURITY.md`). To hear about one, watch this
repository for security alerts (**Watch → Custom → Security alerts**).
Then check whether your copy still has the same code, and port the fix by
hand.

The license is MIT No Attribution. A copy does not have to keep the
template's notice, credit it, or stay open source.

## After you copy

The first hour with a new copy, in order. `just up` and `just test` should
pass after each step.

1. **Rename the app** ("Renaming the app" below), and put your logo in
   `services/web/public/favicon.svg`.
2. **Replace the example domain** with your own ("Replacing the example
   domain" below).
3. **Make the repo's own files describe your app, not the template.**
   - `README.md`: what your app is, and how to start it.
   - `AGENTS.md`: its opening paragraph, and the "example domain" rule
     under "Working habits", which can go once the example has.
   - `LICENSE` and `.github/SECURITY.md`: your own, or delete them for a
     private app.
   - `docs/decisions.md`: keep it as your own record. Its current gaps are
     now yours to close or accept.
   - `.github/workflows/ci.yml`: it runs on GitHub with no setup or secrets,
     and deploys nothing. Delete it if you don't use GitHub Actions.
4. **Register the app with your company's provider and deploy it**
   ("Going to production" below).

## Day to day

`just up` starts the stack and returns. There is one rule for the rest of
the day: source hot-reloads, everything else is `just up` again.

Source is each service's code folder: `services/api/app`,
`services/web/src` and `services/dev-idp/src`. Save a file there and its
process picks it up. Everything else, such as the lockfiles,
`services/web/index.html`, the build config and `services/web/public`, is
copied into the image, so changing it means `just up`, which rebuilds only
what changed. A new top-level file in `services/web/` reaches the container
only once the image copies it.

Every service runs on the host's network, so each is at `localhost` from
the browser, the host and the other containers alike. The dev environment
is the two committed `.env.dev` files.

For hot module replacement, where an edit is swapped in place and component
state is kept, run `just hmr` instead (`services/web/README.md`, "One
origin, in every mode").

## Adding or removing a service

Each service built from this repo is a folder in `services/`, named like
its Compose service. The folder holds the service's code and its README.
How the services run together is in two files at the root, so the whole
stack reads in one place: `compose.yml` for the dev stack, and the
`Dockerfile` for every image. A ready-made image, like Mongo, needs no
folder: it is a few lines of `compose.yml`.

To add one:

1. Make the folder, with the code.
2. Add the service to `compose.yml`. Start from the closest one: `dev-idp`
   for a Node process, `mongo` for a ready-made image.
3. If it builds from this repo, add a stage to the `Dockerfile`, above the
   release stage. The release stage must stay last, because a build that
   names no target builds the last stage.
4. For a Node service, a `package.json` in the folder makes it a pnpm
   member. Run `pnpm install` to add it to the lockfile. The formatter,
   `just lint`, `just test` and CI then cover it with no other change.

To remove one, undo the same steps: delete the folder, its service and its
stage, then run `pnpm install`. If another service still depends on it,
`just up` stops and names both.

Three limits:

- **The browser sees one origin.** Only `:8000` is the app. A service the
  browser needs goes behind the API, which calls it from the server. A
  second origin would need CORS with credentials, which the template never
  allows.
- **The Python is one project.** A second Python service, such as a
  background worker, needs a uv workspace (`docs/toolchain.md`, "Python"),
  and the Python tools' settings in `pyproject.toml` name `services/api`.
- **Other languages are not wired in.** A Go or Java service needs its own
  lint and test commands added to the `justfile` and CI.

## Replacing the example domain

Clients and orders exist to show the patterns, and a fork replaces them.
Your own code goes in the same places: each `domain/` folder keeps its
name, and holds your code once the example's is gone.

Run `just down` first, and `just up` once your code is in place. The running
API does not notice edits in a folder that was deleted and made again, and
`just up` alone does not restart it.

Delete everything in the "example" column and put your own in its place.
The template imports these names from each side's domain, so keep them:

- In the API, `app/domain/__init__.py` exports `router`, every route, and
  `models`, every Document. `app/domain/seed.py` has `seed()`,
  which inserts the demo data into empty collections.
- In the web app, `src/domain/routes.ts` exports `routes`, the pages under
  the signed-in layout, and `src/domain/Nav.tsx` is the header's actions.

| Side | Example (delete and replace) | Template file that names it, and where |
|---|---|---|
| Backend | `app/domain/`: its models, routes and seed data | `app/main.py` (`domain.router`), `app/db.py` (`domain.models`), `scripts/seed.py` (`models`, `seed`) |
| Backend tests | `tests/domain/`, the seed command's tests among them | — |
| Frontend | `src/domain/`: its pages and their test, `StatusBadge`, `routes` and `Nav` | `src/router.tsx` (`domainRoutes`), `src/components/Layout.tsx` (`<Nav />`) |
| Generated | `services/web/openapi.json`, `services/web/src/lib/api/` | regenerate with `just generate-api` |

The example's 409 comes from its one unique index a caller can collide
with, the client email, and only its router declares it. Give your own
router the 409 if one of its routes can collide (`services/api/README.md`,
"Declaring errors in the OpenAPI schema").

## Renaming the app

The app's name is written out wherever it is used, not derived from one
constant, in two spellings. Find every place with:

```sh
git grep -n "internal-app\|Internal App"
```

Change each one by hand, this file's own lines aside. The name shows in the
page title and header, the API docs' title, and on the provider's consent
screen (`client_name`).

Write your own `description` too, in `pyproject.toml` and in
`services/api/app/main.py`; the API docs show the second.

Then regenerate the files made from these:

```sh
uv lock                     # uv.lock
just generate-api           # services/web/openapi.json
just generate-dev-idp-client   # services/dev-idp/src/client.json
```

The cookie names do not include the app's name (`services/api/AUTH.md`, "Two
cookies"). Compose names the dev stack's containers and volumes after the
folder the repo is in, so renaming the folder starts a fresh dev database.

## Going to production

The template ships an image, not a platform. Every company runs containers
its own way, so the deployment is your copy's to write. Whatever runs the
app has to give it these:

- **The image.** `docker build .` makes it: the API serving the SPA, as a
  non-root user, on port 8000. The app writes no files, so a read-only
  filesystem works.
- **The settings**, as environment variables: `APP_URL`, `OIDC_ISSUER`,
  `OIDC_CLIENT_ID`, `OIDC_CLIENT_KEY` or `OIDC_CLIENT_SECRET`,
  `OAUTH_STATE_SECRET`, `MONGODB_URL` and `MONGODB_DB`. `services/api/.env.dev`
  says what each one is. The secrets come from a secret store, never the
  image. Give `MONGODB_URL` a `timeoutMS` and an `appName` of your own
  (`services/api/README.md`, "The database").
- **HTTPS in front**, from a load balancer or proxy that sets
  `X-Forwarded-Proto`, with `FORWARDED_ALLOW_IPS` set to match
  (`services/api/README.md`, "Security headers").
- **A health check** on `/api/health`, and at least 30 seconds for the app
  to stop (`services/api/README.md`, "Configuration and startup").
- **A MongoDB** the app can reach, with a user that can read and write its
  own database only. Startup creates indexes and never drops one. When a
  release removes an index or changes one's settings, do it by hand with
  `mongosh`: a removal after the deploy, a change before it
  (`services/api/README.md`, "The database").
- **The company's identity provider**, with the app registered as a
  client. `just client-metadata https://…` prints what to register.

For an app people depend on, also run at least two copies in different
zones, keep the database off the public internet, and alarm on 5xx
responses and restarts. Sessions are in the database, so any copy can
answer any request.
