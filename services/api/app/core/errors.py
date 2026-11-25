"""Errors: how every raised error becomes a response, and the error shapes
every route declares."""

from collections.abc import Callable, Coroutine, Mapping
from typing import Any

from fastapi import Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from pymongo.errors import DuplicateKeyError
from starlette.exceptions import HTTPException as StarletteHTTPException

### ERROR BODIES


class ErrorModel(BaseModel):
    """The body of every non-2XX response, in RFC 9457's member names (§3.1),
    with `status` and `detail` required. Sent as plain application/json."""

    # The HTTP status code, repeated for convenience.
    status: int
    # A human-readable explanation of this occurrence.
    detail: str


class FieldErrorModel(ErrorModel):
    """A failure attributable to named inputs, so a form can mark them."""

    # Each input, and what is wrong with it (an extension member, §3.2).
    fields: dict[str, str]


class ErrorResponse(JSONResponse):
    """An error response: the body is `error`, and the status its `status`."""

    def __init__(self, error: ErrorModel, headers: Mapping[str, str] | None = None) -> None:
        super().__init__(error.model_dump(), error.status, headers)


### HANDLERS


async def handle_validation_error(_: Request, exc: RequestValidationError) -> ErrorResponse:
    """A request that failed validation: its errors as one sentence, and per field."""
    # loc[0] is the request part ("body", "query"); the rest names the field.
    fields: dict[str, str] = {
        ".".join(str(part) for part in err["loc"][1:]) or "request": str(err["msg"])
        for err in exc.errors()
    }
    detail = "; ".join(f"{field}: {msg}" for field, msg in fields.items())
    return ErrorResponse(FieldErrorModel(status=422, detail=detail, fields=fields))


def detail_str(detail: Any) -> str:
    """Whatever a raiser put in `detail`, as one renderable string."""
    # HTTPException.detail is typed loosely and not enforced.
    # A non-string here would make Pydantic raise inside the handler.
    if isinstance(detail, str):
        # Left alone, so a str subclass such as an enum member keeps its value.
        return detail
    if isinstance(detail, dict):
        # Keep every key rather than guess which one carries the detail.
        return "; ".join(f"{key}: {value}" for key, value in detail.items())
    return str(detail)


# Registered on Starlette's class, not FastAPI's subclass: an unmatched
# route raises the base one, so the base registration answers both.
async def handle_http_exception(_: Request, exc: StarletteHTTPException) -> ErrorResponse:
    """Catches HTTPException, whether raised by a route or by the framework."""
    # Its headers too: a 405 MUST carry Allow (RFC 9110 §15.5.6), and a 401
    # or 429 may carry WWW-Authenticate or Retry-After.
    return ErrorResponse(
        ErrorModel(status=exc.status_code, detail=detail_str(exc.detail)), exc.headers
    )


# A unique-index violation is the client's problem, not a server fault, so it
# gets a 409 rather than a 500.
async def handle_duplicate_key(_: Request, exc: DuplicateKeyError) -> ErrorResponse:
    """Turn a driver-level duplicate key into a field error."""
    # The driver reports which index collided and on what value: {"email": "ops@example.com"}
    key_value: dict[str, Any] = (exc.details or {}).get("keyValue") or {}
    collided = ", ".join(f"{field}={value!r}" for field, value in key_value.items())
    return ErrorResponse(
        FieldErrorModel(
            status=409,
            detail=f"a record with {collided} already exists" if collided else "duplicate key",
            fields={field: "already exists" for field in key_value},
        ),
    )


def unexpected_error_response() -> ErrorResponse:
    """A generic 500 response for any unhandled exception."""
    return ErrorResponse(ErrorModel(status=500, detail="Internal server error"))


# Starlette's last resort answers with this. The response says nothing of
# the exception.
# It must never raise: nothing would answer the request. So the response is
# built from constants, taking nothing from the request or the exception.
async def handle_unexpected_error(_: Request, __: Exception) -> ErrorResponse:
    """Anything no other handler claimed, which is a bug."""
    return unexpected_error_response()


exception_handlers: dict[
    int | type[Exception], Callable[[Request, Any], Coroutine[Any, Any, Response]]
] = {
    # Answered below the middleware, as each route's own errors.
    RequestValidationError: handle_validation_error,
    StarletteHTTPException: handle_http_exception,
    DuplicateKeyError: handle_duplicate_key,
    # Starlette treats this key apart: the last resort, above all middleware.
    Exception: handle_unexpected_error,
}


### DECLARED ON EVERY ROUTE

# Only the error shapes true of every route: any request can fail
# validation, and every other failure carries at least a status and detail.
responses: dict[int | str, dict[str, Any]] = {
    422: {"model": FieldErrorModel},
    "default": {"model": ErrorModel},
}
