"""The provider ending sessions of its own accord: back-channel logout, a
signed token POSTed server to server, and front-channel logout, an unsigned
GET from an iframe in the browser.

Both arrive with no session cookie worth trusting, so each test's question is
the same: which sessions does this request name, and is it entitled to name
them. Sessions are made directly, because the provider is the caller here,
not a browser that signed in.
"""

import time
from logging import ERROR
from typing import Any

from pytest import LogCaptureFixture, mark, param

from app.core.auth import Session, User
from tests.helpers import cookies_set_by, create_session, create_user, exists
from tests.parties import (
    BACKCHANNEL_LOGOUT_EVENT,
    COOKIE,
    IMPOSTOR_KEY,
    ISSUER,
    NEXT_PROVIDER_KEY,
    Browser,
    FakeProvider,
)

pytestmark = mark.asyncio(loop_scope="session")


### Back-channel logout: which sessions a verified token ends


async def test_back_channel_logout_ends_every_session_the_sid_names(
    browser: Browser, user: User, session: Session, provider: FakeProvider
) -> None:
    """§2.7 says the RP locates the session(s) the sid identifies — plural.
    One browser that signed in twice holds two rows under one sid, and leaving
    the second alive would leave that browser signed in."""
    second = await create_session(user, sid=session.sid)

    response = await provider.log_out(sid=session.sid)

    assert response.status_code == 200
    assert not await exists(second)
    assert not await browser.is_signed_in()


async def test_a_token_naming_both_ends_only_the_browser_it_names(
    browser: Browser, user: User, session: Session, provider: FakeProvider
) -> None:
    """A session the provider says is over stops working here at once, with no
    browser involved and without waiting for either clock.

    The two names are not the same size: a sid is one browser, a sub is
    every browser that person has open. A token carrying both is naming that
    person's *one* browser, so the laptop signing out must not take the phone
    with it — which is what an `Or` of the two conditions would do."""
    other_device = await create_session(user, sid="some-other-browser")
    assert await browser.is_signed_in()

    response = await provider.log_out(sid=session.sid, sub=user.sub)

    assert response.status_code == 200
    assert not await exists(session)
    assert not await browser.is_signed_in()
    assert await exists(other_device)


async def test_back_channel_logout_falls_back_to_the_subject(
    user: User, session: Session, provider: FakeProvider
) -> None:
    """A provider that names no session still ends that person's sessions —
    `sid` comes from an optional spec, `sub` is always there. Ending them
    reads only the sessions: the user record is a mirror of the provider's
    claims and may be trimmed or anonymised on its own schedule, and a
    session must still end when it is."""
    await user.delete()

    response = await provider.log_out(sub=user.sub)

    assert response.status_code == 200
    assert not await exists(session)


### Back-channel logout: the token itself
# The rules a logout token must pass (§2.6), each broken in turn. The tests
# above are the same tokens unbroken, so these are known to refuse bad
# tokens rather than all of them.


@mark.parametrize(
    "overrides",
    [
        param({"exp": int(time.time()) - 3600}, id="expired an hour ago"),
        param({"exp": None}, id="no expiry at all"),
        param({"nonce": "n"}, id="an ID token wearing a logout token's clothes"),
        param({"events": {BACKCHANNEL_LOGOUT_EVENT: "not-an-object"}}, id="no event"),
        param({"sid": None, "sub": None}, id="names nobody"),
        param({"aud": "another-client"}, id="addressed elsewhere"),
        param({"iss": "https://evil.example"}, id="wrong issuer"),
    ],
)
async def test_a_logout_token_that_breaks_a_rule_is_refused(
    provider: FakeProvider, overrides: dict[str, Any]
) -> None:
    """Each of these is signed by the provider's key: the signature is
    necessary and never sufficient."""
    response = await provider.log_out(**{"sid": "a-browser", **overrides})

    assert response.status_code == 400


async def test_a_forged_logout_token_is_refused(provider: FakeProvider) -> None:
    """§2.6 makes the signature one of the validation steps, so a token signed
    by anyone else must be a 400 like any other rule break.

    Regression: joserfc raises BadSignatureError here, which is a *sibling* of
    ClaimError rather than a subclass. Catching only claim errors would let a
    forged token out as a 500 — the one input on this endpoint most likely to
    be hostile, answered with a stack trace instead of a refusal."""
    provider.signing_key = IMPOSTOR_KEY
    response = await provider.log_out(sid="a-browser")

    assert response.status_code == 400
    assert response.headers["cache-control"] == "no-cache, no-store"


async def test_a_logout_token_under_a_rotated_key_is_accepted(
    browser: Browser, session: Session, provider: FakeProvider
) -> None:
    """The app keeps the provider's keys once fetched. When the provider
    rotates, the first token under the new key names a key id the app has
    not seen, and the app fetches the keys again rather than refuse every
    logout until it restarts."""
    # Fetches the keys, and keeps them.
    assert (await provider.log_out(sid="someone-else")).status_code == 200
    provider.rotate_key()

    response = await provider.log_out(sid=session.sid)

    assert response.status_code == 200
    assert not await browser.is_signed_in()


async def test_a_logout_token_under_an_unpublished_key_is_refused(
    provider: FakeProvider,
) -> None:
    """Fetching the keys again finds nothing new, so the token is refused
    like any other bad signature, not answered with a 500."""
    provider.signing_key = NEXT_PROVIDER_KEY

    response = await provider.log_out(sid="a-browser")

    assert response.status_code == 400


async def test_a_logout_token_that_proves_nothing_is_refused(provider: FakeProvider) -> None:
    """The endpoint is unauthenticated by necessity — the provider calls it —
    so the token's own signature is the only thing standing in front of it."""
    response = await provider.send_logout_token("not.a.real.token")

    assert response.status_code == 400
    assert response.headers["cache-control"] == "no-cache, no-store"


async def test_an_unreachable_provider_is_not_reported_as_a_bad_token(
    provider: FakeProvider, caplog: LogCaptureFixture
) -> None:
    """A 400 says "your token is bad". Discovery being down says nothing about
    the token, and answering 400 would file our own outage under someone
    probing us — so it is left to the 500 handler, which logs it as a fault."""
    provider.down = True
    with caplog.at_level(ERROR, logger="app.core.errors"):
        response = await provider.send_logout_token("anything")

    assert response.status_code == 500
    assert "ConnectError" in caplog.text


### Front-channel logout
# The same job with nothing signed in it, so there is no token to build:
# every test is the endpoint's own reasoning about two query parameters.
# The issuer in discovery is all the request can be checked against.


async def test_a_matching_logout_takes_the_cookie_back_too(
    browser: Browser, session: Session, provider: FakeProvider
) -> None:
    """When the browser did send its cookie, the session it names and the
    session the provider named are the same one — so the cookie goes as well,
    rather than being left pointing at a row that no longer exists."""
    response = await browser.navigate(provider.frontchannel_logout_url(session.sid))

    assert response.status_code == 200
    assert cookies_set_by(response)[COOKIE]["max-age"] == "0"
    assert not await exists(session)


async def test_a_logout_naming_someone_elses_session_is_ignored(
    browser: Browser, session: Session, provider: FakeProvider
) -> None:
    """§2's second check. A cookie arrived, so we know which session this
    browser is running — and it is not the one named. Acting anyway would sign
    out a session the provider said nothing about, which is the whole of what
    an unsigned request could otherwise be used for."""
    elsewhere = await create_session(await create_user("someone-else"), sid="their-browser")

    response = await browser.navigate(provider.frontchannel_logout_url("their-browser"))

    assert response.status_code == 400
    assert await browser.is_signed_in()
    # Refusing means refusing outright: the named session survives too.
    assert await exists(elsewhere)


async def test_front_channel_logout_ends_every_session_the_sid_names(
    anon_browser: Browser, provider: FakeProvider
) -> None:
    """The case the endpoint exists for. Nothing identifies the session but the
    `sid` in the query string, and that has to be enough — a browser that had
    sent its cookie would not have needed the provider to tell us anything.

    A sid names "a Session of a User Agent or device", not a row here, so
    one browser signing in twice while its provider session lasts leaves two
    rows under a single sid. Both are that browser's, so both end — verified
    against the Compose provider, which reuses the sid on the second sign-in
    and issues a fresh one to a second browser."""
    someone = await create_user("someone")
    first = await create_session(someone, sid="someones-browser")
    second = await create_session(someone, sid="someones-browser")

    response = await anon_browser.navigate(provider.frontchannel_logout_url("someones-browser"))

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache, no-store"
    assert not await exists(first)
    assert not await exists(second)


async def test_an_unknown_session_is_a_quiet_success(
    anon_browser: Browser, provider: FakeProvider
) -> None:
    """§2: already logged out is logged out. An iframe has no way to report a
    problem, and a session we cannot find is not one."""
    response = await anon_browser.navigate(provider.frontchannel_logout_url("no-such-session"))

    assert response.status_code == 200


async def test_front_channel_logout_from_elsewhere_is_ignored(
    browser: Browser, session: Session, provider: FakeProvider
) -> None:
    """Nothing in this request is signed, so the issuer is the only claim that
    can be checked at all — and §2 says a mismatch may be ignored."""
    response = await browser.navigate(
        provider.frontchannel_logout_url(),
        params={"iss": "https://evil.example", "sid": str(session.sid)},
    )

    assert response.status_code == 400
    assert await browser.is_signed_in()


@mark.parametrize("missing", ["iss", "sid"])
async def test_half_a_logout_request_is_refused(
    browser: Browser, session: Session, provider: FakeProvider, missing: str
) -> None:
    """§2: "When either parameter is included, both MUST be present." Acting on
    half of it would mean guessing which half was meant."""
    params = {"iss": ISSUER, "sid": str(session.sid)}
    del params[missing]

    response = await browser.navigate(provider.frontchannel_logout_url(), params=params)

    assert response.status_code == 400
    assert await browser.is_signed_in()


async def test_front_channel_logout_falls_back_to_the_cookie(
    browser: Browser, provider: FakeProvider
) -> None:
    """`frontchannel_logout_session_required` defaults to false, so a provider
    may name nothing at all. Then the cookie is the only session there is."""
    response = await browser.navigate(provider.frontchannel_logout_url())

    assert response.status_code == 200
    assert not await browser.is_signed_in()


async def test_front_channel_logout_without_a_session_is_still_a_success(
    anon_browser: Browser, provider: FakeProvider
) -> None:
    """The usual case, in fact: a `SameSite=Strict` cookie is not sent inside
    the provider's iframe, so this endpoint routinely runs with no session to
    end and must not treat that as a failure."""
    response = await anon_browser.navigate(provider.frontchannel_logout_url())

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache, no-store"
