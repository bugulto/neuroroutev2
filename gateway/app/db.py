import os
import asyncpg

_pool = None


async def get_pool():
    global _pool

    if _pool is None:
        _pool = await asyncpg.create_pool(
            user=os.getenv("POSTGRES_USER"),
            password=os.getenv("POSTGRES_PASSWORD"),
            database=os.getenv("POSTGRES_DB"),
            host=os.getenv("POSTGRES_HOST", "postgres"),
            port=int(os.getenv("POSTGRES_PORT", "5432")),
            min_size=1,
            max_size=5,
        )

    return _pool


async def close_pool():
    global _pool

    if _pool is not None:
        await _pool.close()
        _pool = None