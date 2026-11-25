"""Signing out, from the browser's side: the session ends here, the cookie
goes, and the browser is sent on to end the provider's session too.

The provider's half is optional and may be unreachable, so the local half is
asserted to happen regardless.
"""

from logging import WARNING

from pytest import LogCaptureFixture, mark

from app.core.auth import Session, User
from tests.helpers import assert_lands_on, cookies_set_by, create_session, create_user, exists
from tests.parties import COOKIE, OIDC_CLIENT_ID, Browser, FakeProvider

pytestmark = mark.asyncio(loop_scope="session")


### The local half


async def test_a_replayed_cookie_is_refused_after_logout(browser: Browser) -> None:
    """The whole point of a server-side session: the session is deleted, so
    the browser keeping a copy of the cookie buys it nothing."""
    token = browser.session_cookie
    await browser.navigate("/api/auth/logout")

    browser.session_cookie = str(token)
    assert not await browser.is_signed_in()


async def test_logout_ends_this_browsers_other_sessions_too(
    browser: Browser, user: User, session: Session
) -> None:
    """Signing out means this browser is done, and a sid names a browser. The
    sibling row is one this browser orphaned by signing in again, so nothing
    can reach it — but it should not outlive the sign-out, and waiting for the
    provider's back-channel call to tidy it would assume a call that optional
    spec may never make."""
    orphan = await create_session(user, sid=session.sid)

    await browser.navigate("/api/auth/logout")

    assert not await exists(orphan)


async def test_logout_keeps_its_hands_off_sessions_with_no_sid(
    browser: Browser, session: Session
) -> None:
    """The trap in the sweep above: a provider that issues no sid leaves every
    session's sid null, and `sid == None` would match all of them — signing
    one person out would sign out everybody."""
    await session.set({Session.sid: None})
    stranger = await create_session(await create_user("stranger"))

    await browser.navigate("/api/auth/logout")

    assert await exists(stranger)


### The cookie


async def test_logout_tells_the_browser_to_drop_the_cookie(browser: Browser) -> None:
    """Asserted on the Set-Cookie the app sends, not on the client's jar.

    A `__Host-` cookie is refused unless the Set-Cookie carries Secure and
    Path=/ — on deletion as much as on the way in. Starlette's delete_cookie
    defaults both off, and the failure is silent: the browser keeps the old
    value and stays signed in while the server believes it signed them out.
    Verified in Chrome, which still sent the cookie after a default deletion.
    """
    cookie = cookies_set_by(await browser.navigate("/api/auth/logout"))[COOKIE]

    assert cookie.value == ""
    assert cookie["max-age"] == "0"
    assert cookie.key.startswith("__Host-"), "this test guards a prefix that is gone"
    assert cookie["secure"]
    assert cookie["path"] == "/"
    # The third prefix rule: a Domain of any value disqualifies the cookie.
    assert not cookie["domain"]


### The provider's half


async def test_logout_sends_the_browser_on_to_the_provider(
    browser: Browser, session: Session, provider: FakeProvider
) -> None:
    """The local session is this app's to end; the provider's SSO session is
    not, because it lives as a cookie on the provider's own origin. So the
    browser makes that trip, and the provider sends it back to the login
    page only because that URL is the one registered."""
    response = await browser.navigate("/api/auth/logout")

    assert_lands_on(response, "/login")
    (query,) = provider.end_session_requests
    # The hint is what lets the provider end the right session without
    # stopping to ask the user to confirm.
    assert query["id_token_hint"] == session.id_token
    # Sent alongside, so a session stored before id_token existed still works.
    assert query["client_id"] == OIDC_CLIENT_ID
    # Amazon Cognito's own name for the post-logout URL; it follows no other.
    assert query["logout_uri"] == query["post_logout_redirect_uri"]


async def test_logout_when_the_provider_publishes_no_end_session_endpoint(
    browser: Browser, provider: FakeProvider, caplog: LogCaptureFixture
) -> None:
    """RP-initiated logout is optional. A provider that does not implement it
    publishes no end_session_endpoint, and Authlib raises RuntimeError rather
    than any HTTP error — a different branch from the unreachable case below,
    and the reason that catch names two types."""
    del provider.discovery["end_session_endpoint"]
    with caplog.at_level(WARNING, logger="app.core.auth"):
        response = await browser.navigate("/api/auth/logout")

    assert_lands_on(response, "/login")
    assert "Provider sign-out skipped" in caplog.text
    # The half this app controls happened regardless.
    assert await Session.find_all().count() == 0


async def test_logout_with_the_provider_down_still_lands_on_the_login_page(
    browser: Browser, provider: FakeProvider
) -> None:
    """A provider that is unreachable must not break signing out — the half
    that protects this app's data has already happened. The outage arrives as
    the connection error of the HTTP library Authlib uses, which is what the
    app catches; an error from any other would turn signing out into a 500."""
    provider.down = True
    response = await browser.navigate("/api/auth/logout")

    assert_lands_on(response, "/login")
    # Still signed out here, which is the part that matters.
    assert await Session.find_all().count() == 0


async def test_logout_without_a_session_just_goes_to_the_login_page(
    anon_browser: Browser, provider: FakeProvider
) -> None:
    """Signing out is idempotent, and this is a navigation — answering it with
    a JSON 401 would put an error body in the address bar. Nor is there any
    reason to send someone with no session to the provider."""
    response = await anon_browser.navigate("/api/auth/logout")

    assert_lands_on(response, "/login")
    assert provider.end_session_requests == []
