# AGENTS.md

A template for internal web apps behind the company's identity provider:
the RFC 10017 §6.1 backend for frontend, with only local APIs. FastAPI +
Beanie 2 + MongoDB, Vite + React + TanStack Query, a generated TypeScript
client, a Compose dev stack, and one image that deploys anywhere. Clients
and orders are a placeholder domain.

This file holds the rules every change needs. Each part of the repo has
its own rules, and the reasons, in the docs beside it: see "Read relevant
docs".

## Commands

Run `just` from the repo root to list every command and what it does.
They are defined in `justfile`. A new command goes there, with its
description, and docs name it only to say when to run it. A test fails
if a doc names one that does not exist.

## Making changes

### Read relevant docs

Each part has its own docs beside it: what is going on there, and its
rules. Read them before working in that part. `services/api/`, `services/web/` and `services/dev-idp/`
each have a `README.md`; `services/api/` also has `AUTH.md` and
`TESTING.md`. What spans the parts, like Compose, the images and the
toolchain, is in `docs/`.

Libraries that ship agent skills have them linked into `.agents/skills/`
and `.claude/skills/`, for the version in the lockfile. The links point into
`.venv`, so they work after `uv sync`, and CI fails if one breaks. After
adding a library or upgrading Python, run `uvx library-skills --claude` to
link new skills and repair old links.

### Working habits

- Docs are part of the product. Update the README and setup docs in the same change as the code they describe.
- Run `just lint` and `just test` before committing.
- Docs are plain words and short sentences, for a newcomer.
- A comment describes only the code beside it, and why, in plain words.
  Code that reads clearly gets none. A comment never names or describes
  another part of the repo, even without naming it: that goes stale when
  the other part changes, and nothing checks it. A link between parts that
  matters is enforced by a test, not written down. Outside tools and specs
  may be named, since they don't move with a refactor. Docstrings are a few
  sentences. Code meeting a spec cites its section on that line
  (`# RFC 10017 §6.1.3.2`).
- In the API, `app/core/` is the template and `app/domain/` is the
  example; `db.py` binds the models of both, and `main.py` assembles them. App behaviour goes in `domain/`,
  machinery every app needs in `core/`.
- The example domain stays removable. Only the seam files listed in
  `docs/adopting.md`, "Replacing the example domain", import it, and a test
  fails if any other file does; when the seam moves, update that list. A
  template test that needs a route finds it in the OpenAPI paths or uses a
  template route.

### Never

Breaking one of these is a security hole, or a mistake nothing reports
until later.

- **Never add password handling, registration, or reset/verification
  flows.** The identity provider owns credentials.
- **Never give the browser a token**: not in `localStorage`, not in an
  `Authorization` header. The API checks the access and refresh tokens at
  the callback and discards them. The only header the frontend adds is
  `X-CSRF: 1`.
- Never add CORS that allows credentials.
- Never let sign-in take a caller-supplied destination; the callback always
  lands on `/`.
- Never deploy the dev provider, and never write code against it: the API
  reaches it only through discovery.
- Never leave a domain router without `dependencies=AUTHENTICATED`, and
  never widen the CSP to silence a console error.
- **Never hand-edit `services/web/src/lib/api/` or `services/web/openapi.json`.** Run
  `just generate-api` and commit the diff.
- Never register anything on the app in the lifespan: `just generate-api`
  imports `main.py` without running startup.
- Never run `npx`.
