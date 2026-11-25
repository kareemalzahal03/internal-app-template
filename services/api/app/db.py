"""How this app opens MongoDB and binds every Document to it."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from beanie import init_beanie
from fastapi import FastAPI
from pydantic_settings import BaseSettings
from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from app import core, domain


class MongoSettings(BaseSettings):
    """Where the database is, read from the environment."""

    # Connection string for the MongoDB deployment, with its driver options.
    mongodb_url: str
    # The database within that deployment this app reads and writes.
    mongodb_db: str


@asynccontextmanager
async def mongo_db(settings: MongoSettings) -> AsyncGenerator[AsyncDatabase]:
    """Opens client to MongoDB instance, yields DB, closes connection at end of scope."""
    # tz_aware: BSON datetimes come back naive otherwise, which cannot be
    # compared with an aware now() and serialise with no offset.
    async with AsyncMongoClient(settings.mongodb_url, tz_aware=True) as client:
        # The client connects lazily. Ping fails now if the server does not answer.
        await client.admin.command("ping")
        # Yield the DB this app works with.
        yield client.get_database(settings.mongodb_db)


async def init_beanie_models(db: AsyncDatabase) -> None:
    """Initialize Beanie with all document models."""
    # Binds every Document to this database, and has MongoDB create each
    # collection and declared index that does not exist yet. Drops none.
    await init_beanie(database=db, document_models=(*domain.models, *core.models))


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    """Binds every Document to the database."""
    async with mongo_db(MongoSettings()) as db:
        await init_beanie_models(db)
        yield
