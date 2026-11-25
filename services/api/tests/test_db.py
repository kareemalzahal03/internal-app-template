"""Opening the database: startup only adds indexes. Dropping or changing
one is done by hand.

These tests bind the models to a scratch database, as startup binds them
to the app's. Binding is for the whole process, so afterwards they are
bound back to the suite's database.
"""

from collections.abc import AsyncGenerator

from pymongo import ASCENDING
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import OperationFailure
from pytest import mark, raises
from pytest_asyncio import fixture as async_fixture

from app.db import init_beanie_models

pytestmark = mark.asyncio(loop_scope="session")

SCRATCH = "appdb_test_scratch"
# A template collection, and one of its declared indexes: its sessions' expiry.
SESSIONS = "sessions"
DECLARED = "expires_at_1"


@async_fixture(loop_scope="session")
async def scratch(db: AsyncDatabase) -> AsyncGenerator[AsyncDatabase]:
    """An empty second database, on the suite's client."""
    await db.client.drop_database(SCRATCH)
    yield db.client[SCRATCH]
    await db.client.drop_database(SCRATCH)
    await init_beanie_models(db)


async def index_names(database: AsyncDatabase) -> set[str]:
    return set(await database[SESSIONS].index_information())


async def test_startup_creates_the_declared_indexes_and_drops_none(
    scratch: AsyncDatabase,
) -> None:
    """In a rolling deploy, an index only the other version declares stays."""
    await scratch[SESSIONS].create_index([("undeclared", ASCENDING)])

    await init_beanie_models(scratch)

    assert {DECLARED, "undeclared_1"} <= await index_names(scratch)


async def test_an_index_whose_options_changed_fails_startup(scratch: AsyncDatabase) -> None:
    """Same keys, other options: startup cannot create the declared one
    without dropping the old, so it stops rather than run without it."""
    await scratch[SESSIONS].create_index([("expires_at", ASCENDING)])

    with raises(OperationFailure, match="IndexOptionsConflict"):
        await init_beanie_models(scratch)
