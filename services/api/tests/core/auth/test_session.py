"""The session: what a cookie has to name, how long it lasts, and what an
anonymous caller is allowed to learn.

Most tests here hold the `browser` fixture's session and move its deadlines
directly, rather than waiting on a clock. The cookie itself is read from a
real sign-in, since that is where the browser gets it.
"""

import re
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime

from pytest import MonkeyPatch, mark

from app.core import auth as auth_module
from app.core.auth import CSRF_HEADER, Session, User
from app.main import app
from tests.helpers import MISSING_ID, cookies_set_by
from tests.parties import COOKIE, Browser, FakeProvider

pytestmark = mark.asyncio(loop_scope="session")


### The session dependency


async def test_an_unknown_token_is_401(anon_browser: Browser) -> None:
    """A cookie is not a session — the token has to name one."""
    anon_browser.session_cookie = "not-a-real-session-token"
    assert (await anon_browser.get("/api/auth/me")).status_code == 401


async def test_me_returns_the_signed_in_user(browser: Browser, user: User) -> None:
    """The frontend's only way to ask whether it is signed in."""
    response = await browser.get("/api/auth/me")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["email"] == user.info.email
    # The response is built by hand, so storage fields never leak by accident.
    assert set(body) == {"id", "email", "name"}


### The two clocks


async def test_an_expired_session_is_401(browser: Browser, session: Session) -> None:
    """Expiry is enforced by the dependency, not by the TTL index: Mongo's TTL
    monitor only sweeps about once a minute, so an expired document is still
    there to be found and must still be refused."""
    await session.set({Session.expires_at: datetime.now(UTC) - timedelta(seconds=1)})

    assert (await browser.get("/api/auth/me")).status_code == 401


async def test_a_session_past_its_absolute_deadline_is_401(
    browser: Browser, session: Session
) -> None:
    """Staying busy must not keep a session alive past the provider's ceiling:
    the idle deadline is fine here and the absolute one is not."""
    await session.set(
        {
            Session.expires_at: datetime.now(UTC) + timedelta(minutes=30),
            Session.absolute_expires_at: datetime.now(UTC) - timedelta(seconds=1),
        }
    )

    assert (await browser.get("/api/auth/me")).status_code == 401


async def test_activity_pushes_the_idle_deadline_forward(
    browser: Browser, session: Session
) -> None:
    """A request counts as activity, which is what makes the idle window idle
    rather than a second fixed lifetime."""
    await session.set({Session.expires_at: datetime.now(UTC) + timedelta(seconds=30)})
    assert await browser.is_signed_in()

    await session.sync()
    assert session.expires_at > datetime.now(UTC) + timedelta(minutes=20)


async def test_the_idle_deadline_never_passes_the_absolute_one(
    browser: Browser, session: Session
) -> None:
    """Extending is clamped, so the two clocks cannot disagree. The ceiling is
    inside the idle window here, which is the only case where they can."""
    await session.set(
        {
            Session.expires_at: datetime.now(UTC) + timedelta(seconds=30),
            Session.absolute_expires_at: datetime.now(UTC) + timedelta(minutes=20),
        }
    )
    assert await browser.is_signed_in()

    await session.sync()
    # Compared to the stored value, not to a local one: Mongo keeps
    # milliseconds, so a datetime built here would differ in microseconds.
    assert session.expires_at == session.absolute_expires_at


### The cookie


async def test_the_session_cookie_has_the_attributes_rfc_10017_asks_for(
    anon_browser: Browser, provider: FakeProvider
) -> None:
    """RFC 10017 §6.1.3.2: Secure and HttpOnly (MUST), SameSite=Strict, Path=/,
    no Domain and the __Host-Http- prefix (SHOULD)."""
    cookie = cookies_set_by(await anon_browser.sign_in())[COOKIE]

    assert cookie.key.startswith("__Host-Http-")
    assert cookie["secure"]
    assert cookie["httponly"]
    assert cookie["path"] == "/"
    assert cookie["samesite"].lower() == "strict"
    assert not cookie["domain"]


@mark.parametrize("max_seconds", [3600, 86_400])
async def test_the_cookie_lasts_as_long_as_the_session(
    anon_browser: Browser, provider: FakeProvider, monkeypatch: MonkeyPatch, max_seconds: int
) -> None:
    """The cookie expires with the session's absolute deadline, not its idle one.

    Two regressions, both of which looked like a successful sign-in. The
    lifetime was once computed with `timedelta.seconds` — the seconds
    *component*, which drops whole days, so at exactly 86400, a case here, it emitted
    Max-Age=0 and told the browser to delete the cookie at once. Passing the
    deadline itself removes that arithmetic. The other was expiring with
    `expires_at`, the *idle* deadline, which slides server-side without
    re-issuing the cookie, so an active session lost its cookie at the first
    idle window while the server still believed it was signed in.
    """
    monkeypatch.setattr(auth_module, "SESSION_MAX", timedelta(seconds=max_seconds))
    cookie = cookies_set_by(await anon_browser.sign_in())[COOKIE]
    session = await Session.find_one(Session.cookie == cookie.value)
    assert session is not None

    expires = parsedate_to_datetime(cookie["expires"])
    assert expires == session.absolute_expires_at.replace(microsecond=0)
    assert session.absolute_expires_at - session.created_at == timedelta(seconds=max_seconds)


### The guard on the domain routers


def guarded_routes() -> list[tuple[str, str]]:
    """Every (method, path) in the API contract except the health probe.

    Read from the OpenAPI document rather than listed here, so a route a
    fork adds is checked without anyone remembering to add it, and so this
    file never names the example domain. The contract is the right list: the
    routes outside it are the sign-in navigations and the provider's
    callbacks, which are open by design."""
    found: list[tuple[str, str]] = []
    for path, operations in app.openapi()["paths"].items():
        if path == "/api/health":
            continue
        # Every path parameter filled with a well-formed id, so a 401 cannot
        # be a 422 in disguise.
        concrete = re.sub(r"\{[^}]+\}", MISSING_ID, path)
        found.extend((method.upper(), concrete) for method in operations)
    return found


@mark.parametrize(("method", "path"), guarded_routes())
async def test_every_route_requires_a_session_and_the_csrf_header(
    browser: Browser, method: str, path: str
) -> None:
    """The router-level dependency, not each route's own.

    Without the header, a valid cookie is not enough: a cross-site request
    carries the cookie too, when the other site shares this one's parent
    domain (RFC 10017 §6.1.3.3.1). The header is what such a request cannot
    add. Without the cookie, a 401 rather than a 404 or 422 proves the check
    runs before the path and body are resolved, so an anonymous caller
    learns nothing about what exists."""
    del browser.headers[CSRF_HEADER]
    no_header = await browser.request(method, path)
    assert no_header.status_code == 403, no_header.text
    assert CSRF_HEADER in no_header.json()["detail"]

    async with Browser() as anon:
        no_session = await anon.request(method, path)
    assert no_session.status_code == 401, no_session.text


async def test_a_navigation_carries_the_cookie_and_is_still_refused(browser: Browser) -> None:
    """What the header defends against, as it arrives: a link or a form on a
    sibling site sends the browser here with its cookie, but a navigation
    never carries a header the SPA adds."""
    response = await browser.navigate("/api/auth/me")

    assert response.status_code == 403
    # The same browser, through the SPA, is signed in.
    assert await browser.is_signed_in()


async def test_the_docs_fill_in_the_csrf_header(anon_browser: Browser) -> None:
    """Declared as a security scheme in the contract, and filled in under
    that scheme, so a call sent from /api/docs carries it as one from the SPA does."""
    page = await anon_browser.navigate("/api/docs")

    schemes = app.openapi()["components"]["securitySchemes"].items()
    [key] = [key for key, s in schemes if s["in"] == "header" and s["name"] == CSRF_HEADER]
    assert f'preauthorizeApiKey("{key}", "1")' in page.text


async def test_the_guard_covers_the_domain() -> None:
    """If the contract held only /api/auth/me, the route test would pass
    while guarding nothing of the domain — so say so."""
    assert any(not path.startswith("/api/auth/") for _, path in guarded_routes()), (
        "no domain routes in the contract; is the domain mounted?"
    )


async def test_health_stays_open(anon_browser: Browser) -> None:
    """A load balancer's probe has no session, so nothing in this route's chain may
    require one."""
    response = await anon_browser.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
