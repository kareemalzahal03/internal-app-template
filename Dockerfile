# Every image, one stage each, built from the repo root. The release stage is last, so a plain `docker build` makes it.

### node-dep: the pnpm workspace, before any member is installed
# https://pnpm.io/docker
FROM ghcr.io/pnpm/pnpm:12 AS node-dep
WORKDIR /app
# Copy only the root manifests. Each stage adds its own member's, so editing one never rebuilds another.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./

### web-dep: the SPA's dependencies and build config
FROM node-dep AS web-dep
COPY services/web/package.json services/web/
# Install the SPA's packages, and the pnpm and Node pinned in package.json.
# Keep pnpm's store between builds, so a lockfile change downloads only what changed.
RUN --mount=type=cache,id=pnpm,target=/root/.cache/pnpm \
    pnpm install --frozen-lockfile --filter web --store-dir /root/.cache/pnpm/store
# Copy the build config. Vite and tsc read it once, so a change needs a rebuild.
COPY services/web/index.html services/web/vite.config.ts services/web/tsconfig.json services/web/tsconfig.app.json services/web/tsconfig.node.json services/web/
# Copy the static files. A watching build copies them once, so a change needs a rebuild too.
COPY services/web/public/ services/web/public/

### web-build: the SPA, built to services/web/dist
FROM web-dep AS web-build
COPY services/web/ services/web/
# Type-check, then build.
RUN pnpm --filter web build

### dev-idp: the dev identity provider's dependencies. Never deployed.
FROM node-dep AS dev-idp
COPY services/dev-idp/package.json services/dev-idp/
RUN --mount=type=cache,id=pnpm,target=/root/.cache/pnpm \
    pnpm install --frozen-lockfile --filter dev-idp --store-dir /root/.cache/pnpm/store

### api-dep: Python and the API's runtime dependencies
# https://docs.astral.sh/uv/guides/integration/docker/
FROM python:3.15-slim-trixie AS api-dep
WORKDIR /app

# Send logs to stdout at once, even if the process crashes.
ENV PYTHONUNBUFFERED=1
# Precompile to bytecode for faster starts.
ENV UV_COMPILE_BYTECODE=1
# Copy packages out of the cache mount. Links into it would dangle.
ENV UV_LINK_MODE=copy
# Use this image's Python, never download one.
ENV UV_PYTHON_DOWNLOADS=0

# Install the runtime only, without the dev group.
# Mount uv and the manifests for this step only, so none enters a layer.
RUN --mount=from=ghcr.io/astral-sh/uv:0.13.9,source=/uv,target=/bin/uv \
    # Keep uv's download cache between builds.
    --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev

# Put the venv's commands, like uvicorn, first on the PATH.
ENV PATH="/app/.venv/bin:$PATH"

# Set uvicorn's settings for every command that runs the app. A command adds only what differs.
# https://www.uvicorn.org/settings/
ENV UVICORN_HOST=0.0.0.0
ENV UVICORN_PORT=8000
# Exit on any startup failure, rather than serve 500s.
ENV UVICORN_LIFESPAN=on
# Skip uvicorn's access line. The app logs one line per request itself.
ENV UVICORN_ACCESS_LOG=false
# Write every log line as JSON, uvicorn's own from its first.
ENV UVICORN_LOG_CONFIG=app/core/logging.json
# On stop, finish running requests for up to 20 s, inside the 30 s most platforms give before a kill.
ENV UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN=20

### release: the API serving the SPA. Any new stage goes above this one.
FROM api-dep AS release
COPY services/api/app /app/app
# Copy the built SPA beside the code.
COPY --from=web-build /app/services/web/dist /app/frontend

# Run unprivileged. The code and SPA stay root-owned and read-only to it.
RUN groupadd --system --gid 999 nonroot \
  && useradd --system --gid 999 --uid 999 --create-home nonroot
USER nonroot

EXPOSE 8000
# Run one process, no reload. The platform supplies the environment.
CMD ["uvicorn","app.main:app"]
