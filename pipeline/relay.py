"""Relay: copies unpublished outbox rows into Redis Streams. At-least-once: a crash after XADD and before
commit re-sends the row, which consumers tolerate because every handler is idempotent."""
import asyncio
import contextlib
import json
import logging

from psycopg_pool import AsyncConnectionPool

from pipeline.streams import MAXLEN

log = logging.getLogger("distrirag.relay")

SELECT = ("SELECT id, stream, event_type, payload FROM outbox WHERE published_at IS NULL "
          "ORDER BY id LIMIT %s FOR UPDATE SKIP LOCKED")


async def relay_once(pool: AsyncConnectionPool, redis, batch: int = 100) -> int:
    try:
        async with pool.connection() as conn, conn.transaction():
            rows = await (await conn.execute(SELECT, (batch,))).fetchall()
            if not rows:
                return 0
            for row_id, stream, event_type, payload in rows:
                await redis.xadd(stream, {"event_id": str(row_id), "type": event_type, "payload": json.dumps(payload)},
                                 maxlen=MAXLEN, approximate=True)
            await conn.execute("UPDATE outbox SET published_at = now() WHERE id = ANY(%s)", ([r[0] for r in rows],))
            return len(rows)
    except Exception as error:
        async with pool.connection() as conn:
            await conn.execute(
                "UPDATE outbox SET attempts = attempts + 1, last_error = %s WHERE id IN "
                "(SELECT id FROM outbox WHERE published_at IS NULL ORDER BY id LIMIT %s)", (str(error)[:500], batch))
        raise


async def run(pool: AsyncConnectionPool, redis, stop: asyncio.Event, idle_poll: float = 1.0) -> None:
    backoff = 0.5
    while not stop.is_set():
        try:
            published = await relay_once(pool, redis)
            backoff = 0.5
        except Exception as error:  # Redis or Postgres down: keep rows, retry with backoff
            log.warning("relay error: %s; retrying in %.1fs", error, backoff)
            await _sleep(stop, backoff)
            backoff = min(backoff * 2, 10.0)
            continue
        if not published:
            await _sleep(stop, idle_poll)


async def _sleep(stop: asyncio.Event, seconds: float) -> None:
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=seconds)
