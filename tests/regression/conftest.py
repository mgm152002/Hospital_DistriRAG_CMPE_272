"""Regression suite: one seeded stack per session (synthetic corpus v1 + v2, fake LLM, hashing embedder)."""

import asyncio
import os
import pathlib

import httpx
import pytest
import pytest_asyncio
import redis.asyncio as aioredis
import yaml

import run
from common.db import create_pool
from common.migrate import migrate
from tests.integration.api_client import build_state, client

ROOT = pathlib.Path(__file__).resolve().parents[2]
TYPES = {".md": "text/markdown", ".txt": "text/plain", ".pdf": "application/pdf"}


def pytest_collection_modifyitems(items):
    for item in items:
        if "regression" in str(item.fspath):
            item.add_marker(pytest.mark.regression)
            item.add_marker(pytest.mark.integration)


async def wait_ready(api: httpx.AsyncClient, version_ids: list[str], timeout: float = 120) -> None:
    for _ in range(int(timeout / 0.5)):
        statuses = [
            (await api.get(f"/api/versions/{v}/status", headers={"X-User-Id": "alex"})).json()["status"]
            for v in version_ids
        ]
        if all(s in ("READY", "FAILED") for s in statuses):
            assert all(s == "READY" for s in statuses), statuses
            return
        await asyncio.sleep(0.5)
    raise TimeoutError("corpus did not become READY")


async def seed(api: httpx.AsyncClient) -> dict[str, str]:
    """Upload v1 of every document as Alex, approve as Taylor; then the v2 updates. Returns title → document_id."""
    entries = yaml.safe_load((ROOT / "corpus" / "manifest.yaml").read_text())["documents"]
    ids: dict[str, str] = {}
    for wanted in (1, 2):
        versions = []
        for e in (x for x in entries if x["version"] == wanted):
            path = ROOT / "corpus" / e["file"]
            files = {"file": (path.name, path.read_bytes(), TYPES[path.suffix])}
            if wanted == 1:
                form = {k: e[k] for k in ("title", "category", "department", "classification")}
                form["groups"] = ",".join(e["groups"])
                r = await api.post("/api/documents", headers={"X-User-Id": "alex"}, data=form, files=files)
            else:
                r = await api.post(
                    f"/api/documents/{ids[e['title']]}/versions", headers={"X-User-Id": "alex"}, files=files
                )
            r.raise_for_status()
            ids.setdefault(e["title"], r.json()["document_id"])
            versions.append(r.json()["version_id"])
            await api.post(f"/api/versions/{r.json()['version_id']}/approve", headers={"X-User-Id": "taylor"}, json={})
        await wait_ready(api, versions)
    return ids


class Switchable:
    """Embedder whose failures can be switched on mid-run (workers capture the embedder when they start)."""

    def __init__(self, inner) -> None:
        self.inner, self.dim, self.broken = inner, inner.dim, False

    async def embed(self, texts):
        if self.broken:
            raise RuntimeError("provider down (test switch)")
        return await self.inner.embed(texts)


class Seeded:
    def __init__(self, api, state, pool, redis, ids, embedder):
        self.api, self.state, self.pool, self.redis, self.ids, self.embedder = api, state, pool, redis, ids, embedder


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def seeded(tmp_path_factory):
    import psycopg

    url = os.environ["DATABASE_URL"]
    async with await psycopg.AsyncConnection.connect(url, autocommit=True) as conn:
        await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    await migrate(url)
    pool = await create_pool(url, max_size=10)
    redis = aioredis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    await redis.flushall()
    state = build_state(
        pool,
        redis,
        tmp_path_factory.mktemp("blobs"),
        llm_provider="fake",
        phi_mode="redact",  # the eval corpora expect identifiers removed and the question still answered
        reclaim_base_idle_ms=300,
        stuck_after_seconds=2,
    )
    embedder = Switchable(state.embedder)
    state.embedder = embedder
    stop = asyncio.Event()
    tasks = await run.start_background(state, stop, embed_consumers=2)
    async with client(state) as api:
        ids = await seed(api)
        yield Seeded(api, state, pool, redis, ids, embedder)
    stop.set()
    await asyncio.gather(*tasks, return_exceptions=True)
    await redis.aclose()
    await pool.close()
