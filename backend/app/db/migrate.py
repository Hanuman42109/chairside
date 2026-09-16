"""Minimal migration runner: applies numbered .sql files in app/db/migrations/
in order, tracking what's already run in a `schema_migrations` table.

No ORM/Alembic dependency -- migrations are plain SQL, which keeps the actual
schema fully visible and easy to review/copy into the Supabase SQL editor if
you'd rather run them by hand.

Usage:
    python -m app.db.migrate
"""

import asyncio
from pathlib import Path

import asyncpg

from app.config import get_settings

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


async def _ensure_migrations_table(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        create table if not exists schema_migrations (
            filename text primary key,
            applied_at timestamptz not null default now()
        );
        """
    )


async def run_migrations() -> None:
    settings = get_settings()
    conn = await asyncpg.connect(dsn=settings.database_url)
    try:
        await _ensure_migrations_table(conn)
        applied = {r["filename"] for r in await conn.fetch("select filename from schema_migrations")}

        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in applied:
                print(f"skip  {path.name} (already applied)")
                continue
            print(f"apply {path.name}")
            sql = path.read_text(encoding="utf-8")
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    "insert into schema_migrations (filename) values ($1)", path.name
                )
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(run_migrations())
