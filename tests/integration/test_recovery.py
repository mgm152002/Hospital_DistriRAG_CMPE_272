"""Covers: RL-5, RL-7, RL-8, RL-9, CP-6."""
import asyncio
import os

import pytest
import redis.asyncio as aioredis

from pipeline import recovery, streams
from pipeline.consumer import Consumer
from pipeline.outbox import enqueue
from pipeline.relay import relay_once
from pipeline.stages import extract
from tests.integration.factories import create_version, make_ctx, run_pipeline, scalar

BASE = 200  # ms; production uses 60 000


@pytest.fixture
async def redis():
    r = aioredis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    await r.flushall()
    await streams.ensure_groups(r)
    yield r
    await r.aclose()


def consumer(ctx, handler, stream=streams.EXTRACT, event="version.approved"):
    ctx.settings.reclaim_base_idle_ms = BASE
    return Consumer(ctx, stream, streams.GROUPS[stream], {event: handler},
                    reclaimer=recovery.make_reclaimer(BASE, ctx.settings.max_deliveries))


async def publish(pool, redis, key="extract:x", payload=None, stream=streams.EXTRACT, event="version.approved"):
    async with pool.connection() as conn:
        await enqueue(conn, stream, event, key, payload or {"version_id": "x"})
    await relay_once(pool, redis)


async def test_reclaim_after_consumer_dies(pool, redis, tmp_path):
    await publish(pool, redis)
    dead = make_ctx(pool, tmp_path, redis, name="w-dead")
    await redis.xreadgroup(streams.GROUPS[streams.EXTRACT], dead.consumer_name, {streams.EXTRACT: ">"}, count=1)
    seen = []

    async def handler(ctx, payload):
        seen.append(ctx.consumer_name)
    alive = consumer(make_ctx(pool, tmp_path, redis, name="w-alive"), handler)
    assert await alive.step(block_ms=10) is False or seen == []  # not idle long enough yet
    await asyncio.sleep(BASE / 1000 + 0.1)
    await alive.step(block_ms=10)
    assert seen == ["w-alive"]
    assert (await redis.xpending(streams.EXTRACT, streams.GROUPS[streams.EXTRACT]))["pending"] == 0
    assert await scalar(pool, "SELECT count(*) FROM ops_events WHERE kind = 'message.reclaimed'") == 1


async def test_dead_letter_after_max_deliveries_marks_failed(pool, redis, tmp_path):
    ctx = make_ctx(pool, tmp_path, redis)
    _, vid = await create_version(ctx, b"# T\nSome text here.")
    await publish(pool, redis, key=f"extract:{vid}", payload={"version_id": vid})

    async def always_fails(ctx, payload):
        raise RuntimeError("provider down")
    c = consumer(ctx, always_fails)
    for _ in range(40):
        await c.step(block_ms=10)
        await recovery.dead_letter(ctx, streams.EXTRACT, streams.GROUPS[streams.EXTRACT], 5, BASE)
        if await scalar(pool, "SELECT count(*) FROM dead_letters"):
            break
        await asyncio.sleep(0.15)
    assert await scalar(pool, "SELECT deliveries FROM dead_letters") == 5
    assert await scalar(pool, "SELECT error_code FROM document_versions WHERE version_id=%s",
                        (vid,)) == "max_retries_exceeded"
    assert await redis.xlen(streams.dlq(streams.EXTRACT)) == 1
    assert (await redis.xpending(streams.EXTRACT, streams.GROUPS[streams.EXTRACT]))["pending"] == 0


async def test_replay_reaches_ready(pool, redis, tmp_path):
    ctx = make_ctx(pool, tmp_path, redis)
    _, vid = await create_version(ctx, b"# T\nSome text about gloves and gowns.")
    async with pool.connection() as conn:
        await conn.execute("UPDATE document_versions SET status='FAILED', error_code='max_retries_exceeded' "
                           "WHERE version_id=%s", (vid,))
        await conn.execute("INSERT INTO dead_letters (stream, message_id, payload, deliveries) VALUES "
                           "(%s, '1-0', %s::jsonb, 5)",
                           (streams.EXTRACT, f'{{"type": "version.approved", "payload": {{"version_id": "{vid}"}}}}'))
    dl_id = await scalar(pool, "SELECT id FROM dead_letters")
    await recovery.replay_dead_letter(pool, dl_id, "casey")
    assert await scalar(pool, "SELECT status FROM document_versions WHERE version_id=%s", (vid,)) == "QUEUED"
    await run_pipeline(ctx, vid)
    assert await scalar(pool, "SELECT status FROM document_versions WHERE version_id=%s", (vid,)) == "READY"


async def test_redrive_after_flushall(pool, redis, tmp_path):
    ctx = make_ctx(pool, tmp_path, redis)
    _, vid = await create_version(ctx, ("# T\n" + "Gloves and gowns. " * 200).encode())
    await extract.handle_approved(ctx, {"version_id": vid})
    await relay_once(pool, redis)          # batch events published...
    await redis.flushall()                 # ...then Redis loses everything
    await streams.ensure_groups(redis)
    async with pool.connection() as conn:
        await conn.execute("UPDATE document_versions SET updated_at = now() - interval '1 hour' WHERE version_id=%s",
                           (vid,))
    assert await recovery.redrive_stuck(pool, redis, stuck_after_s=60) == 1
    await relay_once(pool, redis)
    assert await redis.xlen(streams.EMBED) >= 1
    assert await recovery.redrive_stuck(pool, redis, stuck_after_s=60) == 0  # touched: not stuck any more


async def test_retention_removes_only_expired(pool, tmp_path):
    async with pool.connection() as conn:
        for offset in ("- interval '1 day'", "+ interval '1 day'"):
            await conn.execute(f"INSERT INTO conversations VALUES (gen_random_uuid(), 'sam', now(), now() {offset})")
        await conn.execute("INSERT INTO audit_log (actor_id, action, created_at) VALUES "
                           "('x', 'old', now() - interval '400 days'), ('x', 'new', now())")
    ctx = make_ctx(pool, tmp_path)
    counts = await recovery.purge_retention(pool, ctx.settings)
    assert counts["conversations"] == 1 and counts["audit"] == 1
    assert await scalar(pool, "SELECT count(*) FROM conversations") == 1
    assert await scalar(pool, "SELECT count(*) FROM audit_log WHERE action = 'old'") == 0
    assert await scalar(pool, "SELECT count(*) FROM audit_log WHERE action = 'retention.purged'") == 1


async def test_orphan_blob_removed(pool, tmp_path):
    ctx = make_ctx(pool, tmp_path)
    did, vid = await create_version(ctx, b"# kept\nText.")
    await ctx.blobs.put("originals/orphan-doc/orphan-ver/x.md", b"x", "text/markdown")
    assert await recovery.purge_orphan_blobs(pool, ctx.blobs, older_than_s=0) == 1
    assert await ctx.blobs.exists(f"originals/{did}/{vid}/policy.md")
