# Every dev command. `just` lists them, from the comment above each recipe.

# The dev origin, which the committed dev client is registered for.
dev_app_url := shell("sed -n 's/^APP_URL=//p' services/api/.env.dev")

[private]
default:
    @just --list --unsorted

# Every Python and Node dependency, for the editor and the host-side tools
[group('setup')]
install:
    uv sync
    pnpm install

# Build and start the stack, then return. Again after a lockfile or build-config change.
[group('stack')]
up:
    docker compose up --build -d
    @echo "App: http://localhost:8000  (API under /api, health at /api/health)"
    @echo "Identity provider: http://localhost:8080 — sign in as admin, or any username (any password)"

# The same stack with Vite answering :8000, for hot module replacement, and the API behind it on :8001
[group('stack')]
hmr:
    docker compose -f compose.yml -f compose.hmr.yml up --build -d
    @echo "App: http://localhost:8000  (Vite, hot module replacement; API under /api, docs at /api/docs)"
    @echo "Identity provider: http://localhost:8080 — sign in as admin, or any username (any password)"

# Stop either stack
[group('stack')]
down:
    docker compose down

# Reset the dev database's example data to demo data. Sign-ins stay.
[group('stack')]
seed: mongo
    uv run --directory services/api python -m scripts.seed

# Start the Compose Mongo, or wait for it if it is starting
[private]
mongo:
    docker compose up -d --wait mongo

# Every test: the API's, then every Node member's
[group('checks')]
test: test-api
    pnpm -r test

# The API's tests, against the Compose Mongo's appdb_test. Takes pytest's arguments: just test-api services/api/tests/core -k name
[group('checks')]
[positional-arguments]
test-api *args: mongo
    uv run pytest -q "$@"

# Ruff and pyrefly over all the Python; oxfmt, tsc and oxlint over the TypeScript
[group('checks')]
lint:
    uv run ruff check .
    uv run ruff format --check .
    uv run pyrefly check
    pnpm format --check
    pnpm -r typecheck
    pnpm -r lint

# Rewrite the Python and TypeScript in the house style that lint checks
[group('checks')]
format:
    uv run ruff format .
    pnpm format

# A new key pair for private_key_jwt: the private key for the secret store, then its public JWK Set
[group('auth')]
client-key:
    @uv run --directory services/api python -m scripts.client_key

# What to register with a provider for the app at an origin, the dev stack's by default
[group('auth')]
client-metadata app_url=dev_app_url:
    @uv run --directory services/api python -m scripts.client_metadata {{ quote(app_url) }}

# Rewrite the dev provider's committed client from the dev origin's metadata.
[group('generate')]
generate-dev-idp-client:
    @just client-metadata > services/dev-idp/src/client.json

# Regenerate the web app's OpenAPI schema and TypeScript client from the app. Both are committed.
[group('generate')]
generate-api:
    uv run --directory services/api python -m scripts.openapi > services/web/openapi.json
    pnpm -r generate:api
