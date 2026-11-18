"""Covers: DP-6, DP-7, RL-4, RL-7, RL-9 (all roles in one process; kill drill recovers)."""
import asyncio
import os

import pytest
import redis.asyncio as aioredis

import run
from pipeline import streams
from pipeline.outbox import enqueue
from tests.integration.api_client import build_state
from tests.integration.factories import create_version, make_ctx, scalar

LONG = ("# Fall Prevention\n\n" + "\n\n".join(f"## Step {i}\n" + "Keep the bed low and the call light in reach. " * 30
                                            for i in range(8))).encode()


@pytest.fixture
async def redis():
    r = aioredis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    await r.flushall()
    yield r
    await r.aclose()


async def wait_status(pool, vid, status, timeout=30):
    for _ in range(int(timeout / 0.2)):
        if await scalar(pool, "SELECT status FROM document_versions WHERE version_id=%s", (vid,)) == status:
            return True
        await asyncio.sleep(0.2)
    return False


async def approve(pool, vid):
    async with pool.connection() as conn:
        await enqueue(conn, streams.EXTRACT, "version.approved", f"extract:{vid}", {"version_id": vid})


async def test_run_mode_all_end_to_end(pool, redis, tmp_path):
    state = build_state(pool, redis, tmp_path, reclaim_base_idle_ms=300)
    _, vid = await create_version(make_ctx(pool, tmp_path), LONG)
    stop = asyncio.Event()
    tasks = await run.start_background(state, stop, embed_consumers=2)
    try:
        await approve(pool, vid)
        assert await wait_status(pool, vid, "READY")
    finally:
        stop.set()
        await asyncio.gather(*tasks, return_exceptions=True)
    total = await scalar(pool, "SELECT chunks_total FROM document_versions WHERE version_id=%s", (vid,))
    assert await scalar(pool, "SELECT count(*) FROM document_embeddings") == total


async def test_kill_drill_recovers_without_duplicates(pool, redis, tmp_path):
    state = build_state(pool, redis, tmp_path, reclaim_base_idle_ms=300)
    _, vid = await create_version(make_ctx(pool, tmp_path), LONG)
    await redis.set("drill:kill", streams.EMBED, ex=60)
    stop = asyncio.Event()
    tasks = await run.start_background(state, stop, embed_consumers=2)
    try:
        await approve(pool, vid)
        assert await wait_status(pool, vid, "READY")
    finally:
        stop.set()
        await asyncio.gather(*tasks, return_exceptions=True)
    assert await scalar(pool, "SELECT count(*) FROM ops_events WHERE kind = 'worker.killed'") == 1
    total = await scalar(pool, "SELECT chunks_total FROM document_versions WHERE version_id=%s", (vid,))
    assert await scalar(pool, "SELECT count(*) FROM document_chunks WHERE version_id=%s", (vid,)) == total
    assert await scalar(pool, "SELECT count(*) FROM document_embeddings") == total
