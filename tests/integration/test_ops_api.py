"""Covers: UX-6, UX-7, UX-8, RL-8, CP-5, CP-7, AT-23, AT-24."""
import json
import os

import pytest
import redis.asyncio as aioredis

from pipeline import streams
from pipeline.outbox import enqueue
from pipeline.relay import relay_once
from tests.integration.api_client import as_user, build_state, client
from tests.integration.factories import create_version, make_ctx, run_pipeline, scalar


@pytest.fixture
async def redis():
    r = aioredis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    await r.flushall()
    await streams.ensure_groups(r)
    yield r
    await r.aclose()


@pytest.fixture
async def api(pool, redis, tmp_path):
    async with client(build_state(pool, redis, tmp_path)) as c:
        yield c


async def test_streams_endpoint_matches_redis(api, pool, redis):
    async with pool.connection() as conn:
        await enqueue(conn, streams.EXTRACT, "version.approved", "extract:a", {"version_id": "a"})
        await enqueue(conn, streams.EXTRACT, "version.approved", "extract:b", {"version_id": "b"})
    await relay_once(pool, redis)
    await redis.xreadgroup("extractors", "w-1", {streams.EXTRACT: ">"}, count=1)
    body = (await api.get("/api/ops/streams", headers=as_user("casey"))).json()
    extract = next(s for s in body["streams"] if s["stream"] == streams.EXTRACT)
    assert extract["length"] == 2 and extract["pending"] == 1 and extract["lag"] == 1
    assert extract["consumers"][0]["name"] == "w-1" and body["outbox_unpublished"] == 0
    assert (await api.get("/api/ops/streams", headers=as_user("sam"))).status_code == 403


async def test_events_since_and_board(api, pool, tmp_path):
    ctx = make_ctx(pool, tmp_path)
    _, vid = await create_version(ctx, b"# T\nText about gloves.")
    await run_pipeline(ctx, vid)
    events = (await api.get("/api/ops/events", params={"since": 0}, headers=as_user("casey"))).json()
    assert {"stage.started", "version.ready"} <= {e["kind"] for e in events}
    later = (await api.get("/api/ops/events", params={"since": events[-1]["id"]}, headers=as_user("casey"))).json()
    assert later == []
    board = (await api.get("/api/pipeline/board", headers=as_user("casey"))).json()
    assert board[0]["version_id"] == vid and board[0]["status"] == "READY" and "text" not in board[0]


async def test_pipeline_sse_emits_snapshot(api, pool, tmp_path):
    ctx = make_ctx(pool, tmp_path)
    await create_version(ctx, b"# T\nText.", status="QUEUED")
    lines = []
    async with api.stream("GET", "/api/pipeline/events", params={"max_seconds": 1},
                          headers=as_user("alex")) as r:
        async for line in r.aiter_lines():
            if line.startswith("data: "):
                lines.append(json.loads(line[6:]))
    assert lines and lines[0]["status"] == "QUEUED"


async def test_operator_cannot_read_text(api, pool, tmp_path):
    ctx = make_ctx(pool, tmp_path)
    _, vid = await create_version(ctx, b"# T\nSecret clinical text.")
    await run_pipeline(ctx, vid)
    assert (await api.get(f"/api/versions/{vid}/text", headers=as_user("casey"))).status_code == 404
    assert (await api.get("/api/search", params={"q": "secret clinical"}, headers=as_user("casey"))).json() == []


async def test_provider_outage_drill_sets_ttl(api, redis, pool):
    r = await api.post("/api/ops/drills/provider-outage", headers=as_user("casey"))
    assert r.status_code == 202 and 0 < await redis.ttl("drill:provider_outage") <= 30
    assert await scalar(pool, "SELECT count(*) FROM audit_log WHERE action = 'drill.run'") == 1


async def test_kill_worker_drill_arms_kill_switch(api, redis):
    assert (await api.post("/api/ops/drills/kill-worker", headers=as_user("casey"))).status_code == 202
    assert await redis.get("drill:kill") == streams.EMBED


async def test_poison_file_drill_creates_approved_upload(api, pool):
    assert (await api.post("/api/ops/drills/poison-file", headers=as_user("casey"))).status_code == 202
    assert await scalar(pool, "SELECT status FROM document_versions") == "QUEUED"
    assert await scalar(pool, "SELECT uploaded_by || '/' || approved_by FROM document_versions") == "alex/taylor"


async def test_unknown_drill_404_and_sam_forbidden(api):
    assert (await api.post("/api/ops/drills/nope", headers=as_user("casey"))).status_code == 404
    assert (await api.post("/api/ops/drills/kill-worker", headers=as_user("sam"))).status_code == 403


async def test_dead_letters_list_and_replay(api, pool, tmp_path):
    ctx = make_ctx(pool, tmp_path)
    _, vid = await create_version(ctx, b"# T\nText.", status="FAILED")
    async with pool.connection() as conn:
        await conn.execute("INSERT INTO dead_letters (stream, message_id, payload, deliveries) VALUES "
                           "(%s, '1-0', %s::jsonb, 5)",
                           (streams.EXTRACT, json.dumps({"type": "version.approved", "payload": {"version_id": vid}})))
    listed = (await api.get("/api/ops/dead-letters", headers=as_user("casey"))).json()
    assert listed[0]["deliveries"] == 5
    assert (await api.post(f"/api/ops/dead-letters/{listed[0]['id']}/replay",
                           headers=as_user("casey"))).status_code == 202
    assert await scalar(pool, "SELECT status FROM document_versions") == "QUEUED"


async def test_audit_filters_and_csv(api, pool):
    async with pool.connection() as conn:
        rows = [("alex", "document.uploaded"), ("taylor", "version.approved"), ("sam", "search.performed")]
        for actor, action in rows:
            await conn.execute("INSERT INTO audit_log (actor_id, action) VALUES (%s, %s)", (actor, action))
    page = (await api.get("/api/audit", params={"actor": "taylor"}, headers=as_user("taylor"))).json()
    assert [e["action"] for e in page["items"]] == ["version.approved"]
    csv = await api.get("/api/audit.csv", headers=as_user("taylor"))
    assert csv.headers["content-type"].startswith("text/csv") and "search.performed" in csv.text
    assert (await api.get("/api/audit", headers=as_user("alex"))).status_code == 403


async def test_deletion_receipt_listed(api, pool, tmp_path):
    from pipeline.stages.delete import handle_delete
    ctx = make_ctx(pool, tmp_path)
    did, vid = await create_version(ctx, b"# T\nText about visitors.")
    await run_pipeline(ctx, vid)
    await handle_delete(ctx, {"document_id": did, "requested_by": "taylor"})
    receipts = (await api.get("/api/deletions", headers=as_user("taylor"))).json()
    assert receipts[0]["detail"]["chunks"] >= 1 and receipts[0]["actor_id"] == "taylor"


async def test_version_preview_for_compliance(api, pool, tmp_path):
    ctx = make_ctx(pool, tmp_path)
    _, vid = await create_version(ctx, b"# Visitor Policy\nVisiting hours are 8 to 20.", status="PENDING_APPROVAL")
    r = await api.get(f"/api/versions/{vid}/preview", headers=as_user("taylor"))
    assert "Visiting hours" in r.json()["text"]
    assert (await api.get(f"/api/versions/{vid}/preview", headers=as_user("sam"))).status_code == 403
