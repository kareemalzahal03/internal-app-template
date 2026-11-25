"""The dev command that resets the example's data to the demo data.

The reset runs on the suite's database here, not the dev one. It opens its
own connection and binds the models to it, as the app does at startup.
Binding is for the whole process, so afterwards the models are bound back
to the suite's database.
"""

from collections.abc import AsyncGenerator

from pymongo.asynchronous.database import AsyncDatabase
from pytest import mark
from pytest_asyncio import fixture as async_fixture

from app.core.auth import Session
from app.db import MongoSettings, init_beanie_models
from app.domain.seed import CLIENTS
from scripts.seed import main

pytestmark = mark.asyncio(loop_scope="session")


@async_fixture(loop_scope="session")
async def rebound(empty_db: AsyncDatabase) -> AsyncGenerator[AsyncDatabase]:
    """The suite's database, with the models bound back to it after the test."""
    yield empty_db
    await init_beanie_models(empty_db)


async def test_the_reset_replaces_the_example_data_and_keeps_sign_ins(
    rebound: AsyncDatabase, session: Session
) -> None:
    """Run twice, as a developer would: the second run finds the first's
    data, and still ends with one copy. Sessions are not the example's."""
    await main(MongoSettings())
    await main(MongoSettings())

    assert await rebound["clients"].count_documents({}) == len(CLIENTS)
    client_ids = {client["_id"] for client in await rebound["clients"].find().to_list()}
    order_clients = {order["client_id"] for order in await rebound["orders"].find().to_list()}
    assert order_clients and order_clients <= client_ids
    assert await rebound["sessions"].count_documents({"_id": session.id}) == 1
