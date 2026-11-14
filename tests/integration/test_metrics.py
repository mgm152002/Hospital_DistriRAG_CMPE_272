"""Covers: E11-1."""
import os

import redis.asyncio as aioredis

from common import metrics
from tests.integration.api_client import as_user, build_state, client


async def test_metrics_exposed_and_gauges_refresh(pool, tmp_path):
    r = aioredis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    state = build_state(pool, r, tmp_path)
    await metrics.refresh_gauges(state)
    async with client(state) as api:
        body = (await api.get("/metrics")).text
        assert "outbox_unpublished" in body and "messages_processed_total" in body
        await api.post("/api/chat", headers=as_user("sam"), json={"message": "Write me a poem"})
        assert "guardrail_blocks_total" in (await api.get("/metrics")).text
    await r.aclose()


async def test_readyz_503_when_redis_down(pool, tmp_path):
    dead = aioredis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.2)
    async with client(build_state(pool, dead, tmp_path)) as api:
        r = await api.get("/readyz")
    assert r.status_code == 503 and r.json()["redis"] is False
