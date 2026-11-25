"""Resets the dev database's example data to the demo data.

Only the example's collections are emptied; everything else is left as it
was.
"""

import asyncio

from app.db import MongoSettings, init_beanie_models, mongo_db
from app.domain import models
from app.domain.seed import seed


async def main(settings: MongoSettings) -> None:
    """Empties the example's collections in that database and seeds them."""
    async with mongo_db(settings) as db:
        await init_beanie_models(db)
        for model in models:
            await model.delete_all()
        print(f"emptied the example's collections in {db.name!r}")
        await seed()


if __name__ == "__main__":
    # Written here, not read from the environment, so a MONGODB_URL set in
    # the shell can never point the reset at another database.
    settings = MongoSettings(
        mongodb_url="mongodb://localhost:27017/?timeoutMS=1000&appName=devAppSeed",
        mongodb_db="appdb",
    )
    asyncio.run(main(settings))
