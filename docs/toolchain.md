# Toolchain

How the Python and Node sides are installed, checked and pinned. Why each
tool was chosen over the others is in `docs/decisions.md`, "Choices tested here".

Each language has one lockfile and one install, at the repo root. They are
organised differently, because the two sides are shaped differently.

## Python

Python is one project. The root `pyproject.toml` lists the API's
runtime dependencies, plus the `dev` dependency group: tools that are only
ever used locally and never enter an image.

| What | Declared as | Used by | In the image? |
|---|---|---|---|
| The API's runtime | `[project] dependencies` | uvicorn, in `services/api/` | yes |
| `dev` | a dependency group | ruff, pyrefly, pytest | no |

`uv sync` installs both into `.venv` at the root, since uv installs the
`dev` group by default. The image runs `uv sync --no-dev`, which is the
runtime alone. `services/api/` is not an installable package: uvicorn runs `app/`
from it. The tools find the code without help: `services/api/tests/` is a package,
so pytest works out that imports start at `services/api/`, and pyrefly finds `app`
through its `search-path` setting. Ruff and pyrefly are configured in the
same file and run from the root over everything.

## The type checker

pyrefly is the type checker, from Meta. It is pinned to an exact version,
because any release can change what it reports. Upgrading it is
deliberate: bump the pin, run `just lint`, and fix or suppress anything
new. It runs with `preset = "default"`. Without a config, pyrefly uses its
lenient `basic` preset, which here missed even `x: int = "s"`. A
suppression is `# pyrefly: ignore[error-kind]`, and one that stops
suppressing anything fails the lint (`unused-ignore`). pyrefly does not
require annotations, so ruff's `ANN` rules do.

It is also the editor's language server: errors, navigation, hover and
completions. The extension (`meta.pyrefly`) runs the pinned pyrefly from
`.venv`, so the editor and `just lint` agree. Pylance is switched off
(`"python.languageServer": "None"`), so two servers do not report the same
thing.

What no checker catches is a misspelled field on a document itself, or a
missing required field when building one: Beanie's `Document.__init__`
takes `*args, **kwargs`. The API tests run every route against a real
database, so a typo on a document fails there.

## Node

Node is one pnpm workspace. A workspace is a set of member directories
that share one lockfile and one store. `pnpm-workspace.yaml` makes every
folder in `services/` with a `package.json` a member: today `web` and
`dev-idp`. Each member lists the packages its own code
uses, and the lockfile and store (`node_modules/.pnpm`) are at the root.
`pnpm -r test` runs `test` in every member that
has one and skips the rest, so the justfile and CI name no member. A script
a member runs for itself, like `typecheck`, lives in its own `package.json`.

The formatter is the exception: oxfmt is installed once, at the root, and
formats everything in `services/`, as ruff does for the Python. Its settings are in
`.oxfmtrc.json`, chosen to match the code as it was written: single quotes,
no semicolons, 100 columns like ruff. It also sorts imports and Tailwind
classes. Generated files and Markdown are left alone. `pnpm format` writes,
and `just lint` and CI check with `--check`.

A Node image installs one member (`pnpm install --filter web`), from the
lockfile and that member's own `package.json` alone. pnpm still refuses to
install if the two disagree. So editing one member's manifest never
rebuilds another member's image. On both sides the cost of one lockfile is
the same: changing any dependency rebuilds the image's dependency layer. The rebuild downloads only
what changed, because pnpm's and uv's caches are kept between builds, outside
the image.

Why the two sides differ: a pnpm workspace is how pnpm handles several
`package.json` files, and this repo has three. uv's docs describe its
workspaces as "multiple interconnected packages", and the Python here is
neither packages nor interconnected. It is one service's runtime and its
local tools, which is what dependency groups are for. A second
Python service with its own runtime, such as a background worker, is the
case a uv workspace exists for.

## Pinned versions

The tool versions are pinned in files that local runs and CI both read:

| Tool | Pinned by | How it is enforced |
|---|---|---|
| pnpm | `packageManager` in the root `package.json` | pnpm switches itself to that version, locked with its checksum in `pnpm-lock.yaml` |
| Node | `devEngines.runtime` in the root `package.json` | pnpm downloads that Node and runs every member's scripts with it; it is locked in `pnpm-lock.yaml` like a package |
| Python | `requires-python` in the root `pyproject.toml`, and the API image's tag | uv picks a matching interpreter for the `.venv`, downloading one if none is installed |
| uv | `required-version` in the root `pyproject.toml` | uv refuses to run if it is older; CI's `setup-uv` installs a matching one |

uv's pin is a minimum, not an exact version, because uv cannot switch
itself to another version the way pnpm does. An exact pin would break every
machine the day its uv upgraded. The images pin an exact uv of their own.

just is pinned only in CI, where uvx runs that exact version from PyPI.
Locally, any recent just runs the justfile, and an old one stops at the
first thing it does not know.

Nothing here runs `npx`. npm reads the same `devEngines` field, does not
support downloading the Node it names, and fails with `EBADDEVENGINES`.
