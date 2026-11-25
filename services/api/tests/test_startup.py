"""Every piece the app needs fails startup when it cannot start.

Each piece reads its own settings as it starts: the state cookie's secret
when Starlette builds the middleware stack, the provider's and the
database's in the lifespan. Under uvicorn both happen during the lifespan's
startup, and lifespan "on" makes uvicorn exit on a failure in either. Its
default mode ("auto") would take a failure while building the stack to mean
"no lifespan support" and keep serving 500s, so the image every command runs
in sets it.
"""

import json

from pydantic import ValidationError
from pytest import MonkeyPatch, mark, raises

from app.main import app
from tests.parties import OIDC_CLIENT_KEY, FakeProvider


async def start_app() -> None:
    """Run the app's lifespan: its startup, then at once its shutdown."""
    async with app.router.lifespan_context(app):
        pass


def test_a_missing_state_secret_fails_building_the_middleware(monkeypatch: MonkeyPatch) -> None:
    """Starlette builds the stack on the first call, the lifespan's startup."""
    monkeypatch.delenv("OAUTH_STATE_SECRET")
    with raises(ValidationError, match="oauth_state_secret"):
        app.build_middleware_stack()


@mark.parametrize(
    ("app_url", "refusal"),
    [
        # Each registered URL would then hold "//api".
        ("https://app.example.com/", "must be an origin"),
        # The SPA is served from the root, not under a path.
        ("https://app.example.com/internal", "must be an origin"),
        # No scheme: every URL sent to the provider would be relative.
        ("app.example.com", "must be an origin"),
        # The Secure session cookie would never come back.
        ("http://app.example.com", "must use https"),
        # Only http is allowed instead, and only on localhost.
        ("ftp://localhost", "must use https"),
    ],
)
@mark.asyncio(loop_scope="session")
async def test_an_app_url_that_is_not_an_https_origin_fails_the_lifespan(
    app_url: str, refusal: str, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_URL", app_url)
    with raises(ValidationError, match=refusal):
        await start_app()


@mark.parametrize(
    ("variable", "refusal"),
    [
        ("APP_URL", "app_url"),
        ("OIDC_ISSUER", "oidc_issuer"),
        # The client credential: one of two variables, and neither is set.
        ("OIDC_CLIENT_KEY", "exactly one"),
        ("MONGODB_URL", "mongodb_url"),
    ],
)
@mark.asyncio(loop_scope="session")
async def test_a_missing_setting_fails_the_lifespan(
    variable: str, refusal: str, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.delenv(variable)
    with raises(ValidationError, match=refusal):
        await start_app()


@mark.asyncio(loop_scope="session")
async def test_both_client_credentials_fail_the_lifespan(monkeypatch: MonkeyPatch) -> None:
    """Which method the app uses must not depend on which value wins."""
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "test-client-secret")
    with raises(ValidationError, match="exactly one"):
        await start_app()


@mark.asyncio(loop_scope="session")
async def test_a_public_client_key_fails_the_lifespan(monkeypatch: MonkeyPatch) -> None:
    """The public half cannot sign: refused at startup, not at the first sign-in."""
    monkeypatch.setenv("OIDC_CLIENT_KEY", json.dumps(OIDC_CLIENT_KEY.as_dict(private=False)))
    with raises(ValidationError, match="private key"):
        await start_app()


@mark.asyncio(loop_scope="session")
async def test_a_provider_naming_another_issuer_fails_the_lifespan(
    provider: FakeProvider,
) -> None:
    """OIDC Discovery §4.3: the document must name the issuer it was fetched under."""
    provider.discovery["issuer"] = "https://elsewhere.example.com"
    with raises(RuntimeError, match="names issuer"):
        await start_app()


@mark.asyncio(loop_scope="session")
async def test_a_provider_refusing_the_auth_method_fails_the_lifespan(
    provider: FakeProvider,
) -> None:
    """A provider that only takes a secret, given a key: every sign-in would
    fail at the token endpoint, so the app does not start."""
    provider.discovery["token_endpoint_auth_methods_supported"] = ["client_secret_basic"]
    with raises(RuntimeError, match="private_key_jwt"):
        await start_app()


@mark.asyncio(loop_scope="session")
async def test_a_provider_listing_no_auth_methods_takes_only_a_secret(
    provider: FakeProvider,
) -> None:
    """OIDC Discovery §3: an absent list means client_secret_basic alone."""
    del provider.discovery["token_endpoint_auth_methods_supported"]
    with raises(RuntimeError, match="client_secret_basic"):
        await start_app()
