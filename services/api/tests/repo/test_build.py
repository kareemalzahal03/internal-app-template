"""The files that build and run the app keep the promises the app relies on.

The app exits on a failed startup only because uvicorn runs its lifespan
"on", and a deploy ships the release image only because it is the last
stage. Neither is visible from the app's code, so these read the files.
"""

import shlex

from pytest import mark

from tests.helpers import ROOT


def test_the_image_every_command_runs_in_exits_on_a_failed_startup_and_logs_json() -> None:
    """uvicorn reads each setting from a UVICORN_ variable when its flag is
    not given. The stage that every image of the API builds from sets them.
    Without the log config, the app's own lines below WARNING, its request
    lines among them, would be dropped."""
    lines = (ROOT / "Dockerfile").read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.endswith("AS api-dep"))
    end = next(i for i, line in enumerate(lines) if i > start and line.startswith("FROM "))
    assert "ENV UVICORN_LIFESPAN=on" in lines[start:end]
    assert "ENV UVICORN_LOG_CONFIG=app/core/logging.json" in lines[start:end]


@mark.parametrize("path", ["Dockerfile", "compose.yml", "compose.hmr.yml"])
def test_no_command_running_the_app_overrides_the_lifespan(path: str) -> None:
    lines = [line for line in (ROOT / path).read_text().splitlines() if "app.main:app" in line]
    assert lines, f"no uvicorn command in {path}"
    for line in lines:
        words = shlex.split(line.replace('","', " ").replace('["', " ").replace('"]', " "))
        assert "--lifespan" not in words, line


def test_a_build_that_names_no_target_makes_the_release_image() -> None:
    """Platforms and CI build without a target, which builds the last stage.
    A stage added below the release one would replace it, and still build."""
    stages = [
        line for line in (ROOT / "Dockerfile").read_text().splitlines() if line.startswith("FROM ")
    ]
    assert stages[-1].endswith(" AS release"), (
        f"the last stage is not the release image: {stages[-1]}"
    )
