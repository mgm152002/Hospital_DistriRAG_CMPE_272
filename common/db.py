from collections.abc import Sequence

from psycopg_pool import AsyncConnectionPool


async def create_pool(url: str, min_size: int = 1, max_size: int = 5) -> AsyncConnectionPool:
    pool = AsyncConnectionPool(url, min_size=min_size, max_size=max_size, open=False,
                               kwargs={"autocommit": True})
    await pool.open(wait=True, timeout=30)
    return pool


def vector_literal(vector: Sequence[float]) -> str:
    return "[" + ",".join(f"{v:.6f}" for v in vector) + "]"
