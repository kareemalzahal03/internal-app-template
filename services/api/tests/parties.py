"""The two parties the app deals with, on either side of it.

A browser running the SPA calls the app: the SPA's API requests, and the
navigations the browser makes itself. An identity provider, run in
process, is on the other side. It answers the three requests the app's
OAuth client sends: discovery, the signing keys and the token endpoint. It
answers a browser at its authorization endpoint, where the person signs in
at once, and at its end-session endpoint, where the person signs out. And it
makes the two requests a provider's server makes of the
app: fetching the app's public keys, and sending a back-channel logout
token.

Everything in between is the app's real code and Authlib's: state, the
nonce, PKCE, the app's client credential and the ID token's signature are
all checked as they would be against a real provider. A test changes the
provider's data, never the app's functions: what its discovery document
says, who signs in, which key signs, or whether it answers at all.
"""

import time
from base64 import b64encode, urlsafe_b64encode
from hashlib import sha256
from secrets import token_urlsafe
from typing import Any
from urllib.parse import parse_qsl, urlencode

from httpx2 import AsyncClient, ConnectError, Request, Response
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet, RSAKey
from joserfc.jwt import ClaimsOption, JWTClaimsRegistry

from app.core.auth import CSRF_HEADER, SESSION_COOKIE, ClientMetadata, client_metadata

### App

# Where the app is served
APP_URL = "https://app.example.com"

# The client id the app registered with the provider, and uses to identify itself.
OIDC_CLIENT_ID = "test-client"

# The app's signing key
OIDC_CLIENT_KEY = RSAKey.generate_key(2048, parameters={"kid": "client-key"}, private=True)


### Browser

# Constant headers a browser sends when it navigates to a page
NAVIGATION = {"accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}

# The name of the app's session cookie.
COOKIE = SESSION_COOKIE["key"]


class Browser(AsyncClient):
    """A browser running the SPA, at the app's origin."""

    def __init__(self) -> None:
        # Every request carries the `X-CSRF` header the SPA adds.
        super().__init__(base_url=APP_URL, headers={CSRF_HEADER: "1"})

    @property
    def session_cookie(self) -> str | None:
        """The app's session cookie, as this browser holds it."""
        return self.cookies.get(COOKIE)

    @session_cookie.setter
    def session_cookie(self, value: str) -> None:
        self.cookies.set(COOKIE, value)

    async def navigate(
        self, url: str, params: dict[str, str] | None = None, *, follow_redirects: bool = True
    ) -> Response:
        """Load `url` as a page, as the address bar, a link or an iframe does:
        asking for HTML, and without the SPA's header. Follows redirects
        until a page answers, and returns that page, with each redirect on
        the way in its `history`. With `follow_redirects` false, takes the
        first step only."""
        request = self.build_request("GET", url, params=params, headers=NAVIGATION)
        # Every redirect copies this request's headers, so none adds it back.
        del request.headers[CSRF_HEADER]
        return await self.send(request, follow_redirects=follow_redirects)

    async def sign_in(self) -> Response:
        """Click the login page's sign-in button: navigate to /api/auth/login,
        by way of the provider, where the person signs in at once, and back.
        Returns the page the browser lands on."""
        return await self.navigate("/api/auth/login")

    async def is_signed_in(self) -> bool:
        """Whether this browser's cookie names a live session, as the SPA asks it."""
        status = (await self.get("/api/auth/me")).status_code
        # Anything else is neither answer, and must not pass as "signed out".
        assert status in (200, 401), status
        return status == 200


### Provider

ISSUER: str = "https://provider.example.com/realms/test-realm"

# Made once: a 2048-bit key takes long enough to notice per test.
PROVIDER_KEY = RSAKey.generate_key(2048, parameters={"kid": "provider-key"}, private=True)
# Same key id, different key: what a forger who copied the header would sign with.
IMPOSTOR_KEY = RSAKey.generate_key(2048, parameters={"kid": "provider-key"}, private=True)
# The key the provider moves to when it rotates, under a new key id.
NEXT_PROVIDER_KEY = RSAKey.generate_key(2048, parameters={"kid": "provider-key-2"}, private=True)

# Issued beside every ID token. The app must keep neither.
ACCESS_TOKEN = "access-token-the-app-must-not-keep"
REFRESH_TOKEN = "refresh-token-the-app-must-not-keep"

# RFC 7523 §2.2: what marks client_assertion as a JWT.
JWT_BEARER = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
# Back-Channel Logout §2.4: the event that marks a JWT as a logout token.
BACKCHANNEL_LOGOUT_EVENT = "http://schemas.openid.net/event/backchannel-logout"


class FakeProvider:
    """A provider at `ISSUER` with one registered client, `OIDC_CLIENT_ID`: the
    client `registration` describes."""

    def __init__(self) -> None:
        # What the client registered: the only URLs this provider sends a
        # browser back to, and the ones it calls the client at.
        self.registration: ClientMetadata = client_metadata(APP_URL)
        # A secret issued to the client, when it authenticates with one
        # instead of a key.
        self.client_secret: str | None = None
        # Assertion ids already accepted; a provider takes each one once.
        self.seen_jtis: set[str] = set()
        # What discovery returns (OIDC Discovery §3). Edit it to change what
        # the provider says it supports.
        self.discovery: dict[str, Any] = {
            "issuer": ISSUER,
            "authorization_endpoint": f"{ISSUER}/protocol/openid-connect/auth",
            "token_endpoint": f"{ISSUER}/protocol/openid-connect/token",
            "jwks_uri": f"{ISSUER}/protocol/openid-connect/certs",
            "end_session_endpoint": f"{ISSUER}/protocol/openid-connect/logout",
            "response_types_supported": ["code"],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["RS256"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["private_key_jwt"],
        }
        # The claims the next ID token asserts, over the ones every ID token
        # carries: so a test can change who signs in, drop a claim, or break
        # iss, aud, exp or the nonce.
        self.claims: dict[str, Any] = {
            "sub": "99999999-8888-7777-6666-555555555555",
            "email": "admin@example.com",
            "email_verified": True,
            "name": "Ada Admin",
        }
        # Signs every token issued. A key set here but not published makes
        # tokens that nothing verifies.
        self.signing_key = PROVIDER_KEY
        # The public keys served at jwks_uri.
        self.published_keys = [PROVIDER_KEY]
        # The token endpoint's answer when set, in place of the usual one.
        self.token_response: Response | None = None
        # Every request fails to connect, as if the provider were down.
        self.down = False
        # Each token request received, to read what the app sent.
        self.token_requests: list[Request] = []
        # Each ID token issued, in order.
        self.id_tokens: list[str] = []
        # The query of each sign-out the browser arrived with, in order.
        self.end_session_requests: list[dict[str, str]] = []
        # Codes issued and not yet redeemed, with what they were issued for.
        self.codes: dict[str, dict[str, str]] = {}

    async def __call__(self, request: Request) -> Response:
        """Answer one request, from the app or from a browser."""
        if self.down:
            raise ConnectError("connection refused", request=request)
        url = str(request.url.copy_with(query=None))
        if url == self.discovery["authorization_endpoint"]:
            return self.authorize(dict(request.url.params))
        if url == self.discovery.get("end_session_endpoint"):
            return self.end_session(dict(request.url.params))
        if url == f"{ISSUER}/.well-known/openid-configuration":
            return Response(200, json=self.discovery)
        if url == self.discovery.get("jwks_uri"):
            return Response(
                200, json={"keys": [key.as_dict(private=False) for key in self.published_keys]}
            )
        if url == self.discovery.get("token_endpoint") and request.method == "POST":
            self.token_requests.append(request)
            form = dict(parse_qsl(request.content.decode()))
            if not await self.client_authenticated(request, form):
                # RFC 6749 §5.2.
                return Response(401, json={"error": "invalid_client"})
            return self.token_response or self.token(form)
        return Response(404)

    def authorize(self, query: dict[str, str]) -> Response:
        """The authorization endpoint (OIDC Core §3.1.2), as the browser
        arrives at it and the person signs in, at once: redirects back to the
        redirect_uri with a code for the claims in `claims`, and the state."""
        # §3.1.2.1: the redirect_uri must exactly match a registered one.
        # §3.1.2.6: if either check fails, nothing is redirected anywhere.
        registered = [str(uri) for uri in self.registration.redirect_uris]
        if query.get("client_id") != OIDC_CLIENT_ID or query.get("redirect_uri") not in registered:
            return Response(400, json={"error": "invalid_request"})
        code = token_urlsafe(16)
        self.codes[code] = query
        back = f"{query['redirect_uri']}?{urlencode({'code': code, 'state': query['state']})}"
        return Response(302, headers={"location": back})

    def end_session(self, query: dict[str, str]) -> Response:
        """The end-session endpoint (RP-Initiated Logout §2), as the browser
        arrives at it: the person is signed out here at once, and sent back
        to the post_logout_redirect_uri."""
        self.end_session_requests.append(query)
        # §3: only to a URI the client registered; otherwise nowhere.
        registered = [str(uri) for uri in self.registration.post_logout_redirect_uris]
        if query.get("post_logout_redirect_uri") not in registered:
            return Response(400, json={"error": "invalid_request"})
        return Response(302, headers={"location": query["post_logout_redirect_uri"]})

    async def fetch_client_keys(self) -> Response:
        """GET the client's registered jwks_uri, as this provider does to
        check the client's assertions (OIDC Registration §2)."""
        # This provider's server, not a browser: no cookie, no CSRF header.
        async with AsyncClient() as server:
            return await server.get(str(self.registration.jwks_uri))

    async def client_authenticated(self, request: Request, form: dict[str, str]) -> bool:
        """Whether the token request proves it comes from the registered
        client (OIDC Core §9): signed by a key the client publishes at its
        jwks_uri, or with the secret issued to it."""
        if self.client_secret is not None:
            # RFC 6749 §2.3.1: HTTP Basic, the client id and secret.
            basic = b64encode(f"{OIDC_CLIENT_ID}:{self.client_secret}".encode()).decode()
            return request.headers.get("authorization") == f"Basic {basic}"

        if form.get("client_assertion_type") != JWT_BEARER:
            return False
        try:
            # Fetched from the client as each assertion arrives, so a key
            # the client stops publishing stops working at once.
            keys = KeySet.import_key_set((await self.fetch_client_keys()).json())
            claims = jwt.decode(form.get("client_assertion", ""), keys).claims
            # RFC 7523 §3: about and from the client, for this provider,
            # with an expiry. draft-ietf-oauth-rfc7523bis §4: the audience
            # is the issuer.
            JWTClaimsRegistry(
                iss=ClaimsOption(essential=True, value=OIDC_CLIENT_ID),
                sub=ClaimsOption(essential=True, value=OIDC_CLIENT_ID),
                aud=ClaimsOption(essential=True, value=ISSUER),
                exp=ClaimsOption(essential=True),
                jti=ClaimsOption(essential=True),
            ).validate(claims)
        except JoseError:
            return False
        # RFC 7523 §3: a jti may be refused if seen before.
        if claims["jti"] in self.seen_jtis:
            return False
        self.seen_jtis.add(claims["jti"])
        return True

    def rotate_key(self) -> None:
        """Publish a new key beside the old one and sign with it from now on,
        as a provider rotating its keys does."""
        self.published_keys.append(NEXT_PROVIDER_KEY)
        self.signing_key = NEXT_PROVIDER_KEY

    def sign(self, claims: dict[str, Any]) -> str:
        """A JWT of `claims`, signed with `signing_key`."""
        return jwt.encode({"alg": "RS256", "kid": self.signing_key.kid}, claims, self.signing_key)

    def token(self, form: dict[str, str]) -> Response:
        """The token endpoint (OIDC Core §3.1.3): redeems a code once, for an
        ID token naming the person in `claims`."""
        issued = self.codes.pop(form.get("code", ""), None)
        # RFC 6749 §4.1.3: the code is this client's and unused, and the
        # redirect_uri is the one it was issued for.
        if (
            issued is None
            or form.get("grant_type") != "authorization_code"
            or form.get("redirect_uri") != issued["redirect_uri"]
        ):
            return Response(400, json={"error": "invalid_grant"})
        # RFC 7636 §4.6: the verifier hashes to the challenge sent at sign-in.
        digest = sha256(form.get("code_verifier", "").encode()).digest()
        if urlsafe_b64encode(digest).rstrip(b"=").decode() != issued.get("code_challenge"):
            return Response(400, json={"error": "invalid_grant"})

        now = int(time.time())
        id_token = self.sign(
            {
                "iss": ISSUER,
                "aud": OIDC_CLIENT_ID,
                "iat": now,
                "exp": now + 300,
                "nonce": issued["nonce"],
                **self.claims,
            }
        )
        self.id_tokens.append(id_token)
        return Response(
            200,
            json={
                "id_token": id_token,
                "access_token": ACCESS_TOKEN,
                "refresh_token": REFRESH_TOKEN,
                "token_type": "Bearer",
                "expires_in": 300,
                "scope": issued["scope"],
            },
        )

    def logout_token(self, **claims: Any) -> str:
        """A logout token (Back-Channel Logout §2.4) carrying `claims`, over
        the ones every logout token carries. A claim given as None is sent as null."""
        now = int(time.time())
        return self.sign(
            {
                "iss": ISSUER,
                "aud": OIDC_CLIENT_ID,
                "iat": now,
                "exp": now + 120,
                "jti": token_urlsafe(8),
                "events": {BACKCHANNEL_LOGOUT_EVENT: {}},
                **claims,
            }
        )

    async def send_logout_token(self, token: str) -> Response:
        """POST `token` to the client's registered backchannel_logout_uri
        (Back-Channel Logout §2.5)."""
        async with AsyncClient() as server:
            return await server.post(
                str(self.registration.backchannel_logout_uri), data={"logout_token": token}
            )

    async def log_out(self, **claims: Any) -> Response:
        """End sessions at the client, server to server: a logout token
        carrying `claims`, sent to its back-channel logout URL."""
        return await self.send_logout_token(self.logout_token(**claims))

    def frontchannel_logout_url(self, sid: str | None = None) -> str:
        """Where this provider's logout page frames the client, for the
        session `sid` (Front-Channel Logout §2). With no sid, the bare
        registered URL: the provider names no session."""
        url = str(self.registration.frontchannel_logout_uri)
        # §2: when either parameter is included, both are.
        return f"{url}?{urlencode({'iss': ISSUER, 'sid': sid})}" if sid else url
