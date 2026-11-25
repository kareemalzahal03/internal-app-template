"""Authentication: an OIDC provider proves who you are, this app runs the session.

The backend for frontend of RFC 10017 §6.1, with only local APIs (§6.1.2.5):
the API is the OAuth client, the browser holds an opaque session cookie, and
no token is kept. The provider is reached only through its discovery document.

The provider tells this app who someone is in an ID token: a signed
statement whose `sub` claim is the provider's permanent id for that person.

Specs, by the short names the comments cite them by. A bare "§" is in the
spec its section names at the top.
  RFC 10017 §6.1 ........ the architecture, cookies, CSRF defense
  RFC 9700, RFC 7636 .... the code grant with PKCE
  OIDC Core ............. sign-in, ID token claims
  OIDC Discovery ........ every provider URL and signing key
  RFC 7591 .............. registration: what the provider is told about us
  OIDC Registration ..... the same, OIDC's additions
  RP-Initiated Logout ... ending the provider's session too
  Back-Channel Logout ... the provider ending ours, server to server
  Front-Channel Logout .. the provider ending ours through the browser
  Layered Cookies ....... the __Host-Http- cookie prefix (a draft)

Each section opens with a plain overview; reading just those, top to
bottom, gives the whole design. The code says "sign in" and "sign out";
"logout" appears only in the specs' own names and in URL paths.
"""

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from functools import cached_property, lru_cache
from logging import getLogger
from secrets import token_urlsafe
from typing import Annotated, Any, ClassVar, Literal, Self, TypedDict

from authlib.common.urls import add_params_to_uri
from authlib.integrations.starlette_client import (
    OAuthError,
    StarletteIntegration,
    StarletteOAuth2App,
)
from authlib.oauth2.rfc7523 import PrivateKeyJWT
from beanie import Document, PydanticObjectId, UpdateResponse
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security.api_key import APIKeyCookie, APIKeyHeader
from httpx2 import HTTPError
from joserfc.errors import InvalidClaimError, InvalidKeyIdError, JoseError, MissingClaimError
from joserfc.jwk import KeySet, KeySetSerialization, RSAKey
from joserfc.jwt import ClaimsOption, JWTClaimsRegistry, decode
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    PlainSerializer,
    model_validator,
)
from pydantic_settings import BaseSettings
from pymongo import ASCENDING, IndexModel
from starlette.datastructures import URL
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.types import ASGIApp

logger = getLogger(__name__)

auth_router = APIRouter(prefix="/auth", tags=["auth"])


### APP URLS
#
# Every URL of this app that leaves it: to the provider, or to the browser
# at the end of a sign-in. All are built from one setting, APP_URL, never
# from the request, whose Host and scheme a proxy may have changed. They
# match what is registered with the provider.


def origin_url(value: Any) -> URL:
    """The URL in `value`, refused unless it is an origin: a host and nothing
    after it, not even a trailing slash, over https, or http on localhost."""
    url = value if isinstance(value, URL) else URL(value)

    if not url.hostname or url.path or url.query or url.fragment:
        raise ValueError(
            f"APP_URL must be an origin, such as https://app.example.com, not {value!r}."
        )

    # Browsers keep a Secure cookie only over https, or on localhost.
    if not (url.scheme == "https" or (url.scheme == "http" and url.hostname == "localhost")):
        raise ValueError(f"APP_URL must use https, or http on localhost, not {value!r}.")

    return url


class URLSettings(BaseSettings):
    """Every URL of this app the provider or the browser is sent to, built from APP_URL."""

    # Where this app is reached. The SPA and the API are one process on one origin.
    app_url: Annotated[URL, BeforeValidator(origin_url)]

    def auth_url(self, endpoint: Callable[..., Any]) -> URL:
        """The absolute URL the auth route `endpoint` is served at."""
        return auth_router.url_path_for(endpoint.__name__).make_absolute_url(
            base_url=self.app_url.replace(path="/api")
        )

    @property
    def callback_url(self) -> URL:
        """Where the provider sends the browser back with a code."""
        return self.auth_url(callback)

    @property
    def frontchannel_logout_url(self) -> URL:
        """Loaded by the provider in an iframe to end a session here."""
        return self.auth_url(frontchannel_logout)

    @property
    def backchannel_logout_url(self) -> URL:
        """Posted a logout token by the provider's server."""
        return self.auth_url(backchannel_logout)

    @property
    def jwks_url(self) -> URL:
        """Fetched by the provider's server for this app's public keys."""
        return self.auth_url(jwks)

    @property
    def login_url(self) -> URL:
        """The SPA's login page, where signing out or a failed sign-in lands."""
        return self.app_url.replace(path="/login")

    @property
    def sign_in_failed_url(self) -> URL:
        """The SPA's login page, telling it a sign-in failed."""
        return self.login_url.include_query_params(error="sign_in_failed")

    @property
    def home_url(self) -> URL:
        """Where a completed sign-in lands. Fixed: it takes no destination from the caller."""
        return self.app_url.replace(path="/")


@lru_cache
def get_urls() -> URLSettings:
    """The one URLSettings, read on first use and kept, since routes read it per request."""
    return URLSettings()


### REGISTRATION
#
# What the provider is told about this app, out of band: through an admin
# console, IaC or a registration endpoint. Above all, the exact URLs it may
# send browsers and logout requests to; a provider refuses any other.


# RFC 10017 §6.1.3.1: MUST use the authorization code grant.
# RFC 9700 §2.1.2: SHOULD use response type code, not the implicit grant.
RESPONSE_TYPE = "code"

# The claims asked for (OIDC Core §5.4). `openid` makes this an OIDC sign-in.
# RFC 9700 §2.3: SHOULD ask for the minimum privileges.
SCOPES = "openid profile email"

# Signs this app's JWTs when it authenticates with a key. Every major provider accepts it.
CLIENT_KEY_ALG = "RS256"

# Written out as its exact text: a provider compares redirect URIs character
# by character (RFC 9700 §4.1.3).
RegisteredURL = Annotated[URL, PlainSerializer(str, return_type=str)]


class ClientMetadata(BaseModel):
    """Everything a provider must be told about this app, under the specs'
    names. Fields with defaults are fixed by what this app is; the rest are
    its URLs. It registers with a key; a provider that takes only a secret is
    set up by hand instead."""

    # Its URLs are Starlette's, a type pydantic does not know.
    model_config = ConfigDict(arbitrary_types_allowed=True)

    # --- OIDC Registration §2 -----------------------------------------------
    # Shown on the provider's consent screen, if it has one. Logo, terms and
    # policy URLs could join it, for a provider that shows them.
    client_name: str = "Internal App"
    # A client with a server behind it, so it can keep a secret.
    application_type: str = "web"
    redirect_uris: list[RegisteredURL]
    response_types: list[str] = [RESPONSE_TYPE]
    # No refresh_token: tokens are discarded (RFC 7591 §2.1).
    grant_types: list[str] = ["authorization_code"]
    # RFC 9700 §2.5 RECOMMENDS an asymmetric method (OIDC Core §9).
    token_endpoint_auth_method: str = "private_key_jwt"
    token_endpoint_auth_signing_alg: str = CLIENT_KEY_ALG
    # Where the provider fetches the public half of that key.
    jwks_uri: RegisteredURL

    # --- RFC 7591 §2 ---------------------------------------------------------
    scope: str = SCOPES

    # --- RP-Initiated Logout §3.1 --------------------------------------------
    post_logout_redirect_uris: list[RegisteredURL]

    # --- Front-Channel Logout §2 ---------------------------------------------
    frontchannel_logout_uri: RegisteredURL
    # The spec's default is false. Without iss and sid, one browser can't be told apart.
    frontchannel_logout_session_required: bool = True

    # --- Back-Channel Logout §2.2 --------------------------------------------
    backchannel_logout_uri: RegisteredURL
    # Same default, same reason: the token must carry a sid.
    backchannel_logout_session_required: bool = True


def client_metadata(app_url: str) -> ClientMetadata:
    """What to register with a provider for this app served at `app_url`."""
    urls = URLSettings(app_url=app_url)
    return ClientMetadata(
        jwks_uri=urls.jwks_url,
        redirect_uris=[urls.callback_url],
        post_logout_redirect_uris=[urls.login_url],
        frontchannel_logout_uri=urls.frontchannel_logout_url,
        backchannel_logout_uri=urls.backchannel_logout_url,
    )


### THE PROVIDER
#
# Which provider this is and who this app is to it, read from the
# environment. Every provider URL and signing key comes from its discovery
# document, so nothing here is written against one provider: swapping
# Keycloak for Entra or Okta is three settings.


def private_key(value: Any) -> RSAKey | None:
    """The key in `value`, a JWK as one line of JSON, with a key id: its own,
    else its thumbprint (RFC 7638). None stays None. Refuses a public key,
    which cannot sign."""
    if value is None:
        return None
    key = value if isinstance(value, RSAKey) else RSAKey.import_key(json.loads(value))
    if not key.is_private:
        raise ValueError("OIDC_CLIENT_KEY must be a private key.")
    key.ensure_kid()
    return key


class ProviderSettings(BaseSettings):
    """Which provider, who this app is to it, and how the app proves that."""

    oidc_client_id: str

    # Discovery lives at a fixed path under it, and must name this same issuer.
    oidc_issuer: str

    @property
    def oidc_server_metadata_url(self) -> str:
        """The provider's discovery document (OIDC Discovery §4)."""
        return f"{self.oidc_issuer.rstrip('/')}/.well-known/openid-configuration"

    # Exactly one of the two. A private RSA key, as one line of JSON: the
    # provider holds only its public half, so nothing it stores can act as
    # this app. A secret is for a provider that takes no key.
    oidc_client_key: Annotated[RSAKey | None, BeforeValidator(private_key)] = None
    oidc_client_secret: str | None = None

    @model_validator(mode="after")
    def one_credential(self) -> Self:
        """Refuse both a key and a secret, or neither."""
        if (self.oidc_client_key is None) == (self.oidc_client_secret is None):
            raise ValueError("Set exactly one of OIDC_CLIENT_KEY and OIDC_CLIENT_SECRET.")
        return self

    @property
    def token_endpoint_auth_method(self) -> str:
        """How the token endpoint is told who this app is (OIDC Core §9)."""
        return "private_key_jwt" if self.oidc_client_key else "client_secret_basic"

    @cached_property
    def oidc_client(self) -> StarletteOAuth2App:
        """The OAuth client these settings describe."""

        # With a key, sign a short-lived JWT naming this app for every token
        # request (RFC 7523 §3). A secret Authlib sends by itself.
        auth_methods: list[PrivateKeyJWT] = []
        if self.oidc_client_key is not None:
            auth_methods.append(
                PrivateKeyJWT(
                    # Used only as the JWT's audience: the issuer, never the
                    # token endpoint URL (draft-ietf-oauth-rfc7523bis §4).
                    token_endpoint=self.oidc_issuer,
                    headers={"kid": self.oidc_client_key.kid},
                    alg=CLIENT_KEY_ALG,
                )
            )

        return StarletteOAuth2App(
            # Sign-in state lives in request.session, carried in a signed cookie.
            StarletteIntegration("idp"),
            server_metadata_url=self.oidc_server_metadata_url,
            client_id=self.oidc_client_id,
            # RFC 10017 §6.1.3.1: MUST be a confidential client. Authlib takes
            # the key in the secret's place.
            client_secret=self.oidc_client_secret or self.oidc_client_key,
            client_auth_methods=auth_methods,
            # Authlib adds `state` to every sign-in, and a `nonce` with the
            # openid scope (RFC 9700 §2.1: MUST prevent CSRF).
            client_kwargs={
                "response_type": RESPONSE_TYPE,
                # RFC 9700 §2.1.1: PKCE, with the one method that does not
                # expose the verifier.
                "code_challenge_method": "S256",
                "scope": SCOPES,
                "token_endpoint_auth_method": self.token_endpoint_auth_method,
            },
        )

    async def connect(self) -> None:
        """Load the discovery document and check it names this issuer and
        accepts this app's way of authenticating, or fail startup.

        Done once, at startup, so a wrong or unreachable provider fails the
        deploy rather than the first sign-in. The cost: a new copy of the app
        cannot start while the provider is down."""
        metadata = await self.oidc_client.load_server_metadata()

        # OIDC Discovery §4.3: MUST be identical to the issuer it was fetched under.
        md_issuer = metadata.get("issuer")
        if md_issuer != self.oidc_issuer:
            raise RuntimeError(
                f"The discovery document names issuer {md_issuer!r}, "
                f"not OIDC_ISSUER {self.oidc_issuer!r}."
            )

        # OIDC Discovery §3: when absent, the default is client_secret_basic.
        supported = metadata.get("token_endpoint_auth_methods_supported", ["client_secret_basic"])
        method = self.token_endpoint_auth_method
        if method not in supported:
            raise RuntimeError(
                f"The provider accepts {supported!r} at its token endpoint, not {method!r}."
            )


@lru_cache
def get_provider() -> ProviderSettings:
    """The one ProviderSettings, read on first use and kept, with its client."""
    return ProviderSettings()


def get_oidc_client() -> StarletteOAuth2App:
    """The one OAuth client."""
    return get_provider().oidc_client


OIDCClient = Annotated[StarletteOAuth2App, Depends(get_oidc_client)]


@auth_router.get("/jwks", include_in_schema=False)
async def jwks() -> JSONResponse:
    """This app's public signing key, as a JWK Set (RFC 7517 §5), for the
    provider's server to check the JWTs it signs. No keys with a secret."""
    key = get_provider().oidc_client_key
    keys: list[dict[str, Any]] = []
    if key is not None:
        # RFC 7517 §4.2, §4.4. OIDC Registration §2: MUST NOT contain private key values.
        keys.append({**key.as_dict(private=False), "use": "sig", "alg": CLIENT_KEY_ALG})
    return JSONResponse(
        {"keys": keys},
        # RFC 7517 §8.5.
        media_type="application/jwk-set+json",
        headers={"Cache-Control": "max-age=300"},
    )


### USERS
#
# Nobody signs up here and no password exists. The provider decides who may
# sign in; this app learns the answer as the claims in the ID token. A User
# is a local copy of those claims, keyed on `sub` and rewritten at every
# sign-in, so the app has a record to hang its own data off.


class UserClaims(BaseModel):
    """The claims about a person this app keeps. Only what it uses, so it
    stores nothing else about anyone. To keep another, add it here and its
    scope to the requested scopes."""

    # `email` scope (OIDC Core §5.1). Shown, never trusted to identify anyone:
    # that is `sub`. Keep `email_verified` too before matching on it.
    email: EmailStr | None = None
    # `profile` scope (OIDC Core §5.1)
    name: str | None = None


class User(Document):
    """The identity the provider asserts, mirrored locally."""

    # The only key: iss + sub is the stable identifier, and there is one iss (OIDC Core §5.7).
    sub: str
    # Provider-owned, rewritten at each sign-in. Everything beside it is the app's.
    info: UserClaims

    # When `info` was last mirrored.
    updated_at: datetime
    created_at: datetime

    class Settings:
        name = "users"
        indexes: ClassVar[list[IndexModel]] = [
            IndexModel([("sub", ASCENDING)], unique=True),
        ]


async def upsert_user(claims: UserClaims, sub: str) -> User:
    """Create or update the user with this sub, mirroring its claims."""
    now = datetime.now(UTC)
    user = await User.find_one(User.sub == sub).update(
        {
            "$set": {"info": claims.model_dump(mode="json"), "updated_at": now},
            "$setOnInsert": {"created_at": now},
        },
        # One atomic find_one_and_update, so two first sign-ins at once cannot
        # collide on the unique index, as a find then an insert could.
        upsert=True,
        response_type=UpdateResponse.NEW_DOCUMENT,
    )
    if isinstance(user, User):
        return user
    raise RuntimeError("upsert did not return the user document")


### SESSIONS
#
# How a signed-in browser is remembered. The API stores a Session and gives
# the browser a cookie holding only its random value: nothing to decode, and
# no script can read it. Deleting the Session ends it at once, for every
# copy of the cookie, which a self-contained token could not do.
#
# A session ends on whichever clock runs out first: idle time since the last
# request, or total time since sign-in.


# Keycloak's defaults; match the provider's session policy.
SESSION_IDLE = timedelta(minutes=30)
SESSION_MAX = timedelta(hours=10)


class CookieAttributes(TypedDict):
    """A cookie's name and attributes, as setting and clearing it both take
    them. Typed, so a misspelt or missing attribute fails the type check."""

    key: str
    path: str
    secure: bool
    domain: str | None
    httponly: bool
    samesite: Literal["lax", "strict", "none"]


# RFC 10017 §6.1.3.2 sets each attribute.
SESSION_COOKIE: CookieAttributes = {
    # SHOULD prefix. __Host-Http-: set over HTTP, by this host only (Layered Cookies §4.1.3.4).
    "key": "__Host-Http-session",
    # SHOULD be /, so it reaches every API route.
    "path": "/",
    # MUST. Browsers treat localhost as secure, so dev works.
    "secure": True,
    # SHOULD NOT set Domain: host-only, never sent to a sibling host.
    "domain": None,
    # MUST. No script can read it.
    "httponly": True,
    # SHOULD. Use lax if a guarded page must open from a link elsewhere.
    "samesite": "strict",
}


class Session(Document):
    """One signed-in browser."""

    # Handed back to the provider when signing out, so it can end the right
    # session without stopping to ask the user to confirm.
    id_token: str
    # The sub, not the user record's id: ending sessions by person reads only
    # this collection, and works even if the user record is gone.
    sub: str
    # The provider's session id, if it sends one. Not unique: two sign-ins in
    # one provider session share it.
    sid: str | None = None
    # The cookie's value: 32 random bytes. Never the ObjectId, which is a
    # timestamp and a counter, so guessable.
    cookie: str

    created_at: datetime
    # The idle deadline, pushed forward while the session is used.
    expires_at: datetime
    # Set at sign-in and never extended.
    absolute_expires_at: datetime

    async def touch(self) -> None:
        """Count this request as activity, pushing the idle deadline forward."""
        idle_expiry = min(datetime.now(UTC) + SESSION_IDLE, self.absolute_expires_at)
        # Write at most once per half window, never past the absolute deadline.
        if idle_expiry >= self.expires_at + SESSION_IDLE / 2:
            await self.set({Session.expires_at: idle_expiry})

    class Settings:
        name = "sessions"
        indexes: ClassVar[list[IndexModel]] = [
            IndexModel([("cookie", ASCENDING)], unique=True),
            # Ending sessions by sid or by sub can match several.
            IndexModel([("sid", ASCENDING)]),
            IndexModel([("sub", ASCENDING)]),
            # Cleanup only: every lookup checks the deadline itself.
            IndexModel([("expires_at", ASCENDING)], expireAfterSeconds=0),
        ]


async def start_session(id_token: str, sub: str, sid: str | None = None) -> Session:
    """Insert a session for a signed-in user, with a fresh random cookie value."""
    now = datetime.now(UTC)
    return await Session(
        id_token=id_token,
        sub=sub,
        sid=sid,
        cookie=token_urlsafe(32),
        created_at=now,
        expires_at=now + SESSION_IDLE,
        absolute_expires_at=now + SESSION_MAX,
    ).insert()


async def end_sessions(query: Mapping[Any, Any] | bool) -> None:
    """Delete every session a query matches, and log how many went."""
    result = await Session.find(query).delete()
    logger.info("Ended %s session(s).", result.deleted_count if result else 0)


### SIGNING IN
#
# Seven steps, as the browser lives them. Any failure lands on the login
# page with an error: the browser is mid-navigation, so there is no page to
# show it on. The sign-in routes are navigations, not API calls, so they are
# left out of the schema.

# Step 1. The browser arrives here with a full page load, since it has to
# visit the provider itself.
#
# Step 2. Authlib makes `state`, a `nonce` and a PKCE verifier, keeps them in
# request.session, and puts `state`, the nonce and the verifier's hash in
# the redirect to the provider.


@auth_router.get("/login", include_in_schema=False)
async def sign_in(request: Request, client: OIDCClient) -> RedirectResponse:
    """The Authentication Request (OIDC Core §3.1.2.1)."""
    return await client.authorize_redirect(request, redirect_uri=get_urls().callback_url)


# Step 3. On the way out, the middleware below writes request.session into a
# signed cookie, which the browser carries to the provider and back. A
# cookie, not a server-side store, so a sign-in can start on one copy of the
# app and finish on another. Signed, not encrypted: nothing in it is secret,
# but it must not change.


class OAuthStateSettings(BaseSettings):
    """The state cookie's signing key."""

    oauth_state_secret: str


def oauth_state_cookie(app: ASGIApp) -> ASGIApp:
    """Carries request.session from the sign-in redirect to the callback in a signed cookie."""
    # Built on the app's first call, the lifespan's startup, so a missing
    # secret fails startup.
    return SessionMiddleware(
        app,
        secret_key=OAuthStateSettings().oauth_state_secret,
        # __Host-Http-: no sibling host or script can plant it (login CSRF).
        session_cookie="__Host-Http-oauth-state",
        # Long enough for one sign-in.
        max_age=300,
        # Strict would withhold it on the redirect back from the provider.
        same_site="lax",
        https_only=True,
    )


# A factory, so the secret is read when the stack is built, not at import.
oauth_state_middleware = Middleware(oauth_state_cookie)


# Step 4. The provider signs the person in however the company has set it
# up, then sends the browser back here with a one-time code and the same
# `state`.
#
# Step 5. The middleware reads the cookie back into request.session. A
# missing, tampered or expired cookie becomes an empty one.
#
# Step 6. Authlib checks `state`, redeems the code, and verifies the ID token.


class IDTokenResponse(BaseModel):
    """The two parts of the token response sign-in uses (OIDC Core §3.1.3.3).
    The access and refresh tokens beside them are never read."""

    # The ID token as sent, kept for signing out.
    id_token: str
    # Its claims, verified by Authlib. Not a call to the UserInfo endpoint,
    # despite the name; this app makes none.
    userinfo: dict[str, Any]


async def redeem_code(request: Request, client: StarletteOAuth2App) -> IDTokenResponse:
    """The provider's verified answer to this browser's sign-in."""
    # OIDC Core §3.1.2.5 to §3.1.3.8, in one call: check the response for an
    # error; pop `state` from request.session and match it, so it passes once;
    # redeem the code with the PKCE verifier (RFC 7636 §4.5); verify the ID
    # token's signature, iss, aud, exp, iat and nonce (§3.1.3.7). `userinfo`
    # is missing if there was no ID token, which fails validation here.
    return IDTokenResponse.model_validate(await client.authorize_access_token(request))


# Step 7. Record the user, start the session, set its cookie, and send the
# browser to the app's home page. Only the ID token is kept.


class SignInClaims(BaseModel):
    """The ID token claims a session needs (OIDC Core §2). The rest are ignored."""

    # The person's id at the provider, never reassigned.
    sub: str
    # The provider's session id, if it supports logout (Back-Channel Logout §2.1).
    sid: str | None = None


async def complete_sign_in(token: IDTokenResponse) -> RedirectResponse:
    """Turn a verified token response into a signed-in browser, sent home."""
    claims = SignInClaims.model_validate(token.userinfo)
    await upsert_user(UserClaims.model_validate(token.userinfo), claims.sub)
    session = await start_session(token.id_token, claims.sub, claims.sid)

    response = RedirectResponse(get_urls().home_url, 303)
    # Expires with the absolute deadline, so the cookie cannot outlive the
    # session. The idle deadline slides on the server only.
    response.set_cookie(**SESSION_COOKIE, value=session.cookie, expires=session.absolute_expires_at)
    return response


# The provider's error codes that mean this app is set up wrong there, or the
# provider itself failed: only an operator can fix these (RFC 6749 §4.1.2.1, §5.2).
OPERATOR_ERRORS = {
    "invalid_request",
    "invalid_client",
    "unauthorized_client",
    "unsupported_response_type",
    "unsupported_grant_type",
    "invalid_scope",
    "server_error",
    "temporarily_unavailable",
}


@auth_router.get("/callback", include_in_schema=False)
async def callback(request: Request, client: OIDCClient) -> RedirectResponse:
    """Finish signing in. Every failure is logged once and lands on the login page."""
    try:
        return await complete_sign_in(await redeem_code(request, client))
    except OAuthError as exc:
        if exc.error in OPERATOR_ERRORS:
            logger.error("Sign-in failed: the provider answered %s", exc)
        else:
            # The person declined or did not finish, `state` did not match,
            # or the code was already used (OIDC Core §3.1.2.6, §3.1.2.7, §3.1.3.4).
            logger.warning("Sign-in refused: %s", exc)
    except JoseError as exc:
        # The ID token did not verify (OIDC Core §3.1.3.7).
        logger.warning("Sign-in refused: %s: %s", type(exc).__name__, exc)
    except Exception:
        # Anything else needs an operator: the provider unreachable or sending
        # no usable identity, or the database down.
        logger.exception("Sign-in failed.")
    return RedirectResponse(get_urls().sign_in_failed_url, 303)


### EVERY REQUEST
#
# Five steps on each API call after sign-in. A failure is a JSON 401 or 403.

# Step 1. The call arrives with the session cookie, which says who is
# calling, and the `X-CSRF` header, which says it came from this app's own
# page. Another origin cannot add a custom header without a CORS preflight,
# which this API never allows, so another site cannot use the cookie. Both
# are read through FastAPI's security classes, so the OpenAPI schema declares them.

SessionCookie = Annotated[
    str | None, Depends(APIKeyCookie(name=SESSION_COOKIE["key"], auto_error=False))
]

CSRF_HEADER = "X-CSRF"
csrf_header = APIKeyHeader(
    name=CSRF_HEADER, auto_error=False, description="Any value; the SPA sends 1."
)
CsrfHeader = Annotated[str | None, Depends(csrf_header)]


# Step 2. The session the cookie names, if it exists and neither clock has run out.
async def current_session(cookie: SessionCookie) -> Session | None:
    """The session the cookie names, or None if there is none or it has expired."""
    if cookie is None:
        return None
    session = await Session.find_one(Session.cookie == cookie)
    if session is None:
        return None
    # Checked here: the TTL index sweeps only about once a minute.
    now = datetime.now(UTC)
    if session.expires_at <= now or session.absolute_expires_at <= now:
        return None
    return session


CurrentSession = Annotated[Session | None, Depends(current_session)]


# Step 3. A 403 without the header, a 401 without a live session or its User.
# Step 4. Otherwise, push the idle clock forward and hand the User to the route.
async def current_user(session: CurrentSession, csrf: CsrfHeader) -> User:
    """The signed-in user, or 401. A 403 if the request lacks the CSRF header."""
    # 403, not 401: the caller may well be signed in; this request is refused.
    if csrf is None:
        raise HTTPException(403, f"Missing the {CSRF_HEADER} header.")

    if session is None or (user := await User.find_one(User.sub == session.sub)) is None:
        raise HTTPException(401, "Not authenticated.")

    await session.touch()
    return user


ActiveUser = Annotated[User, Depends(current_user)]

# Step 5. Put on whole routers, so a new route is guarded from the start.
# Router dependencies run before the path and body are parsed, so an
# anonymous caller gets a 401, never a 404 or 422, and learns nothing.
AUTHENTICATED = [Depends(current_user)]


class UserRead(BaseModel):
    """The signed-in user, as the SPA sees them."""

    id: PydanticObjectId
    email: EmailStr | None
    name: str | None


@auth_router.get("/me", operation_id="get_me")
async def get_me(user: ActiveUser) -> UserRead:
    """Who the caller is, or 401."""
    # Built by hand: the wire shape stays flat while storage nests.
    return UserRead(id=user.id, email=user.info.email, name=user.info.name)


### SIGNING OUT
#
# Three steps, in two halves: this app's session first, then the provider's.
# The first alone protects this app, so it never waits on the provider.

# Step 1. The browser arrives here with a full page load, since it has to
# visit the provider in step 3.
#
# Step 2. End the session here, and tell the browser to drop the cookie.


async def sign_out_browser(response: Response, session: Session | None) -> None:
    """End a browser's session here: its cookie, its row, and that row's siblings."""
    # All the attributes, not just the name: a browser ignores a clearing
    # Set-Cookie for a __Host- cookie unless it repeats Secure and Path=/.
    response.delete_cookie(**SESSION_COOKIE)
    if session is None:
        return
    # Siblings share the provider's sid: every session from that provider sign-in.
    if session.sid is not None:
        await end_sessions(Session.sid == session.sid)
    else:
        await session.delete()


# Step 3. The provider remembers the person too, in a cookie on its own site
# that only the browser can present. So the browser is sent to the
# provider's end_session_endpoint, which ends that session and sends it back
# to the login page. Without it, signing in again would pass straight through.
@auth_router.get("/logout", include_in_schema=False)
async def sign_out(
    request: Request, session: CurrentSession, client: OIDCClient
) -> RedirectResponse:
    """End the session here, then send the browser on to end it at the
    provider (RP-Initiated Logout). Lands on the login page either way."""
    # Not guarded: signing out twice is fine, and a JSON 401 would land in
    # the address bar.
    location = get_urls().login_url
    response = RedirectResponse(location, 303)
    await sign_out_browser(response, session)
    if session is None:
        return response

    # This signs the person out of every app on the provider. To end only
    # this app's session, return here.
    try:
        redirect: RedirectResponse = await client.logout_redirect(
            request,
            post_logout_redirect_uri=location,
            # So the provider ends the right session without asking.
            id_token_hint=session.id_token,
            # The provider needs this or the hint to know which client asks.
            client_id=client.client_id,
        )
        # Amazon Cognito ignores the standard parameters and needs this one;
        # other providers ignore it. Authlib would drop it, so it is added here.
        # https://docs.aws.amazon.com/cognito/latest/developerguide/logout-endpoint.html
        response.headers["location"] = add_params_to_uri(
            redirect.headers["location"], [("logout_uri", str(location))]
        )
    except (RuntimeError, HTTPError) as exc:
        # The provider publishes no end_session_endpoint, or discovery is unreachable.
        logger.warning("Provider sign-out skipped: %s: %s", type(exc).__name__, exc)

    return response


### PROVIDER LOGOUT
#
# Sometimes the provider ends a session first: the person signed out of
# another app, or an admin disabled them. It can tell this app in two ways,
# both optional, and either way the sessions it names are deleted:
#
# - Back-channel: its server POSTs a signed logout token. The signature is
#   the proof.
# - Front-channel: its logout page loads a URL here in a hidden iframe.
#   Nothing is signed, so it only ends a session it can match.
#
# A provider may support neither; the session clocks still end every session.


# Back-Channel Logout §2.8 requires it, Front-Channel Logout §2 recommends it.
NO_STORE = {"Cache-Control": "no-cache, no-store"}

# Back-channel (Back-Channel Logout; a bare § below is in it).

# The event that marks a JWT as a logout token (§2.4).
BACKCHANNEL_LOGOUT_EVENT = "http://schemas.openid.net/event/backchannel-logout"


# Authlib has no client-side back-channel logout, so the rules specific to a
# logout token are here; joserfc does the ordinary JWT work.
async def verified_logout_claims(logout_token: str, client: StarletteOAuth2App) -> dict[str, Any]:
    """The logout token's claims, validated by §2.6. Raises a JoseError if any step fails."""
    metadata = await client.load_server_metadata()

    # §2.6 step 3: the alg is validated as for an ID token. Discovery must
    # list those algs, RS256 among them (OIDC Discovery §3); RS256 if it does not.
    alg_values = metadata.get("id_token_signing_alg_values_supported") or ["RS256"]

    # §2.6 step 2: the signature, against the provider's keys. Step 1,
    # decryption, never applies: this client registers no encryption key.
    def signed_claims(jwk_set: KeySetSerialization) -> dict[str, Any]:
        keys = KeySet.import_key_set(jwk_set)
        return decode(value=logout_token, key=keys, algorithms=alg_values).claims

    # The keys are fetched once and kept. A key id not among them means the
    # provider has likely rotated its keys, so fetch them again, once, as
    # Authlib does for an ID token (OIDC Core §10.1.1).
    try:
        claims = signed_claims(await client.fetch_jwk_set())
    except InvalidKeyIdError:
        claims = signed_claims(await client.fetch_jwk_set(force=True))

    # §2.6 step 4: iss, aud, iat and exp as for an ID token, plus a jti.
    # exp is required, not just checked when present: it bounds replay.
    JWTClaimsRegistry(
        iss=ClaimsOption(essential=True, value=metadata["issuer"]),
        aud=ClaimsOption(essential=True, value=client.client_id),
        iat=ClaimsOption(essential=True),
        exp=ClaimsOption(essential=True),
        jti=ClaimsOption(essential=True),
    ).validate(claims)

    # §2.6 step 5: a sid or a sub, or both.
    if not (claims.get("sid") or claims.get("sub")):
        raise MissingClaimError("sid or sub")

    # §2.6 step 6: the logout event, mapped to an object. Other members may
    # sit beside it, and the object need not be empty (a SHOULD).
    if (events := claims.get("events")) is None:
        raise MissingClaimError("events")
    if not (isinstance(events, dict) and isinstance(events.get(BACKCHANNEL_LOGOUT_EVENT), dict)):
        raise InvalidClaimError("events")

    # §2.6 step 7: no nonce, so an ID token can't be replayed as a logout token.
    if "nonce" in claims:
        raise InvalidClaimError("nonce")

    # §2.6 steps 8 to 11 are optional and skipped. Without step 8, a captured
    # token can be replayed until its exp, and would only end the same
    # sessions again.
    return claims


@auth_router.post("/backchannel-logout", include_in_schema=False)
async def backchannel_logout(logout_token: Annotated[str, Form()], client: OIDCClient) -> Response:
    """The provider's server ending a session. The token's signature is the
    authentication; there is no cookie."""
    try:
        claims = await verified_logout_claims(logout_token, client)
    except JoseError as exc:
        # §2.6: any failed step is a 400.
        logger.warning("Logout token refused: %s: %s", type(exc).__name__, exc)
        return Response(None, 400, NO_STORE)

    # §2.7: the sessions its sid names, else its sub's. By sid, the person's
    # other browsers stay signed in. A provider holding several sessions for
    # one person may name only one; the rest end on their own clocks
    # (measured on Keycloak).
    if (sid := claims.get("sid")) is not None:
        await end_sessions(Session.sid == sid)
    elif (sub := claims.get("sub")) is not None:
        await end_sessions(Session.sub == sub)

    return Response(None, 200, NO_STORE)


# Front-channel (Front-Channel Logout; a bare § below is in it).

# The page is empty, so it loads nothing, and with no frame-ancestors any
# page may frame it. Framing an empty page gains an attacker nothing, and
# naming the provider's origin would mean guessing where its logout page is.
EMBEDDABLE = {**NO_STORE, "Content-Security-Policy": "default-src 'none'"}


@auth_router.get("/frontchannel-logout", include_in_schema=False)
async def frontchannel_logout(
    session: CurrentSession,
    client: OIDCClient,
    iss: str | None = None,
    sid: str | None = None,
) -> Response:
    """The provider ending a session through the browser, in a hidden iframe.

    Ends the session the optional `iss` and `sid` name, or the one this
    browser's cookie names. An empty 200, or a 400 if the request is
    malformed or names a session this browser is not running."""
    refused = Response(None, 400, EMBEDDABLE)

    # §2: both are optional, but a provider sending either MUST send both.
    if (iss is None) != (sid is None):
        logger.warning("Front-channel logout ignored: iss and sid must arrive together.")
        return refused

    # §2: the RP MAY ignore a request whose values it disagrees with. Nothing
    # is signed, so the issuer is the only check on offer.
    if iss is not None and iss != (await client.load_server_metadata())["issuer"]:
        logger.warning("Front-channel logout ignored: %r is not our provider.", iss)
        return refused

    response = Response(None, 200, EMBEDDABLE)

    # Rare: SameSite withholds the cookie unless the provider is on this site.
    if session is not None:
        if sid is not None and sid != session.sid:
            # The sid itself is left out: it ends the sessions it names.
            logger.warning("Front-channel logout ignored: the sid is not this browser's.")
            return refused
        await sign_out_browser(response, session)

    # Usually: no cookie, so the sid is the only handle. Finding no session is
    # still success; §2 counts a signed-out browser as signed out.
    elif sid is not None:
        await end_sessions(Session.sid == sid)

    return response
