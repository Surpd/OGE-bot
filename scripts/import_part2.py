"""Import the bundled atlas into the explicitly configured database."""

import asyncio
import os

import asyncpg

from app.persistence.part2_bank import import_bank


async def main() -> None:
    connection = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        print(f"Imported {await import_bank(connection)} cards")
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
