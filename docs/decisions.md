# Decisions

What the template leaves out, and what it has not done yet. Both are
decisions with a reason, kept here so nobody repeats the research.

The template was built privately, from August to November 2026 and over 300
commits, then published with a new history. What was tried and dropped along
the way is recorded here.

## Current gaps

What to fix next, most important first. Each one is known and accepted for
now. When one is fixed, delete it here. When a new one is found, add it.
Something left out on purpose belongs in "Deliberately omitted" below
instead.

**Before a second identity provider**

- **No `iss` check on the callback**
  ([RFC 9207](https://www.rfc-editor.org/rfc/rfc9207)). It defends against
  mix-up attacks, where one provider's response is passed off as another's.
  [RFC 9700 §2.1](https://www.rfc-editor.org/rfc/rfc9700.html#section-2.1)
  only requires a defense when a client talks to more than one provider.
  Authlib's client does not check it.
- **Users are keyed on `sub` alone.** OIDC Core §5.7 makes `iss` plus `sub`
  the stable key. Two providers could issue the same `sub` to different
  people.

**Security**

- **Revocation lags the provider.** A user disabled at the provider keeps
  their session for up to `SESSION_MAX` (10 hours), unless
  the provider sends back-channel logout. Fixes: a shorter maximum, or
  re-checking the provider during the session (`services/api/AUTH.md`, "The tokens
  are discarded; the ID token is kept").
- **Changing the key can fail sign-ins for a few minutes.** The app serves
  one key at `/api/auth/jwks`, and a provider may keep the old set for as
  long as it caches it (the app allows five minutes). Sign-ins in that
  window carry the new key's `kid`, which the cached set lacks; some
  providers fetch again on an unknown `kid`, and others refuse. Fix: a
  second setting for the next key, served beside the current one before the
  app switches to it.
- **Entra ID's certificate credentials are untried.** Entra takes a
  certificate rather than a bare key, and expects an `x5t` header and the
  token endpoint as the audience. The app sends a `kid` and the issuer, so
  Entra may need both to change.

**Features**

- **No helper for calling other services as the app** (`services/api/README.md`,
  "Calling other services"). Every fork that needs one will write its own
  client-credentials code.
- **No roles.** Every signed-in user can do everything. Providers send group
  or role claims, but nothing reads them. The first fork that needs an admin
  will need this.
- **`users` rows are kept forever.** Someone who leaves the company can no
  longer sign in, but their `User` document stays. There is no retention
  rule and no SCIM deprovisioning.

**Delivery**

- **TypeScript stays on 6.0.** 7.0 has no JavaScript API yet, and the
  client generator needs one; TypeScript is its peer, so it cannot be given
  6.0 alone. Upgrade when the generator supports 7.1's new API
  ([TypeScript 7.0](https://devblogs.microsoft.com/typescript/announcing-typescript-7-0/)).
- GitHub Actions are pinned to tags, not commit SHAs.
- Nothing updates dependencies automatically (Renovate or Dependabot).
- The image is not scanned for vulnerabilities, and has no SBOM.
- The Docker build in CI has no layer cache.

## Deliberately omitted

Each of these is standard somewhere. Here it would add a tool, a layer or
configuration that an internal app behind a company provider does not need.
A new rejection goes here with its reason. Something that should be added
but is not yet is a gap instead ("Current gaps" above).

**Distribution**

- **An update path for copies (Copier, cruft, merging from upstream)** — a copy owns its code outright and is expected to change even the tools, so there is nothing stable to merge into. A security fix reaches copies as an advisory and a commit to port by hand (`docs/adopting.md`, "Your copy is yours").
- **A brand name** — a brand makes a template read as a product. People find a template by searching for what it is, then rename their copy, so the repository is named for what it is (`internal-app-template`), and the code calls the app `internal-app`, the placeholder a copy renames.
- **Releases and versions** — nothing installs the template, so a version would name nothing. An advisory names the fixing commit instead.
- **A license that copies must carry (MIT, Apache-2.0)** — most copies become private company apps. MIT No Attribution lets them drop the notice.

**Auth**

- **Owning credentials** — no passwords, registration, reset or verification. The company's provider proves who someone is (`services/api/AUTH.md`).
- **A token in the browser, and an auth store** — the session is an HttpOnly cookie, so there is no token for a script to steal. Sign-in state is a query like any other (`services/web/README.md`, "Auth").
- **Storing user tokens (the full BFF)** — nothing calls another service as the user. Adding it is six steps (`services/api/README.md`, "Calling other services").
- **A CSRF token (synchronizer or double-submit)** — a fixed `X-CSRF: 1` header does the same job here. Another site's page can only add a header after a CORS preflight, which this API never answers, so the header's presence is the proof, not its value ([RFC 10017 §6.1.3.3.2](https://www.rfc-editor.org/rfc/rfc10017.html#section-6.1.3.3.2); [OWASP, "Custom request headers"](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html#employing-custom-request-headers-for-ajaxapi)). A token would need storing, handing to the SPA and checking, for no gain. It holds only while no CORS allows credentials (`services/api/AUTH.md`).
- **Bearer tokens for non-browser callers** — the API has one client, the SPA. A second kind of caller would need a second way to authenticate, and the CSRF rules would not apply to it.
- **SCIM provisioning** — the provider decides who can sign in, and a `User` is written at first sign-in. SCIM would matter for removing data about people who left (a current gap).
- **A library for back-channel logout** — Authlib has no client side for it, so the logout token is validated in `auth.py`, step by step. `idpyoidc` was tried and rejected: it is synchronous, keeps sign-in state in process memory, and its `LogoutToken.verify()` accepted an expired token and skipped the `iss` and `aud` checks when an argument was left out.

**API**

- **Service / repository layers** — tried, measured and removed: a third of their methods were one-line passthroughs (`services/api/README.md`, "Layering").
- **The rest of RFC 9457: `type`, `title`, `instance` and `application/problem+json`** — errors use its member names `status` and `detail` (plus `fields`), as plain JSON. The rest helps generic clients and gateways tell problems apart; this API's one client renders `detail` (`services/api/README.md`, "Errors on the wire").
- **A migration framework** — documents are schemaless and changes are additive. A one-off script is less than standing machinery.
- **Celery / Redis** — there is no background work.
- **GraphQL** — a REST API with a generated, typed client gives the same developer experience with less machinery.
- **Motor** — deprecated, end of life May 2026. The driver is PyMongo's own `AsyncMongoClient`, under Beanie 2.
- **`fastapi run` / `fastapi[standard]`** — it runs uvicorn, which the image runs directly. The extra adds about 20 packages to the image.
- **`http.route` on the request's log line** — tried and removed. Since FastAPI 0.137 the route a request records leaves out its routers' prefixes, so `/api/clients` logged as `/clients`, and only a private key holds the full template ([FastAPI discussion #16051](https://github.com/fastapi/fastapi/discussions/16051); still so in 0.165). `url.path` carries the full path. Bring it back when FastAPI records the full template.
- **A catch-all route for unknown `/api` paths** — tried and removed. FastAPI's frontend fallback already gives every unknown path a 404, except a browser visit that accepts HTML, which gets `index.html` ([FastAPI, "Frontend"](https://fastapi.tiangolo.com/tutorial/frontend/)). The catch-all had to be included after every other router, an order nothing enforced, and answered other methods with a 405, as if the path existed.

**Frontend**

- **Next.js / SSR** — a small authenticated SPA gets nothing from server rendering but a second runtime.
- **Redux / Zustand** — all shared state is server state, and TanStack Query's cache already holds it.
- **A component library (shadcn, MUI, Chakra)** — a dozen Tailwind-styled elements do the job, and are the learning exercise.
- **Zod / form libraries** — the API is the one validator. Its errors are shown as they come back.
- **ESLint** — the Vite template ships oxlint, which is fast and needs no config.
- **Prettier** — oxfmt, from the same project as oxlint, formats the same way with Prettier's options, and sorts imports and Tailwind classes without plugins. One catch: its import sorting moves imports above a `/// <reference>` line, which then stops working, so no file uses one.
- **Storybook / Playwright / end-to-end tests** — a few Vitest tests beside the code set the pattern.

**Data**

- **A command that syncs the indexes to the code** — tried and removed. It dropped every index no model declares, including one an operator or Atlas's Performance Advisor added; Mongoose's `syncIndexes()` has dropped a unique index that way. Dropping or changing an index is rare and deliberate, so it is done by hand (`services/api/README.md`, "Indexes").
- **Startup that skips an index the database blocks** — tried and reverted. It kept a copy starting mid-way through an index change, but meant reading each model's indexes outside Beanie and running without one the code declares. Startup is `init_beanie` with its defaults, as MongoDB's own FastAPI integration runs it ([fastapi-pymongo](https://github.com/mongodb/fastapi-pymongo)).
- **A replica set for the dev database** — nothing uses transactions or change streams, and CI runs standalone too, so deleting a client and its orders is two writes. To add one: `command: ["mongod", "--replSet", "rs0"]` on the `mongo` service, `rs.initiate({ _id: "rs0", members: [{ _id: 0, host: "localhost:27017" }] })` run once (a file in `/docker-entrypoint-initdb.d` does that on a fresh volume), and the same in CI. Without it, a transaction fails with "Transaction numbers are only allowed on a replica set member".
- **`mongodb/mongodb-atlas-local`** — it bundles Atlas Search, which nothing uses, at twice the size, and needs `?directConnection=true` everywhere.
- **testcontainers** — a second database name in the same Compose Mongo isolates the tests.

**Tooling**

- **A uv workspace, and a lockfile per directory** — the Python is one service and its tools, not packages (`docs/toolchain.md`; "One lockfile per language" below).
- **Making the API an installable package** — pytest and pyrefly find `app` without it, and the editable install broke under iCloud ("The API is not an installable package" below).
- **mypy** — replaced by ty, which was about 50 times faster here from a cold start ("The type checker: pyrefly" below).
- **ty** — replaced by pyrefly, which resolves what Beanie documents inherit where ty could not, at the same speed ("The type checker: pyrefly" below).
- **Make** — every target was a plain command, not a file to build. just lists the commands with their descriptions, takes arguments, and has no tab or `$$` rules. It is one more tool to install, from PyPI with uv.
- **Nx / Turborepo** — nothing needs a task graph or caching yet. Revisit when `just lint` is slow enough to notice.
- **Pre-commit hooks** — lint is defined once, in `just lint`, and CI runs it.
- **A Dockerfile per service** — tried here. The release image is the API plus the built SPA, so the API's Dockerfile needed the web's image: a plain `docker build` failed, and the two builds in turn took 26–29 s against 13–14 s for one file, which builds both halves at once. The dev images built no faster. pnpm's Docker guide also uses one Dockerfile with a target per app.
- **A Compose file per service (`include`)** — tried here. `include` names every file, so nothing was automated, and the services were not independent: the API's file depended on three others and their volume and settings. One root file reads the whole stack in one place. A copy with many services can split it later.
- **Compose watch (`develop.watch`)** — it needed a terminal held open, and rebuilt on a `git checkout`. `just up` does the same when asked.
- **`node --watch` for the dev provider** — it silently stops watching after one atomic save. nodemon does not.
- **A dev container** — one lived here and was removed: nobody used it, CI could not test it, and every team sets up editors its own way. What one needed: the repo mounted at the host's own path, because Compose inside talks to the host's Docker; a volume over `.venv` and each `node_modules`, so Linux packages never land on the host; and no `docker compose down --remove-orphans` from inside, which removes the editor's own container. It is not a security boundary: whatever reaches the Docker socket can mount the host's disk.

**Infrastructure**

- **Deployment code (CDK, Terraform, Kubernetes manifests)** — every company runs containers its own way, and a copy would delete whichever one it did not use. The template ships the image and a list of what a platform must give it (`docs/adopting.md`, "Going to production"). AWS stacks lived here once; they made `uv sync` 264 MB of its 327 MB.
- **Feature flags / i18n / Sentry** — nothing needs them yet.

## Choices tested here

These were settled by building the alternatives here and comparing what
happened. Entries above that point here are these.

### The type checker: pyrefly

pyrefly replaced ty, which replaced mypy. All three were tried here:

| | mypy | ty 0.0.84 | pyrefly 1.3.2 |
|---|---|---|---|
| Cold start, whole repo | 47 s | about 1 s | about 1 s |
| Status | stable | beta | stable |
| Result type of `await Session.find_one(...)` | not measured | unknown | `Session \| None` |
| Wrong return type from a Beanie query | not measured | not reported | reported |
| Editor | not used | errors only; Pylance for the rest | everything |

The difference is the Beanie documents (`User`, `Session`, `Client`,
`Order`). `Document`'s first base class comes from `lazy-model`, which picks
between two classes at runtime by reading Pydantic's version. ty could not
use a base that could be either class, so it treated everything a document
inherits as unknown and stayed silent about it. pyrefly resolves it, so the
result of a query has a real type and mistakes made with it are reported.

### The API is not an installable package

Making `api` installable was built and tested here, and it broke. An
editable install is a `.pth` file in the venv. iCloud sets the macOS hidden
flag on files in synced folders (Desktop and Documents), and Python 3.12.3+
skips hidden `.pth` files. So `import app` worked after `uv sync` and failed
a minute later, with no error pointing at the cause.
[FastAPI's own Docker guide](https://fastapi.tiangolo.com/deployment/docker/)
runs `app/` without installing it, as this repo does.

### One lockfile per language

Before this, each directory had its own lockfile, four in all. One per
language closed a real gap: one directory had been checked by nothing. It
also gives one place each tool is pinned, and a place for shared code: when a
second member needs the generated client, `services/web/src/lib/api/` can become a
package they both import.

### A fake provider, not patched Authlib

The auth tests once patched Authlib's methods. They now run against a fake
provider in process (`services/api/TESTING.md`).

| | Patching Authlib's methods | A fake provider |
|---|---|---|
| What runs | The app's code between two patched calls | The app's code and Authlib's, end to end |
| State, nonce, PKCE, ID-token signature | Never checked | Checked on every sign-in |
| A failure is | A replaced function raising | The provider answering badly, or not at all |
| Depends on | Authlib's method names and its private cache key | The HTTP requests OIDC defines |
