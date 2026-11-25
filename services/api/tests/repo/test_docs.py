"""The docs point only at things that exist.

A doc names another file with a link, and a section of it by quoting the
section's heading beside the file's name. Both go stale the moment a file
moves or a heading is renamed, and nothing else would notice. These tests
read every doc and config file and check each link and each cited section,
and every just command named anywhere in the repo.
"""

import re
import subprocess
from pathlib import Path

from tests.helpers import ROOT

SCANNED = {".md", ".yml", ".yaml", ".json"}
# Commands are also named in code: an error message, a comment, a page.
COMMANDS_SCANNED = SCANNED | {".py", ".ts", ".tsx", ".html", ""}

# A Markdown link to a file in the repo: not a URL, an anchor or a site path.
LINK = re.compile(r"\[[^\]]*\]\((?!https?:|mailto:|#|/)([^)\s]+)\)")
# A file named beside a quoted section, with or without backticks.
CITATION = re.compile(r"`?([\w./-]+\.md)`?,\s+\"([^\"]+)\"")
# A bullet that opens with a bold label, which is cited like a heading.
LABEL = re.compile(r"^\s*- \*\*(.+?)[.:]?\*\*")
# A recipe's first line in the justfile: its name, its parameters, then a
# colon that does not start an assignment.
RECIPE = re.compile(r"^@?([a-z][\w-]*)\b[^:\n]*:(?!=)", re.MULTILINE)
# A just command in backticks, in HTML code, or run by uvx.
COMMAND = re.compile(r"(?:`|<code>|\buvx .* )just ([a-z][\w-]*)")


def scanned_files(suffixes: set[str] = SCANNED) -> list[Path]:
    """Every doc and config file in the repo: those git tracks, and new ones
    it would. Git's ignore rules leave out dependencies, build output and
    anything private to one clone."""
    listed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    files = (ROOT / name for name in listed if Path(name).suffix in suffixes)
    # A tracked file deleted but not yet committed is still listed.
    return sorted(f for f in files if f.is_file())


def sections(path: Path) -> set[str]:
    """Every heading and bold bullet label in a Markdown file, outside code
    blocks."""
    found, in_code = set(), False
    for line in path.read_text().splitlines():
        if line.startswith("```"):
            in_code = not in_code
        elif in_code:
            continue
        elif line.startswith("#"):
            found.add(" ".join(line.lstrip("#").split()))
        elif label := LABEL.match(line):
            found.add(label.group(1))
    return found


def broken_references(path: Path) -> list[str]:
    """Each link and cited section in the file at `path` that points at nothing."""
    text = path.read_text()
    broken = []
    for target in LINK.findall(text):
        if not (path.parent / target.split("#")[0]).exists():
            broken.append(f"link to {target}")
    for name, section in CITATION.findall(text):
        cited = ROOT / name
        section = " ".join(section.split())
        if not cited.exists():
            broken.append(f"{name} does not exist")
        elif section not in sections(cited):
            broken.append(f'{name} has no section "{section}"')
    return broken


def test_every_link_and_cited_section_exists() -> None:
    files = scanned_files()
    names = {f.relative_to(ROOT).as_posix() for f in files}
    assert {"README.md", "services/api/README.md", "compose.yml"} <= names, "docs not found"

    broken = [
        f"{f.relative_to(ROOT)}: {problem}" for f in files for problem in broken_references(f)
    ]
    assert not broken, "\n".join(broken)


def named_commands(path: Path) -> set[str]:
    """Every just command the file at `path` names, and each line of a
    Markdown code block that runs one."""
    names, in_code = set(), False
    for line in path.read_text().splitlines():
        if line.startswith("```"):
            in_code = not in_code
        elif in_code and line.startswith("just "):
            names.add(line.split()[1])
        names.update(COMMAND.findall(line))
    return names


def test_every_named_command_exists() -> None:
    """Docs say when to run a command and the justfile says what it does, so
    a renamed recipe would leave the docs naming one that is gone."""
    recipes = set(RECIPE.findall((ROOT / "justfile").read_text()))
    assert {"up", "test", "generate-api"} <= recipes, "recipes not found"

    missing = [
        f"{f.relative_to(ROOT)}: just {name}"
        for f in scanned_files(COMMANDS_SCANNED)
        for name in sorted(named_commands(f) - recipes)
    ]
    assert not missing, "\n".join(missing)
