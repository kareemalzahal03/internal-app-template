"""Structured JSON logging, and the layer that gives each request its ID and
writes its one line.

Every log line written while a request is in flight carries that request's
ID (new for every request) and how long the request has been running. So one
request's lines can be pulled out of interleaved logs. Each request then
writes one line of its own, with its exception if it raised one.
"""

from asyncio import CancelledError
from contextvars import ContextVar
from datetime import UTC, datetime
from json import JSONEncoder
from logging import ERROR, INFO, WARNING, Formatter, LogRecord, getLogger
from time import perf_counter
from typing import Literal
from urllib.parse import unquote_plus
from uuid import uuid4

from starlette.datastructures import MutableHeaders
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import unexpected_error_response

### JSON LINES


# The running request's ID and start time. Every line logged while it runs
# reads them, so it is stamped without being handed them.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
request_start_var: ContextVar[float | None] = ContextVar("request_start", default=None)


# A value JSON cannot encode (a datetime, an ObjectId) becomes its text,
# rather than losing the line.
json_encoder = JSONEncoder(default=str)


class JsonFormatter(Formatter):
    """Each record as one line of JSON: the same fields on every line, then
    the record's attributes, named as in OpenTelemetry's conventions."""

    def format(self, record: LogRecord) -> str:
        line: dict[str, object] = {
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
        }

        # Only while a request runs: its ID, and how long it has been running.
        if (request_id := request_id_var.get()) is not None:
            line["request_id"] = request_id
        if (start := request_start_var.get()) is not None:
            line["elapsed_ms"] = round((perf_counter() - start) * 1000, 1)

        # The caller's, passed as extra={"attributes": {...}}. Kept apart from
        # the fields above, so none can replace them. Any other key in
        # `extra` is not written.
        attributes = dict(getattr(record, "attributes", {}))

        # The stack at the logging call, when the caller asked with stack_info=True.
        if record.stack_info:
            attributes["code.stacktrace"] = self.formatStack(record.stack_info)

        if record.exc_info and (exc := record.exc_info[1]) is not None:
            # Fully qualified, as httpx2.ConnectError; a built-in's needs no module, as OSError.
            cls = type(exc)
            module = "" if cls.__module__ == "builtins" else f"{cls.__module__}."
            attributes["exception.type"] = module + cls.__qualname__
            # str() can itself raise; the stand-in is the one Python's tracebacks write.
            try:
                attributes["exception.message"] = str(exc)
            except Exception:  # noqa: BLE001
                attributes["exception.message"] = "<exception str() failed>"
            attributes["exception.stacktrace"] = self.formatException(record.exc_info)

        if attributes:
            line["attributes"] = attributes
        return json_encoder.encode(line)


### THE REQUEST BOUNDARY


# Query keys whose values are never written: a sign-in's code and state, and
# a front-channel logout's sid, which ends the sessions it names to anyone
# who sends it. Add any key of the app's own that carries a credential.
SENSITIVE_QUERY_KEYS = {"code", "state", "sid"}


# Proof the request's line was written. Returned by every path that ends a
# request, so a path that forgets to log fails the type check.
Logged = Literal[True]


class BoundaryRequest:
    """One request through the boundary: gives it an ID and a start time, runs
    the app on it, answers with a 500 if the app sent nothing, and writes its
    one line. Every response sent through it carries the request's ID."""

    def __init__(self, scope: Scope, receive: Receive, send: Send) -> None:
        self.scope = scope
        self.receive = receive
        self.send = send
        # Every line logged anywhere in this request reads these.
        self.request_id = uuid4().hex
        request_id_var.set(self.request_id)
        request_start_var.set(perf_counter())
        # The status of the response, after the first message was sent successfully.
        self.status: int | None = None
        # Whether the response is complete, after the last message was sent successfully.
        self.complete: bool = False
        # Whether the client disconnected, after the app was told it had.
        self.client_gone: bool = False

    async def _send(self, message: Message) -> None:
        """Send `message` on. The message that starts the response gets the
        request ID in its headers, and its status is recorded once sent. The
        message that ends the body marks the response complete once sent."""
        if message["type"] == "http.response.start":
            MutableHeaders(scope=message)["X-Request-ID"] = self.request_id
            await self.send(message)
            self.status = message["status"]
        elif message["type"] == "http.response.body" and not message.get("more_body", False):
            await self.send(message)
            self.complete = True
        else:
            await self.send(message)

    async def _receive(self) -> Message:
        """The next message from the client, with a disconnect recorded before
        it is handed on."""
        message = await self.receive()
        if message["type"] == "http.disconnect":
            self.client_gone = True
        return message

    async def run(self, asgi_app: ASGIApp) -> BaseException | None:
        """Run `asgi_app` on this request, through the recording send and receive.
        Returns None if it finished, or what it raised rather than raising it."""
        try:
            await asgi_app(self.scope, self._receive, self._send)
            return None
        # Everything, so every request gets its line. Whoever gets back one that is
        # not an Exception (a cancel, a SystemExit) must raise it once logged.
        except BaseException as exc:  # noqa: BLE001
            return exc

    def request_attributes(self) -> dict[str, object]:
        """The request's attributes, under OpenTelemetry's names. One with no
        value is left out."""
        request = Request(self.scope)
        attributes: dict[str, object] = {
            "http.request.method": request.method,
            "url.path": request.url.path,
        }

        if query := request.url.query:
            # Each sensitive key's value is replaced and the key kept, as
            # OpenTelemetry redacts url.query. The rest is written as sent.
            pairs = query.split("&")
            for i, pair in enumerate(pairs):
                key = pair.partition("=")[0]
                if unquote_plus(key) in SENSITIVE_QUERY_KEYS:
                    pairs[i] = f"{key}=REDACTED"
            attributes["url.query"] = "&".join(pairs)

        # Absent if no response was sent.
        if self.status is not None:
            attributes["http.response.status_code"] = self.status
        if request.client is not None:
            attributes["client.address"] = request.client.host
        if (version := self.scope.get("http_version")) is not None:
            attributes["network.protocol.version"] = version
        return attributes

    def log(self, lvl: int, msg: str, exc: BaseException | None = None) -> Logged:
        """Write the request's line: `msg` at `lvl`, with the request's
        attributes and the app's exception."""
        getLogger(__name__).log(
            lvl, msg, exc_info=exc, extra={"attributes": self.request_attributes()}
        )
        return True

    def log_error_response_failure(self, exc: BaseException) -> None:
        """Log what broke the 500 on a line of its own: it is a bug apart from
        the app's, and a line describes one exception."""
        getLogger(__name__).error("The error response failed.", exc_info=exc)

    async def handle(self, app: ASGIApp) -> Logged:
        """Run `app` on the request, answer with a 500 if it sent nothing, and
        log the line saying how far its response got and what went wrong."""

        app_exc: BaseException | None = await self.run(app)

        if app_exc is not None and not isinstance(app_exc, Exception):
            # Base Exception raised. Log and re-raise.
            if isinstance(app_exc, CancelledError):
                self.log(WARNING, "The app was cancelled.", app_exc)
            else:
                self.log(ERROR, "The app was aborted.", app_exc)
            raise app_exc

        if self.complete and self.status is not None:
            # The whole response was sent. (complete => status is not None)
            if app_exc is not None:
                # Raised after the last message was sent, e.g. a background task.
                return self.log(ERROR, "The app raised after responding.", app_exc)
            lvl = ERROR if self.status >= 500 else INFO
            return self.log(lvl, "The app responded.")

        if self.status is not None:
            # The response started, but its body was cut short.
            if app_exc is None:
                msg = "The app returned before finishing the response."
                if self.client_gone:
                    # The app stopped because it was told the client left: normal.
                    lvl = ERROR if self.status >= 500 else INFO
                    return self.log(lvl, msg + " The client disconnected mid-way.")
                # A bug, and the sentence says all that is known.
                return self.log(ERROR, msg)
            msg = "The app raised during the response."
            if self.client_gone:
                # Often the disconnect itself, sometimes a bug; the line cannot tell.
                return self.log(
                    WARNING, msg + " The client disconnected, which may be the reason.", app_exc
                )
            return self.log(ERROR, msg, app_exc)

        # No response sent by the app.
        if app_exc is None:
            # Normal if it stopped because it was told the client left; otherwise a bug.
            msg = "The app returned without responding."
            lvl = INFO if self.client_gone else ERROR
        else:
            # With the client gone, as above: the line cannot tell which.
            msg = "The app raised before responding."
            lvl = WARNING if self.client_gone else ERROR

        if self.client_gone:
            # The app was told the client disconnected. Send nothing.
            return self.log(lvl, msg + " Error response not sent: client disconnected.", app_exc)

        # Send an error response. Log whether it was sent or an error occurred.
        err_exc: BaseException | None = await self.run(unexpected_error_response())

        if err_exc is None:
            # The usual case: the error response was sent.
            return self.log(lvl, msg + " Error response sent.", app_exc)

        if not isinstance(err_exc, Exception):
            # Base Exception raised. Log and re-raise.
            if isinstance(err_exc, CancelledError):
                self.log(lvl, msg + " Error response cancelled.", app_exc)
            else:
                self.log_error_response_failure(err_exc)
                self.log(lvl, msg + " Error response aborted.", app_exc)
            raise err_exc

        # Normal Exception raised.
        if isinstance(err_exc, OSError):
            # The client disconnected without the app being told. Found out on send:
            # ASGI 2.4 HTTP §Disconnected Client, a send on a closed connection raises OSError.
            return self.log(lvl, msg + " Error response not sent: client disconnected.", app_exc)

        # Something unexpected broke the error response itself.
        self.log_error_response_failure(err_exc)
        return self.log(lvl, msg + " Error response failed: unexpected failure.", app_exc)


class RequestBoundary:
    """The middleware the app's requests pass through: each HTTP request is
    handled as one request through the boundary; anything else passes
    straight through."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # A new object per request: the middleware is shared by every request in flight.
        await BoundaryRequest(scope, receive, send).handle(self.app)


request_boundary = Middleware(RequestBoundary)
