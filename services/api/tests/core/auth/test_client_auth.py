"""How the app proves who it is at the provider's token endpoint.

The app is a confidential client (RFC 10017 §6.1.3.1), and it authenticates
in one of two ways, chosen by which credential it is given: a private key,
signing a short-lived JWT for each request (private_key_jwt), or a shared
secret (client_secret_basic). These tests sign in against the fake provider
and read the token request it received.

The fake checks every assertion as a real provider does, against the keys
it fetches from the app: the signature, iss, sub, aud, exp, and a jti it
has not seen before. So every sign-in in the suite proves the assertion is
right; the tests here cover what a provider would not notice.
"""

import json
from typing import Any
from urllib.parse import parse_qsl

from httpx2 import Request
from joserfc.jwt import decode
from pytest import MonkeyPatch, fixture, mark

from tests.parties import JWT_BEARER, OIDC_CLIENT_KEY, Browser, FakeProvider

pytestmark = mark.asyncio(loop_scope="session")

SECRET = "test-client-secret"


@fixture
def secret(monkeypatch: MonkeyPatch, provider: FakeProvider) -> None:
    """The app given a secret instead of a key, and the provider holding
    that secret for it."""
    monkeypatch.delenv("OIDC_CLIENT_KEY")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", SECRET)
    provider.client_secret = SECRET


async def token_request(browser: Browser, provider: FakeProvider) -> Request:
    """Sign `browser` in, and return the token request the provider received."""
    await browser.sign_in()
    return provider.token_requests[-1]


def form(request: Request) -> dict[str, str]:
    """The request's form body."""
    return dict(parse_qsl(request.content.decode()))


### With a key: private_key_jwt


async def test_a_key_signs_an_assertion_instead_of_sending_a_secret(
    anon_browser: Browser, provider: FakeProvider
) -> None:
    request = await token_request(anon_browser, provider)
    body = form(request)

    assert "authorization" not in request.headers
    assert "client_secret" not in body
    assert body["client_assertion_type"] == JWT_BEARER
    assertion = decode(body["client_assertion"], OIDC_CLIENT_KEY)
    assert assertion.header["alg"] == "RS256"
    assert assertion.header["kid"] == OIDC_CLIENT_KEY.kid


async def test_a_key_without_an_id_is_named_by_its_thumbprint(
    anon_browser: Browser, provider: FakeProvider, monkeypatch: MonkeyPatch
) -> None:
    """RFC 7638: a provider holding several keys picks one by kid. The
    provider finds the key under that name in the set the app serves, so
    the sign-in goes through."""
    unnamed: dict[str, Any] = {
        k: v for k, v in OIDC_CLIENT_KEY.as_dict(private=True).items() if k != "kid"
    }
    monkeypatch.setenv("OIDC_CLIENT_KEY", json.dumps(unnamed))
    body = form(await token_request(anon_browser, provider))

    assert await anon_browser.is_signed_in()
    assert (
        decode(body["client_assertion"], OIDC_CLIENT_KEY).header["kid"]
        == OIDC_CLIENT_KEY.thumbprint()
    )


### With a secret: client_secret_basic


@mark.usefixtures("secret")
async def test_a_secret_is_sent_as_basic_auth(
    anon_browser: Browser, provider: FakeProvider
) -> None:
    request = await token_request(anon_browser, provider)

    assert request.headers["authorization"].startswith("Basic ")
    assert "client_assertion" not in form(request)


### The public key, served to the provider


async def test_the_served_key_set_is_public(provider: FakeProvider) -> None:
    """OIDC Registration §2: MUST NOT contain private key values. Any private
    member of an RSA JWK (RFC 7518 §6.3.2) would let anyone act as this app."""
    response = await provider.fetch_client_keys()
    # RFC 7517 §8.5.
    assert response.headers["content-type"] == "application/jwk-set+json"

    (key,) = response.json()["keys"]
    assert not key.keys() & {"d", "p", "q", "dp", "dq", "qi", "oth"}
    assert key["kid"] == OIDC_CLIENT_KEY.kid
    assert (key["use"], key["alg"]) == ("sig", "RS256")


@mark.usefixtures("secret")
async def test_a_secret_serves_no_keys(provider: FakeProvider) -> None:
    assert (await provider.fetch_client_keys()).json() == {"keys": []}
