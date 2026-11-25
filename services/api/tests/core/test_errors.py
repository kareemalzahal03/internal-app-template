"""The error bodies match what the app declares for their status.

Nothing checks this on its own. The app declares a shape for each error
status, but the bodies are built by handlers that never see those
declarations. A mismatch would reach the browser as `undefined`, not as a
failure here.

Every error body comes from one of four handlers, so this file is a few
checks per handler rather than one per route. Each reaches its handler
through a route the template owns, or with an error only the database can
raise, so the checks survive the example domain being replaced. Each also
holds the body's `status` to the HTTP status it was sent with.
"""

from logging import ERROR

from pymongo.errors import DuplicateKeyError
from pytest import LogCaptureFixture, mark, raises
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request

from app.core.errors import (
    ErrorModel,
    FieldErrorModel,
    handle_duplicate_key,
    handle_http_exception,
)
from app.core.logging import request_boundary
from app.core.security import security_headers_middleware
from app.main import app
from tests.helpers import cause_a_server_error, create_user, declared_model, read_error
from tests.parties import Browser, FakeProvider

pytestmark = mark.asyncio(loop_scope="session")

# For a handler called directly. The handlers read nothing from it.
REQUEST = Request({"type": "http", "method": "GET", "path": "/", "headers": []})


### What every route declares


async def test_every_route_declares_the_shapes_that_hold_everywhere() -> None:
    """Any request can fail validation, and anything unnamed is the base. A
    409 is not among them: only a route that can collide with a unique index
    can produce one, so only its router declares it."""
    assert declared_model("/api/auth/me", "get", "422") == "FieldErrorModel"
    assert declared_model("/api/auth/me", "get", "default") == "ErrorModel"
    assert "409" not in app.openapi()["paths"]["/api/auth/me"]["get"]["responses"]


### What each handler sends


async def test_a_validation_failure_names_its_fields(anon_browser: Browser) -> None:
    """422 carries fields, so a form can mark the inputs that failed."""
    response = await anon_browser.post("/api/auth/backchannel-logout")
    assert response.status_code == 422

    body = read_error(FieldErrorModel, response)
    assert "logout_token" in body.fields
    # detail stays a complete sentence, so a client that ignores fields
    # still has something to render.
    assert "logout_token" in body.detail


async def test_a_duplicate_key_names_the_field_that_collided(empty_db: object) -> None:
    """A 409 in the same shape as a 422: a form marking its inputs should not
    care which of the two happened. The error is the driver's own, from a
    real collision; no template route can cause one."""
    await create_user("taken")
    with raises(DuplicateKeyError) as collision:
        await create_user("taken")
    response = await handle_duplicate_key(REQUEST, collision.value)
    assert response.status_code == 409

    body = read_error(FieldErrorModel, response)
    assert body.fields == {"sub": "already exists"}
    # The colliding value stays in the sentence, not in fields.
    assert "'taken'" in body.detail


@mark.parametrize("method", ["GET", "POST", "DELETE"])
async def test_an_unknown_api_path_is_a_404_in_the_base_shape(
    anon_browser: Browser, method: str
) -> None:
    """Whatever the method: a 405 would say the path exists."""
    response = await anon_browser.request(method, "/api/does-not-exist")
    assert response.status_code == 404

    body = read_error(ErrorModel, response)
    assert body.detail == "Not Found"


async def test_a_method_not_allowed_names_the_methods_that_are(anon_browser: Browser) -> None:
    """RFC 9110 §15.5.6: a 405 MUST carry Allow. The framework sets it on the
    exception it raises, and the handler that shapes the body keeps it."""
    response = await anon_browser.delete("/api/health")
    assert response.status_code == 405

    read_error(ErrorModel, response)
    assert response.headers["allow"] == "GET"


async def test_a_dict_detail_becomes_a_sentence() -> None:
    """`detail` is typed loosely enough to hold anything. Whatever a raiser
    put there has to reach the body's `detail` as a string, and nothing guesses which
    key carries the meaning — so every one survives, rather than the dict
    arriving as a Python repr. No route raises one, so the handler is called
    directly."""
    detail = {"code": "X", "reason": "y", "extra": "z"}
    # Typed as a string, enforced by nothing; the mismatch is the point.
    exc = StarletteHTTPException(400, detail)  # pyrefly: ignore[bad-argument-type]
    response = await handle_http_exception(REQUEST, exc)

    body = read_error(ErrorModel, response)
    assert body.detail == "code: X; reason: y; extra: z"


async def test_an_unexpected_error_is_a_500_that_keeps_the_bug_to_itself(
    provider: FakeProvider, caplog: LogCaptureFixture
) -> None:
    """The catch-all, for whatever no other handler claims. The bug is
    logged, never sent."""
    with caplog.at_level(ERROR, logger="app.core.logging"):
        response = await cause_a_server_error(provider)
    assert response.status_code == 500

    body = read_error(ErrorModel, response)
    assert "connection refused" not in body.detail
    assert "connection refused" in caplog.text
    # Answered below the middleware that adds headers, so it has them too.
    assert "x-request-id" in response.headers


async def test_only_middleware_that_cannot_fail_sits_above_the_request_boundary() -> None:
    """A layer above the boundary that raised would get Starlette's last
    resort: a 500 without the app's headers, and no request line."""
    above = app.user_middleware[: app.user_middleware.index(request_boundary)]
    assert above == [security_headers_middleware]
