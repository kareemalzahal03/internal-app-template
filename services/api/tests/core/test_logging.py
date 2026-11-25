"""Each request writes one JSON line: a sentence from a fixed set saying what
happened, its attributes under OpenTelemetry's names, and the same request ID
the response carries."""

import json
import sys
from asyncio import CancelledError, Event, create_subprocess_exec, create_task
from asyncio.subprocess import PIPE
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from io import StringIO
from logging import INFO, StreamHandler, getLogger
from typing import Any

from pytest import LogCaptureFixture, fixture, mark, raises
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import ErrorModel
from app.core.logging import JsonFormatter, RequestBoundary
from tests.helpers import ROOT, cause_a_server_error
from tests.parties import Browser, FakeProvider

pytestmark = mark.asyncio(loop_scope="session")

LogLines = Callable[[], list[dict[str, Any]]]

METHOD = "http.request.method"
STATUS = "http.response.status_code"


@fixture
def log_lines(caplog: LogCaptureFixture) -> Iterator[LogLines]:
    """Reads the request lines written so far, the ones with an HTTP method,
    as the app's handler writes them."""
    output = StringIO()
    handler = StreamHandler(output)
    handler.setFormatter(JsonFormatter())
    logger = getLogger("app")
    logger.addHandler(handler)

    def read() -> list[dict[str, Any]]:
        lines = (json.loads(line) for line in output.getvalue().splitlines())
        return [line for line in lines if METHOD in line.get("attributes", {})]

    with caplog.at_level(INFO, logger="app"):
        yield read
    logger.removeHandler(handler)


async def test_a_request_writes_one_line_with_its_fields(
    anon_browser: Browser, log_lines: LogLines
) -> None:
    """Method, path, query and status are attributes, so a log search can
    filter on them, and the ID is the one the response carries. It is always
    new: any client can send one, so an incoming ID is not taken."""
    response = await anon_browser.get("/api/health?probe=1", headers={"X-Request-ID": "chosen"})

    [line] = log_lines()
    assert response.headers["x-request-id"] != "chosen"
    assert line["level"] == "INFO"
    assert line["message"] == "The app responded."
    assert line["time"].endswith("+00:00")
    assert line["attributes"][METHOD] == "GET"
    assert line["attributes"]["url.path"] == "/api/health"
    assert line["attributes"]["url.query"] == "probe=1"
    assert line["attributes"][STATUS] == 200
    assert line["request_id"] == response.headers["x-request-id"]
    assert isinstance(line["elapsed_ms"], float)


async def test_a_query_credential_is_redacted_and_its_key_kept(
    anon_browser: Browser, log_lines: LogLines
) -> None:
    """A sign-in's code and state, and a front-channel logout's sid, which
    still ends sessions, never reach the logs. The rest of the query does,
    as sent."""
    await anon_browser.get("/api/health?code=c1&state=s%201&sid=x&page=2")

    [line] = log_lines()
    assert line["attributes"]["url.query"] == "code=REDACTED&state=REDACTED&sid=REDACTED&page=2"


async def test_a_request_that_raised_is_logged_with_its_500_and_its_bug(
    provider: FakeProvider, log_lines: LogLines
) -> None:
    """The 500 is answered below the request line's middleware, so a bug
    still leaves the request's line. The bug's own line names its type as a
    field, so lines can be counted by bug, under the same request ID."""
    response = await cause_a_server_error(provider)

    [line] = log_lines()
    assert line["level"] == "ERROR"
    assert line["message"] == "The app raised before responding. Error response sent."
    attributes = line["attributes"]
    assert attributes[STATUS] == 500
    assert attributes["exception.type"] == "httpx2.ConnectError"
    assert "connection refused" in attributes["exception.message"]
    # Raised inside the HTTP library; the stacktrace shows the app line that called it.
    assert "in verified_logout_claims" in attributes["exception.stacktrace"]
    assert line["request_id"] == response.headers["x-request-id"]


async def through_the_boundary(inner: ASGIApp, disconnect: bool = False) -> list[Message]:
    """What the boundary sends for one GET, with `inner` as everything below it,
    and with the client disconnected if `disconnect`. Called directly, since
    the test network routes every client to the app."""
    scope: Scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "query_string": b"",
        "headers": [],
        "http_version": "1.1",
    }
    sent: list[Message] = []

    async def receive() -> Message:
        if disconnect:
            return {"type": "http.disconnect"}
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        sent.append(message)

    await RequestBoundary(inner)(scope, receive, send)
    return sent


def acting_app(status: int | None, finishes: bool, reads: bool, raises: bool) -> ASGIApp:
    """An app that starts a response with `status` (or sends nothing if None)
    and finishes its body if `finishes`, then reads the next message if
    `reads`, then raises if `raises`."""

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        if status is not None:
            await send({"type": "http.response.start", "status": status, "headers": []})
            await send({"type": "http.response.body", "body": b"x", "more_body": not finishes})
        if reads:
            await receive()
        if raises:
            raise RuntimeError("the bug")

    return app


@mark.parametrize(
    ("status", "finishes", "client_leaves", "raises", "level", "message"),
    [
        (200, True, False, False, "INFO", "The app responded."),
        (503, True, False, False, "ERROR", "The app responded."),
        (200, True, False, True, "ERROR", "The app raised after responding."),
        (
            200, False, True, False, "INFO",
            "The app returned before finishing the response. The client disconnected mid-way.",
        ),
        (
            500, False, True, False, "ERROR",
            "The app returned before finishing the response. The client disconnected mid-way.",
        ),
        (200, False, False, False, "ERROR", "The app returned before finishing the response."),
        (
            200, False, True, True, "WARNING",
            "The app raised during the response. The client disconnected, which may be the reason.",
        ),
        (200, False, False, True, "ERROR", "The app raised during the response."),
        (
            None, False, True, False, "INFO",
            "The app returned without responding. Error response not sent: client disconnected.",
        ),
        (None, False, False, False, "ERROR", "The app returned without responding. Error response sent."),
        (
            None, False, True, True, "WARNING",
            "The app raised before responding. Error response not sent: client disconnected.",
        ),
        (None, False, False, True, "ERROR", "The app raised before responding. Error response sent."),
    ],
)  # fmt: skip
async def test_each_case_has_its_level_and_message(
    log_lines: LogLines,
    status: int | None,
    finishes: bool,
    client_leaves: bool,
    raises: bool,
    level: str,
    message: str,
) -> None:
    """Every row of the table of cases: how far the response got, whether the
    app raised, and whether it was told the client left.

    Once a response has started, no 500 can replace it: the line has the
    status that was sent and the error. Before that, the browser gets the
    app's 500, unless the client has gone and nobody is left to answer. An
    exception as the client leaves may be the disconnect or a bug, and the
    line cannot tell, so it is a warning. Cancels are tested apart, since
    only a task can be cancelled."""
    app = acting_app(status, finishes, reads=client_leaves, raises=raises)
    sent = await through_the_boundary(app, disconnect=client_leaves)

    [line] = log_lines()
    assert line["level"] == level
    assert line["message"] == message
    assert ("exception.type" in line["attributes"]) == raises

    error_response_sent = status is None and not client_leaves
    assert line["attributes"].get(STATUS) == (500 if error_response_sent else status)
    if status is None and client_leaves:
        assert sent == []
    else:
        start = sent[0]
        assert start["status"] == line["attributes"][STATUS]
        assert (b"x-request-id", line["request_id"].encode()) in start["headers"]
    if error_response_sent:
        assert ErrorModel.model_validate_json(sent[1]["body"]).detail == "Internal server error"


async def test_an_error_that_cannot_be_printed_still_gets_its_500_and_its_line(
    log_lines: LogLines,
) -> None:
    """An exception whose own str() raises is a bug inside a bug, and its
    line is the one most needed. The line is written with a stand-in for
    the text, as Python's tracebacks write one, and the 500 is sent."""

    class Unprintable(Exception):
        def __str__(self) -> str:
            raise RuntimeError("cannot be printed")

    async def raises_it(scope: Scope, receive: Receive, send: Send) -> None:
        raise Unprintable

    start, body = await through_the_boundary(raises_it)

    assert start["status"] == 500
    assert ErrorModel.model_validate_json(body["body"]).detail == "Internal server error"
    [line] = log_lines()
    assert line["message"] == "The app raised before responding. Error response sent."
    assert line["attributes"]["exception.type"].endswith("Unprintable")
    assert line["attributes"]["exception.message"] == "<exception str() failed>"
    assert "Unprintable: <exception str() failed>" in line["attributes"]["exception.stacktrace"]


async def raise_with_a_failing_send(send_error: BaseException) -> None:
    """Runs an app that raises before responding, behind a server whose every
    send raises `send_error`. The app is never told the client has gone."""

    async def raises(scope: Scope, receive: Receive, send: Send) -> None:
        raise RuntimeError("the bug")

    async def failing_send(message: Message) -> None:
        raise send_error

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    scope: Scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "query_string": b"",
        "headers": [],
    }
    await RequestBoundary(raises)(scope, receive, failing_send)


@mark.parametrize(
    ("send_error", "passed_on", "outcome", "logs_send_error"),
    [
        # ASGI 2.4 HTTP §Disconnected Client: how the boundary learns a client
        # left that the app was never told about.
        (OSError("connection reset"), False, "not sent: client disconnected.", False),
        # Anything else broke the error response itself: a bug of its own.
        (RuntimeError("Invalid HTTP header value."), False, "failed: unexpected failure.", True),
        # A server stopping, while the 500 waits on a stuck client.
        (CancelledError(), True, "cancelled.", False),
        (SystemExit(1), True, "aborted.", True),
    ],
)
async def test_a_500_that_fails_to_send_keeps_the_apps_case(
    log_lines: LogLines,
    caplog: LogCaptureFixture,
    send_error: BaseException,
    passed_on: bool,
    outcome: str,
    logs_send_error: bool,
) -> None:
    """The line keeps the app's own case and exception, and says what became
    of the 500. It has no status: the server never took one. A cancel or a
    stop is logged, then still reaches the server. What broke the 500, a bug
    of its own, gets a line of its own, so each line has one exception."""
    if passed_on:
        with raises(type(send_error)):
            await raise_with_a_failing_send(send_error)
    else:
        await raise_with_a_failing_send(send_error)

    [line] = log_lines()
    assert line["level"] == "ERROR"
    assert line["message"] == f"The app raised before responding. Error response {outcome}"
    attributes = line["attributes"]
    assert STATUS not in attributes
    assert attributes["exception.message"] == "the bug"
    failures = [r for r in caplog.records if r.getMessage() == "The error response failed."]
    if logs_send_error:
        [failure] = failures
        assert failure.levelname == "ERROR"
        assert isinstance(failure.exc_info, tuple) and failure.exc_info[1] is send_error
    else:
        assert failures == []


async def test_a_cancelled_request_is_logged_and_still_cancelled(log_lines: LogLines) -> None:
    """A server stopping cancels the requests still running once its graceful
    wait is over. Each still gets its line, as a warning naming the await it
    was stuck on, and the cancel still reaches the server. Nothing more is sent."""
    sent: list[Message] = []
    started = Event()

    async def hangs_after_starting(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        started.set()
        await Event().wait()

    async def send(message: Message) -> None:
        sent.append(message)

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    scope: Scope = {"type": "http", "method": "GET", "path": "/", "headers": []}
    task = create_task(RequestBoundary(hangs_after_starting)(scope, receive, send))
    await started.wait()
    task.cancel()
    with raises(CancelledError):
        await task

    assert [message["type"] for message in sent] == ["http.response.start"]
    [line] = log_lines()
    assert line["level"] == "WARNING"
    assert line["message"] == "The app was cancelled."
    assert line["attributes"][STATUS] == 200
    assert line["attributes"]["exception.type"] == "asyncio.exceptions.CancelledError"
    assert "await Event().wait()" in line["attributes"]["exception.stacktrace"]


async def test_an_app_that_exits_is_logged_and_still_exits(log_lines: LogLines) -> None:
    """A SystemExit is a stop, not an error to answer: no 500 is sent. The
    request still gets its line, naming what stopped it, and the exit still
    reaches the server."""

    async def exits(scope: Scope, receive: Receive, send: Send) -> None:
        raise SystemExit(1)

    with raises(SystemExit):
        await through_the_boundary(exits)

    [line] = log_lines()
    assert line["level"] == "ERROR"
    assert line["message"] == "The app was aborted."
    # No status: nothing was sent, so no 500 either.
    assert STATUS not in line["attributes"]
    assert line["attributes"]["exception.type"] == "SystemExit"


async def test_code_adds_attributes_but_never_replaces_the_lines_fields() -> None:
    """Any code can pass `extra={"attributes": {...}}` without the formatter
    knowing the names. A value JSON cannot encode becomes its text, an
    attribute never replaces the line's own fields, and any other `extra` key
    is not written."""
    when = datetime(2026, 1, 2, tzinfo=UTC)
    record = getLogger("app.test").makeRecord(
        "app.test", INFO, __file__, 1, "Order shipped.", (), None,
        extra={"attributes": {"order.id": "o1", "when": when, "level": "fake"}, "order_id": "o2"},
    )  # fmt: skip

    line = json.loads(JsonFormatter().format(record))

    assert line["level"] == "INFO"
    assert line["attributes"] == {"order.id": "o1", "when": str(when), "level": "fake"}
    assert "order_id" not in line


async def test_a_requested_stack_is_written_as_the_code_stacktrace() -> None:
    """stack_info=True asks for the stack at the logging call, as the
    default formatter writes it."""
    output = StringIO()
    handler = StreamHandler(output)
    handler.setFormatter(JsonFormatter())
    logger = getLogger("app.test.stack")
    logger.addHandler(handler)
    try:
        logger.warning("Odd state.", stack_info=True)
    finally:
        logger.removeHandler(handler)

    stack = json.loads(output.getvalue())["attributes"]["code.stacktrace"]
    assert stack.startswith("Stack (most recent call last):")
    assert "test_a_requested_stack_is_written_as_the_code_stacktrace" in stack


# Logs one line from each kind of logger, after uvicorn has applied the
# config file as it does at startup, before it imports the app.
UNDER_UVICORN = """
from logging import getLogger
from uvicorn import Config

Config("app.main:app", log_config="app/core/logging.json")
getLogger("uvicorn.error").info("Started server process.")
getLogger("app.domain").info("Order shipped.")
getLogger("asyncio").warning("A library's warning.")
getLogger("asyncio").info("A library's chatter.")
"""


async def test_under_uvicorn_every_line_is_json() -> None:
    """uvicorn's own lines, the app's from INFO, and any library's from
    WARNING, all as the app's JSON. uvicorn's extra fields are left out."""
    process = await create_subprocess_exec(
        sys.executable, "-c", UNDER_UVICORN, cwd=ROOT / "services" / "api", stderr=PIPE
    )
    _, stderr = await process.communicate()

    assert process.returncode == 0, stderr.decode()
    lines = [json.loads(line) for line in stderr.decode().splitlines()]
    assert [(line["logger"], line["message"]) for line in lines] == [
        ("uvicorn.error", "Started server process."),
        ("app.domain", "Order shipped."),
        ("asyncio", "A library's warning."),
    ]
    assert "attributes" not in lines[0]
