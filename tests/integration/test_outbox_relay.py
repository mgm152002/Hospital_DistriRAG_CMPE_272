"""Covers: RL-2, RL-3, RL-4."""
import asyncio
import json
import os
import time

import pytest
import redis.asyncio as aioredis
import redis.exceptions as redis_errors

from pipeline import streams
from pipeline.consumer import Consumer, Ctx
from pipeline.outbox import enqueue
from pipeline.relay import relay_once


@pytest.fixture
async def redis():
    r = aioredis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    await r.flushall()
    yield r
    await r.aclose()


async def test_rollback_leaves_no_outbox_row(pool):
    async with pool.connection() as conn:
        with pytest.raises(RuntimeError):
            async with conn.transaction():
                await enqueue(conn, streams.EXTRACT, "version.approved", "extract:a", {"version_id": "a"})
                raise RuntimeError("boom")
        assert (await (await conn.execute("SELECT count(*) FROM outbox")).fetchone())[0] == 0


async def test_dedupe_key_single_row(pool):
    async with pool.connection() as conn:
        for _ in range(2):
            await enqueue(conn, streams.EXTRACT, "version.approved", "extract:a", {"version_id": "a"})
        assert (await (await conn.execute("SELECT count(*) FROM outbox")).fetchone())[0] == 1


async def test_relay_publishes_500_rows_under_5s(pool, redis):
    async with pool.connection() as conn, conn.transaction():
        for i in range(500):
            await enqueue(conn, streams.EMBED, "batch.ready", f"embed:x:{i}", {"version_id": "x", "batch_no": i})
    started = time.perf_counter()
    total = 0
    while total < 500:
        total += await relay_once(pool, redis)
    assert time.perf_counter() - started < 5
    assert await redis.xlen(streams.EMBED) == 500
    first = (await redis.xrange(streams.EMBED, count=1))[0][1]
    assert first["type"] == "batch.ready" and json.loads(first["payload"])["batch_no"] == 0


async def test_relay_holds_rows_while_redis_down(pool):
    dead = aioredis.from_url("redis://127.0.0.1:1/0", decode_responses=True, socket_connect_timeout=0.2)
    async with pool.connection() as conn:
        await enqueue(conn, streams.EXTRACT, "version.approved", "extract:z", {"version_id": "z"})
    with pytest.raises(redis_errors.ConnectionError):
        await relay_once(pool, dead)
    async with pool.connection() as conn:
        row = await (await conn.execute("SELECT published_at, attempts, last_error FROM outbox")).fetchone()
    assert row[0] is None and row[1] == 1 and row[2]


async def test_two_relays_no_double_publish_in_same_pass(pool, redis):
    async with pool.connection() as conn, conn.transaction():
        for i in range(200):
            await enqueue(conn, streams.EMBED, "batch.ready", f"embed:y:{i}", {"batch_no": i})
    counts = await asyncio.gather(relay_once(pool, redis, batch=200), relay_once(pool, redis, batch=200))
    assert sum(counts) == 200 and await redis.xlen(streams.EMBED) == 200


async def test_consumer_reads_and_acks(pool, redis):
    await streams.ensure_groups(redis)
    seen = []

    async def handler(ctx, payload):
        seen.append(payload["version_id"])
    async with pool.connection() as conn:
        await enqueue(conn, streams.EXTRACT, "version.approved", "extract:q", {"version_id": "q"})
    await relay_once(pool, redis)
    ctx = Ctx(pool=pool, redis=redis, blobs=None, embedder=None, settings=None, consumer_name="w1")
    consumer = Consumer(ctx, streams.EXTRACT, streams.GROUPS[streams.EXTRACT], {"version.approved": handler})
    assert await consumer.step(block_ms=500) is True
    assert seen == ["q"]
    pending = await redis.xpending(streams.EXTRACT, streams.GROUPS[streams.EXTRACT])
    assert pending["pending"] == 0
