"""The template does not depend on the example domain.

Clients and orders are a placeholder. A fork empties `app/domain/`,
`tests/domain/` and the web app's `src/domain/`, and puts its own code in
their place. Everything else — auth, the database, errors, the SPA shell,
and the tests of all of those — must still import and run. That is only
true while nothing else reaches into the domain, which is the kind of thing
that erodes one convenient import at a time. These tests read the imports
and refuse the erosion.

A few files may import the domain, to bind it in. In the API, `main.py`
(its router), `db.py` (its documents) and the dev seed script (its
documents and demo data). In the web app, `router.tsx` (the pages) and `Layout.tsx` (the
header's actions). Those are the whole seam.
"""

import ast
import re
from pathlib import Path

from fastapi import FastAPI

from app import core
from app.main import app

TESTS = Path(__file__).parents[1]


### THE API


APP = TESTS.parent / "app"
SCRIPTS = TESTS.parent / "scripts"
BINDS_THE_DOMAIN = {APP / "main.py", APP / "db.py", SCRIPTS / "seed.py"}


def imports_of(path: Path) -> set[str]:
    """Every module the file at `path` imports."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            # `from app import domain` imports app.domain too.
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def imports_the_domain(path: Path) -> bool:
    return any(name.split(".")[:2] == ["app", "domain"] for name in imports_of(path))


def test_template_modules_do_not_import_the_domain() -> None:
    """Found, not listed, so a module added later is checked too."""
    modules = [
        *(path for path in APP.rglob("*.py") if (APP / "domain") not in path.parents),
        *SCRIPTS.glob("*.py"),
    ]
    assert {"auth.py", "security.py"} <= {path.name for path in modules}, "found no modules"
    for path in modules:
        if path not in BINDS_THE_DOMAIN:
            name = path.relative_to(TESTS.parent)
            assert not imports_the_domain(path), f"{name} imports the domain"


def test_template_tests_do_not_import_the_domain() -> None:
    """The template's tests outlive the example too. One that needs a domain
    route finds it in the app's OpenAPI document instead."""
    for path in TESTS.rglob("*.py"):
        if (TESTS / "domain") not in path.parents:
            assert not imports_the_domain(path), f"{path.relative_to(TESTS)} imports the domain"


def test_the_domain_is_bound_in_by_its_modules() -> None:
    for path in BINDS_THE_DOMAIN:
        assert imports_the_domain(path), f"{path.relative_to(TESTS.parent)} no longer binds it"


### THE WEB APP


WEB = TESTS.parents[1] / "web" / "src"
WEB_DOMAIN = WEB / "domain"
WEB_BINDS_THE_DOMAIN = {WEB / "router.tsx", WEB / "components" / "Layout.tsx"}
# The generated client holds every operation, the domain's too.
GENERATED = WEB / "lib" / "api"

# The names between the braces of an import, and the module they come from.
NAMED_IMPORT = re.compile(r"""\bimport\s+(?:type\s+)?\{([^}]*)\}\s*from\s*['"]([^'"]+)['"]""")

# The module named by `from '…'`, `import '…'` or `import('…')`.
IMPORTED = re.compile(r"""(?:\bfrom|\bimport)\s*\(?\s*['"]([^'"]+)['"]""")


def web_imports_the_domain(path: Path) -> bool:
    for spec in IMPORTED.findall(path.read_text()):
        if spec.startswith("."):
            target = (path.parent / spec).resolve()
            if target == WEB_DOMAIN or WEB_DOMAIN in target.parents:
                return True
    return False


def test_web_template_files_do_not_import_the_domain() -> None:
    """Found, not listed, so a file added later is checked too."""
    files = [*WEB.rglob("*.ts"), *WEB.rglob("*.tsx")]
    assert WEB / "main.tsx" in files, "found no files"
    for path in files:
        if WEB_DOMAIN in path.parents or GENERATED in path.parents:
            continue
        if path not in WEB_BINDS_THE_DOMAIN:
            assert not web_imports_the_domain(path), f"{path.relative_to(WEB)} imports the domain"


def test_the_web_domain_is_bound_in_by_its_two_files() -> None:
    for path in WEB_BINDS_THE_DOMAIN:
        assert web_imports_the_domain(path), f"{path.relative_to(WEB)} does not import the domain"


def api_names(api: FastAPI) -> tuple[set[str], set[str]]:
    """The operations and the schemas of `api`, as the generated client names them."""
    schema = api.openapi()
    operations = {
        # list_clients -> listClients
        re.sub(r"_(\w)", lambda match: match[1].upper(), operation["operationId"])
        for path in schema["paths"].values()
        for operation in path.values()
    }
    return operations, set(schema["components"]["schemas"])


def generated_imports(path: Path) -> set[str]:
    """Every name the file at `path` imports from the generated client."""
    return {
        # `type Name as Alias` -> Name
        name.strip().removeprefix("type ").split()[0]
        for names, spec in NAMED_IMPORT.findall(path.read_text())
        if spec.startswith(".") and (path.parent / spec).resolve().is_relative_to(GENERATED)
        for name in names.split(",")
        if name.strip()
    }


def test_web_template_files_do_not_use_the_domains_generated_names() -> None:
    """A copy with another domain regenerates the client without them."""
    template = FastAPI(responses=core.responses)
    template.include_router(core.router)
    template_operations, template_schemas = api_names(template)
    operations, schemas = api_names(app)
    # One operation makes many names: listClients, listClientsOptions, ListClientsData.
    prefixes = tuple(name.lower() for name in operations - template_operations)
    domain_schemas = schemas - template_schemas

    files = [
        path
        for path in (*WEB.rglob("*.ts"), *WEB.rglob("*.tsx"))
        if WEB_DOMAIN not in path.parents and GENERATED not in path.parents
    ]
    assert "getMeQueryKey" in generated_imports(WEB / "lib" / "auth.ts"), "found no imports"
    for path in files:
        used = {
            name
            for name in generated_imports(path)
            if name in domain_schemas or name.lower().startswith(prefixes)
        }
        assert not used, f"{path.relative_to(WEB)} uses the domain's {sorted(used)}"
