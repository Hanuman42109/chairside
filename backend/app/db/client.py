"""Async Postgres connection pool (Supabase Postgres, accessed directly via
DATABASE_URL rather than the Supabase REST API -- simpler for a backend that
already runs its own server and doesn't need PostgREST/row-level-security).
"""

import asyncpg

from app.config import get_settings

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = await asyncpg.create_pool(dsn=settings.database_url, min_size=1, max_size=5)
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
