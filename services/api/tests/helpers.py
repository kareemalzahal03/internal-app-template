"""What tests call directly: the environment the suite runs the app with,
records written straight to the database, and ways of reading what the app
sends back.
"""

from datetime import UTC, datetime
from http.cookies import SimpleCookie
from pathlib import Path

from httpx2 import URL, Response
from starlette.responses import Response as StarletteResponse

from app.core.auth import Session, User, UserClaims, start_session
from app.core.errors import ErrorModel
from app.main import app
from tests.parties import APP_URL, FakeProvider

# The repository, for tests that read the files that run the app.
ROOT = Path(__file__).parents[3]


### Records, made directly

# A well-formed id that names nothing, so a 404 is not a 422 in disguise.
MISSING_ID = "6a8b255b6cb1e2a7dbf4abea"


async def create_user(sub: str, *, email: str | None = None, name: str | None = None) -> User:
    """A user record as sign-in would leave it."""
    now = datetime.now(UTC)
    return await User(
        sub=sub,
        info=UserClaims(email=email or f"{sub}@example.com", name=name),
        created_at=now,
        updated_at=now,
    ).insert()


async def create_session(user: User, *, sid: str | None = None) -> Session:
    """A session for `user`, made the way sign-in makes one, and signed in
    on no browser."""
    # Stands in for the provider's signed ID token. Never parsed: the app
    # only ever hands it back to the provider.
    return await start_session("test-id-token", user.sub, sid)


async def exists(session: Session) -> bool:
    """Whether `session` is still stored, so its cookie still works."""
    return await Session.find_one(Session.cookie == session.cookie) is not None


### Reading responses


def cookies_set_by(response: Response) -> SimpleCookie:
    """Every cookie a navigation was told to set, by name, with the
    attributes it was set with: from each redirect on the way, then the
    page. A cookie set twice keeps the later, as the browser does."""
    cookies = SimpleCookie()
    for hop in [*response.history, response]:
        for header in hop.headers.get_list("set-cookie"):
            cookies.load(header)
    return cookies


def assert_lands_on(response: Response, to: str) -> None:
    """The navigation was redirected, and ended on `to`, a page that loaded.
    A path in `to` is at the app's origin."""
    assert response.history, "the navigation was never redirected"
    assert str(response.url) == str(URL(APP_URL).join(to))
    assert response.status_code == 200, response.text


def read_error[M: ErrorModel](model: type[M], response: Response | StarletteResponse) -> M:
    """The body as `model`, once it is known to be JSON for its own status.
    Takes a response a browser received, or one a handler returned."""
    assert response.headers["content-type"] == "application/json"
    raw = response.content if isinstance(response, Response) else bytes(response.body)
    body = model.model_validate_json(raw)
    assert body.status == response.status_code
    return body


def declared_model(path: str, method: str, status: str) -> str:
    """The schema the app's OpenAPI declares for a status."""
    responses = app.openapi()["paths"][path][method]["responses"]
    ref: str = responses[status]["content"]["application/json"]["schema"]["$ref"]
    return ref.rsplit("/", 1)[-1]


async def cause_a_server_error(provider: FakeProvider) -> Response:
    """The 500 the app sends for an error no handler claims. Caused for real:
    the provider is down while a logout token is checked."""
    provider.down = True
    return await provider.send_logout_token("x")
