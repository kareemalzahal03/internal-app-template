"""The fixtures the whole suite shares.

Tests run on the host against the Compose Mongo instance, but in a separate
database (appdb_test) so the tests never touch dev data. A second
database name in the same mongod is all the isolation these tests need —
testcontainers would add setup without adding safety here.

No identity provider runs either. A fake one answers in process, at its
issuer, so a sign-in in a test runs the app's real code end to end.
Tests that only need someone signed in make the session the same way
sign-in does, without the round trip.
"""

from collections.abc import AsyncGenerator
from json import dumps
from os import environ
from typing import Any
from urllib.parse import urlsplit

from httpx2 import ASGITransport, AsyncClient, ConnectError, MockTransport, Request, Response
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import ServerSelectionTimeoutError
from pytest import FixtureRequest, MonkeyPatch, exit, fixture
from pytest_asyncio import fixture as async_fixture

from app.core.auth import Session, User, get_provider, get_urls
from app.db import MongoSettings, init_beanie_models, mongo_db
from app.main import app
from tests.helpers import create_session, create_user
from tests.parties import APP_URL, ISSUER, OIDC_CLIENT_ID, OIDC_CLIENT_KEY, Browser, FakeProvider

### Test Environment

environ.update(
    {
        # Shorter than dev's ten seconds, so a stopped Mongo ends the run at once.
        "MONGODB_URL": "mongodb://localhost:27017/?timeoutMS=1000&appName=devAppTests",
        "MONGODB_DB": "appdb_test",
        "APP_URL": APP_URL,
        "OIDC_ISSUER": ISSUER,
        "OIDC_CLIENT_ID": OIDC_CLIENT_ID,
        "OIDC_CLIENT_KEY": dumps(OIDC_CLIENT_KEY.as_dict(private=True)),
        "OAUTH_STATE_SECRET": "test-oauth-state-secret",
    }
)


@fixture(autouse=True)
def fresh_settings() -> None:
    """Each test reads its settings anew, from its own environment."""
    # The app caches these for its lifetime. Cleared before every test, so a
    # test that changes the environment needs nothing else, and no test
    # inherits another's OAuth client or the discovery document it cached.
    get_urls.cache_clear()
    get_provider.cache_clear()


### Test Network


@fixture(autouse=True)
def provider() -> FakeProvider:
    """The identity provider every test runs against, in process."""
    return FakeProvider()


@fixture(autouse=True)
def network(monkeypatch: MonkeyPatch, provider: FakeProvider) -> None:
    """The test's network, for every HTTP client made during a test: the
    app's host reaches the app and the provider's host reaches `provider`,
    both in process. No other host is reachable."""

    def unreachable(request: Request) -> Response:
        raise ConnectError(f"{request.url.host} is not on the test network", request=request)

    hosts = {
        # An error no handler claims comes back as a browser sees it, the
        # app's 500 response, not raised into the test. The app logs it with
        # its traceback, which a failing test prints.
        f"all://{urlsplit(APP_URL).netloc}": ASGITransport(app, raise_app_exceptions=False),
        f"all://{urlsplit(ISSUER).netloc}": MockTransport(provider),
        # The least specific pattern, so only what the two above do not match.
        "all://": MockTransport(unreachable),
    }
    connect = AsyncClient.__init__

    def connected(self: AsyncClient, *args: Any, **kwargs: Any) -> None:
        # A client given mounts of its own fails here: nothing overrides the network.
        connect(self, *args, mounts=hosts, **kwargs)

    # Patched on the class every HTTP client here derives from, so Authlib's
    # clients are on the network too, built whenever and from whatever.
    monkeypatch.setattr(AsyncClient, "__init__", connected)


### The database


@async_fixture(scope="session", loop_scope="session")
async def db(request: FixtureRequest) -> AsyncGenerator[AsyncDatabase]:
    """The test database, emptied and set up once for the whole suite: one
    connection pool and one init_beanie, not one per test. Dropped at the
    end only if every test passed, so a failure's data is left to inspect."""
    try:
        async with mongo_db(MongoSettings()) as test_db:
            # Emptied before the models are bound, so no earlier run's
            # documents or indexes are left.
            await test_db.client.drop_database(test_db.name)
            await init_beanie_models(test_db)
            yield test_db
            if request.session.testsfailed == 0:
                await test_db.client.drop_database(test_db.name)
    except ServerSelectionTimeoutError:
        # One line and a stop, rather than the same error for every test.
        exit("MongoDB is not reachable at localhost:27017. Start it with `just up`.", 1)


@async_fixture(autouse=True, scope="function", loop_scope="session")
async def empty_db(db: AsyncDatabase) -> AsyncDatabase:
    """The test database, with every document an earlier test left deleted.
    Every test's app runs on it, as on the provider and the network; ask for
    it by name to read the database directly."""
    # Deleted, not dropped, so the indexes made at setup stay.
    for name in await db.list_collection_names(filter={"type": "collection"}):
        await db[name].delete_many({})
    return db


### Users & Sessions


@async_fixture(scope="function", loop_scope="session")
async def user() -> User:
    """The person `browser` is signed in as."""
    return await create_user("11111111-2222-3333-4444-555555555555")


@async_fixture(scope="function", loop_scope="session")
async def session(user: User) -> Session:
    """`user`'s session, which `browser` signs in with: made the way sign-in
    makes one, without the trip to the provider. It has a sid, as from a
    provider that issues one; a test of a provider that issues none clears it."""
    # The provider's id for this browser's session there, as a sid claim carries it.
    return await create_session(user, sid="provider-session-1")


### Browsers


@async_fixture(scope="function", loop_scope="session")
async def anon_browser() -> AsyncGenerator[Browser]:
    """A browser with no session."""
    async with Browser() as anon:
        yield anon


@async_fixture(scope="function", loop_scope="session")
async def browser(anon_browser: Browser, session: Session) -> Browser:
    """`anon_browser`, signed in with `session`'s cookie. Every domain route
    needs a user, so their tests use this and say nothing else about auth,
    while still exercising the cookie and the session lookup. The same
    browser as `anon_browser`: a test that needs a second makes its own."""
    anon_browser.session_cookie = session.cookie
    return anon_browser
