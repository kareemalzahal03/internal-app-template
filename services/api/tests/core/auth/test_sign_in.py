"""Signing in: the redirect to the provider, and the callback that comes back.

Each sign-in here is a whole one, against the fake provider: state, the
nonce and PKCE make the round trip, and the ID token is verified against the
provider's published key. A failing sign-in is the provider behaving badly,
never a patched function, except where the database is the thing failing.
"""

import time
from logging import ERROR, WARNING
from typing import Any
from urllib.parse import parse_qs, urlparse

from httpx2 import Response
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import ServerSelectionTimeoutError
from pytest import LogCaptureFixture, MonkeyPatch, mark, param

from app.core import auth as auth_module
from app.core.auth import Session, User
from tests.helpers import assert_lands_on, cookies_set_by
from tests.parties import ACCESS_TOKEN, COOKIE, IMPOSTOR_KEY, REFRESH_TOKEN, Browser, FakeProvider

pytestmark = mark.asyncio(loop_scope="session")


### The redirect to the provider


async def test_the_login_redirect_asks_for_a_code_with_pkce(anon_browser: Browser) -> None:
    """The one part of the request Authlib builds that this app has to get
    right. PKCE is switched on in the client's options, and passing it per
    call instead would drop the challenge while leaving a sign-in that still
    worked — so it is asserted on the wire, not in config."""
    response = await anon_browser.navigate("/api/auth/login", follow_redirects=False)
    query = parse_qs(urlparse(response.headers["location"]).query)

    assert query["response_type"] == ["code"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"]
    # Both are ours to verify at the callback, and neither is generated unless
    # the scope reaches Authlib as an OpenID one.
    assert query["nonce"]
    assert query["state"]
    assert "openid" in query["scope"][0]


async def test_the_state_cookie_carries_one_sign_in_there_and_back(anon_browser: Browser) -> None:
    """The values /login makes travel to the provider and back in this
    cookie. SameSite=Lax, not Strict: the browser returns from the
    provider's site, and Strict would leave the cookie behind. The
    __Host-Http- prefix: set only by this host, over HTTPS, and never by a
    script, so no other page can plant one (login CSRF). Five minutes: long
    enough for one sign-in."""
    login = await anon_browser.navigate("/api/auth/login", follow_redirects=False)
    cookie = cookies_set_by(login)["__Host-Http-oauth-state"]

    assert cookie["secure"]
    assert cookie["httponly"]
    assert cookie["path"] == "/"
    assert cookie["samesite"].lower() == "lax"
    assert cookie["max-age"] == "300"
    assert not cookie["domain"]


### The callback


async def test_sign_in_creates_a_user_and_a_session_and_lands_on_the_root(
    anon_browser: Browser, provider: FakeProvider
) -> None:
    """Sign-in takes no destination from the caller, so the callback has only
    one place to send anyone, and nothing a caller could redirect elsewhere."""
    assert_lands_on(await anon_browser.sign_in(), "/")

    user = await User.find_one(User.sub == provider.claims["sub"])
    assert user is not None
    assert user.info.email == provider.claims["email"]
    assert await Session.find(Session.sub == user.sub).count() == 1
    # The session cookie is now good for the rest of the app.
    assert await anon_browser.is_signed_in()


async def test_sign_in_keeps_the_id_token_and_discards_the_rest(
    anon_browser: Browser, provider: FakeProvider, empty_db: AsyncDatabase
) -> None:
    """The access and refresh tokens are checked at the callback and
    dropped, so nothing stored holds either. The ID token is kept as issued,
    to send back to the provider at sign-out."""
    await anon_browser.sign_in()

    session = await Session.find_one(Session.cookie == anon_browser.session_cookie)
    assert session is not None
    assert session.id_token == provider.id_tokens[-1]
    for name in await empty_db.list_collection_names(filter={"type": "collection"}):
        async for document in empty_db[name].find():
            assert ACCESS_TOKEN not in str(document), name
            assert REFRESH_TOKEN not in str(document), name


async def test_signing_in_twice_reuses_the_same_user(
    anon_browser: Browser, provider: FakeProvider
) -> None:
    """The user is keyed on `sub`, so a second sign-in updates the record
    rather than creating a second one — even when the email has changed."""
    await anon_browser.sign_in()
    provider.claims["email"] = "ada.admin@example.com"
    await anon_browser.sign_in()

    assert await User.find(User.sub == provider.claims["sub"]).count() == 1
    user = await User.find_one(User.sub == provider.claims["sub"])
    assert user is not None
    # The mirror follows the provider.
    assert user.info.email == "ada.admin@example.com"


async def test_a_provider_that_sends_no_email_still_signs_in(
    anon_browser: Browser, provider: FakeProvider
) -> None:
    """§5.1 makes every user claim OPTIONAL, and providers exercise that —
    Entra sends no `email` unless the claim is configured. Refusing the
    sign-in would be this app declaring a conformant provider broken, so the
    claim is stored as null and the identity still comes from `sub`."""
    del provider.claims["email"]
    del provider.claims["email_verified"]
    await anon_browser.sign_in()
    assert await anon_browser.is_signed_in()

    user = await User.find_one(User.sub == provider.claims["sub"])
    assert user is not None
    assert user.info.email is None
    assert (await anon_browser.get("/api/auth/me")).json()["email"] is None


### Sign-ins that fail
# Every failure answers the same way — back to the login page, no cookie —
# because the browser is mid-navigation and a JSON error in the address bar
# is the wrong answer whatever went wrong.


async def assert_lands_on_the_login_page(response: Response) -> None:
    """The browser is sent back to sign in again, with no session and no user."""
    assert_lands_on(response, "/login?error=sign_in_failed")
    assert COOKIE not in cookies_set_by(response)
    assert await User.find_all().count() == 0


async def sign_in_at_provider(browser: Browser) -> str:
    """Start a sign-in, and sign in at the provider, one step at a time.
    Returns where the provider sends the browser back to, not yet visited."""
    login = await browser.navigate("/api/auth/login", follow_redirects=False)
    at_provider = await browser.navigate(login.headers["location"], follow_redirects=False)
    return at_provider.headers["location"]


async def test_a_provider_that_sends_a_malformed_email_is_refused(
    anon_browser: Browser, provider: FakeProvider
) -> None:
    """Authlib checks the ID token is authentic, never that its claims are
    usable — it does not look at `email` at all. So this reaches our own
    validation, which is why that second block is not redundant."""
    provider.claims["email"] = "not-an-email-address"
    response = await anon_browser.sign_in()

    await assert_lands_on_the_login_page(response)


async def test_a_database_failure_mid_callback_still_lands_on_the_login_page(
    anon_browser: Browser, provider: FakeProvider, monkeypatch: MonkeyPatch
) -> None:
    """The identity can be verified and the sign-in still fail to be recorded.
    Before this, a database that was down escaped the handler and rendered a
    JSON 500 in the address bar."""

    async def unreachable(*args: Any, **kwargs: Any) -> User:
        raise ServerSelectionTimeoutError("no mongod reachable")

    monkeypatch.setattr(auth_module, "upsert_user", unreachable)
    response = await anon_browser.sign_in()

    await assert_lands_on_the_login_page(response)


async def test_a_callback_from_another_browsers_sign_in_is_refused(
    anon_browser: Browser, provider: FakeProvider
) -> None:
    """Login CSRF (RFC 9700 §4.7): someone starts a sign-in as themselves,
    then sends another person's browser to the callback with their code, to
    sign that person in as them. `state` is bound to the browser that
    started, by the state cookie, so this browser has nothing to match it
    with, and the code is never redeemed."""
    async with Browser() as attacker:
        callback = await sign_in_at_provider(attacker)

    response = await anon_browser.navigate(callback)

    await assert_lands_on_the_login_page(response)
    assert provider.token_requests == []


async def test_a_callback_cannot_be_replayed(anon_browser: Browser, provider: FakeProvider) -> None:
    """`state` is used once: the callback removes it, and with it the state
    cookie. The same callback URL again, from the history or a log, is
    refused before its code reaches the provider."""
    callback = await sign_in_at_provider(anon_browser)
    await anon_browser.navigate(callback)

    replay = await anon_browser.navigate(callback)

    assert_lands_on(replay, "/login?error=sign_in_failed")
    assert COOKIE not in cookies_set_by(replay)
    # Refused here, not by the provider: the one token request is the first.
    assert len(provider.token_requests) == 1
    assert await Session.find_all().count() == 1


async def test_an_unreachable_provider_still_redirects(
    anon_browser: Browser, provider: FakeProvider
) -> None:
    """Not every failure is an OAuthError — the provider can simply be down,
    here between the person signing in there and the code being redeemed."""
    callback = await sign_in_at_provider(anon_browser)
    provider.down = True
    response = await anon_browser.navigate(callback)

    await assert_lands_on_the_login_page(response)


### Failures told apart by their logs
# Each branch of the callback's error handling answers identically, so the
# redirect alone cannot tell them apart. These assert the log line too, which
# is the only place the distinction survives: an unreachable provider needs an
# operator, a bad token does not.


@mark.parametrize(
    "claims",
    [
        param({"aud": "another-client"}, id="addressed to another client"),
        param({"iss": "https://elsewhere.example.com"}, id="from another issuer"),
        param({"iat": int(time.time()) - 3700, "exp": int(time.time()) - 3600}, id="expired"),
        param({"nonce": "another-sign-in"}, id="issued for another sign-in"),
        # OIDC Core §2: REQUIRED, and the key the user is stored under.
        param({"sub": None}, id="about nobody"),
    ],
)
async def test_an_id_token_with_a_bad_claim_is_rejected(
    anon_browser: Browser,
    provider: FakeProvider,
    caplog: LogCaptureFixture,
    claims: dict[str, Any],
) -> None:
    """OIDC Core §3.1.3.7: correctly signed, and still not for this sign-in.
    A claim set to None is left out."""
    for name, value in claims.items():
        if value is None:
            del provider.claims[name]
        else:
            provider.claims[name] = value
    with caplog.at_level(WARNING, logger="app.core.auth"):
        response = await anon_browser.sign_in()

    await assert_lands_on_the_login_page(response)
    assert "Sign-in refused" in caplog.text


async def test_an_id_token_signed_by_another_key_is_rejected(
    anon_browser: Browser, provider: FakeProvider, caplog: LogCaptureFixture
) -> None:
    """The header names the provider's key; the signature is someone else's."""
    provider.signing_key = IMPOSTOR_KEY
    with caplog.at_level(WARNING, logger="app.core.auth"):
        response = await anon_browser.sign_in()

    await assert_lands_on_the_login_page(response)
    assert "Sign-in refused" in caplog.text


async def test_a_provider_refusing_this_app_is_an_error_not_a_refusal(
    anon_browser: Browser,
    provider: FakeProvider,
    caplog: LogCaptureFixture,
    monkeypatch: MonkeyPatch,
) -> None:
    """RFC 6749 §5.2: the token endpoint answers invalid_client when the app's
    credential is not the one registered. It arrives as the same kind of
    error as a person declining, but only an operator can fix it, so it must
    not be filed with them."""
    monkeypatch.delenv("OIDC_CLIENT_KEY")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "not-the-registered-secret")
    provider.client_secret = "the-registered-secret"
    with caplog.at_level(WARNING, logger="app.core.auth"):
        response = await anon_browser.sign_in()

    await assert_lands_on_the_login_page(response)
    [record] = caplog.records
    assert record.levelno == ERROR
    assert "invalid_client" in record.getMessage()


async def test_an_unexpected_callback_error_still_redirects(
    anon_browser: Browser, provider: FakeProvider, caplog: LogCaptureFixture
) -> None:
    """The catch-all exists because a browser is mid-navigation: whatever went
    wrong, a JSON 500 in the address bar is the wrong answer. A token endpoint
    answering with a web page is one failure no branch above names."""
    provider.token_response = Response(200, html="<html>Service unavailable</html>")
    with caplog.at_level(ERROR, logger="app.core.auth"):
        response = await anon_browser.sign_in()

    await assert_lands_on_the_login_page(response)
    assert "Sign-in failed" in caplog.text


async def test_a_token_response_with_no_id_token_is_refused(
    anon_browser: Browser, provider: FakeProvider, caplog: LogCaptureFixture
) -> None:
    """What a provider sends when `openid` drops out of the scopes: an access
    token alone. Authlib then attaches no `userinfo`, and the callback has no
    verified identity to sign in with."""
    provider.token_response = Response(200, json={"access_token": "a", "token_type": "Bearer"})
    with caplog.at_level(ERROR, logger="app.core.auth"):
        response = await anon_browser.sign_in()

    await assert_lands_on_the_login_page(response)
    assert "Sign-in failed" in caplog.text
