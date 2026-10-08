"""Covers: FR-1, FR-2, FR-3, CP-1, FR-4, FR-5, FR-6, FR-7, FR-12, FR-13, CR-5, CP-5, AT-01, AT-02, AT-03, AT-09."""
import asyncio
import os

import psycopg
import pytest
import redis.asyncio as aioredis

from tests.integration.api_client import as_user, build_state, client, upload_form
from tests.integration.factories import scalar

MD = b"# Hand Hygiene\n\n## Procedure\nRub hands for 20 to 30 seconds with alcohol-based rub."


@pytest.fixture
async def redis():
    r = aioredis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    await r.flushall()
    yield r
    await r.aclose()


@pytest.fixture
async def api(pool, redis, tmp_path):
    async with client(build_state(pool, redis, tmp_path)) as c:
        yield c


async def upload(api, user="alex", data=MD, name="hand.md", key=None, **form):
    headers = as_user(user, **({"Idempotency-Key": key} if key else {}))
    return await api.post("/api/documents", headers=headers, data=upload_form(**form),
                          files={"file": (name, data, "text/markdown")})


async def test_upload_creates_pending_with_audit(api, pool):
    r = await upload(api)
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "PENDING_APPROVAL" and body["version_number"] == 1
    assert await scalar(pool, "SELECT count(*) FROM audit_log WHERE action='document.uploaded'") == 1
    assert await scalar(pool, "SELECT count(*) FROM outbox") == 0


async def test_nurse_cannot_upload(api):
    assert (await upload(api, user="sam")).status_code == 403


async def test_unknown_user_is_401(api):
    assert (await api.get("/api/documents", headers=as_user("mallory"))).status_code == 401


async def test_reject_bad_metadata(api):
    assert (await upload(api, category="Astrology")).status_code == 422
    bad_class = await upload(api, classification="top-secret")
    assert bad_class.status_code == 422 and bad_class.json()["error_code"] == "invalid_classification"
    assert (await upload(api, groups="all-staff,hackers")).status_code == 422
    assert (await upload(api, data=b"\x00bin", name="x.md")).json()["error_code"] == "invalid_encoding"


async def test_idempotent_upload_replay_and_conflict(api, pool):
    first = await upload(api, key="k-1")
    second = await upload(api, key="k-1")
    assert second.json() == first.json() and second.headers["Idempotent-Replay"] == "true"
    assert await scalar(pool, "SELECT count(*) FROM document_versions") == 1
    assert (await upload(api, key="k-1", data=b"# Other\ntext")).status_code == 409


async def test_new_version_increments(api):
    doc = (await upload(api)).json()
    r = await api.post(f"/api/documents/{doc['document_id']}/versions", headers=as_user("alex"),
                       files={"file": ("hand-v2.md", MD + b" Updated.", "text/markdown")})
    assert r.status_code == 202 and r.json()["version_number"] == 2


async def test_self_approval_forbidden_and_double_approval(api, pool):
    doc = (await upload(api)).json()
    vid = doc["version_id"]
    r = await api.post(f"/api/versions/{vid}/approve", headers=as_user("alex"), json={})
    assert r.status_code == 403
    r = await api.post(f"/api/versions/{vid}/approve", headers=as_user("taylor"), json={"comment": "ok"})
    assert r.status_code == 202 and r.json()["status"] == "QUEUED"
    assert await scalar(pool, "SELECT count(*) FROM outbox WHERE event_type='version.approved'") == 1
    again = await api.post(f"/api/versions/{vid}/approve", headers=as_user("taylor"), json={})
    assert again.status_code == 409


async def test_concurrent_approvals_one_wins(api, pool):
    vid = (await upload(api)).json()["version_id"]
    results = await asyncio.gather(*(api.post(f"/api/versions/{vid}/approve", headers=as_user("taylor"), json={})
                                     for _ in range(2)))
    assert sorted(r.status_code for r in results) == [202, 409]
    assert await scalar(pool, "SELECT count(*) FROM outbox") == 1


async def test_reject_requires_reason(api):
    vid = (await upload(api)).json()["version_id"]
    assert (await api.post(f"/api/versions/{vid}/reject", headers=as_user("taylor"), json={})).status_code == 422
    r = await api.post(f"/api/versions/{vid}/reject", headers=as_user("taylor"), json={"reason": "Outdated"})
    assert r.json()["status"] == "REJECTED"


async def test_approve_succeeds_with_redis_down(pool, tmp_path):
    """Review Focus 3: approving only writes the outbox, so Redis being down does not matter."""
    dead = aioredis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.2)
    async with client(build_state(pool, dead, tmp_path)) as api:
        vid = (await upload(api)).json()["version_id"]
        assert (await api.post(f"/api/versions/{vid}/approve", headers=as_user("taylor"), json={})).status_code == 202


async def test_db_down_returns_503(pool, redis, tmp_path):
    state = build_state(pool, redis, tmp_path)

    class DownPool:
        def connection(self):
            raise psycopg.OperationalError("connection refused")
    state.pool = DownPool()
    async with client(state) as api:
        r = await api.get("/api/documents", headers=as_user("sam"))
    assert r.status_code == 503 and r.json()["error_code"] == "db_unavailable"


async def test_non_reader_gets_404(api):
    doc = (await upload(api, groups="pharmacy", classification="restricted")).json()
    assert (await api.get(f"/api/documents/{doc['document_id']}", headers=as_user("riley"))).status_code == 404
    assert (await api.get(f"/api/documents/{doc['document_id']}", headers=as_user("jordan"))).status_code == 200
    listed = (await api.get("/api/documents", headers=as_user("riley"))).json()
    assert listed == []


async def test_status_reports_progress(api, pool):
    vid = (await upload(api)).json()["version_id"]
    async with pool.connection() as conn:
        await conn.execute("UPDATE document_versions SET status='PROCESSING', stage='EMBED', chunks_total=40, "
                           "chunks_embedded=24 WHERE version_id=%s", (vid,))
    r = await api.get(f"/api/versions/{vid}/status", headers=as_user("alex"))
    assert r.json() | {"stage": "EMBED", "chunks_total": 40, "chunks_embedded": 24} == r.json()
    assert (await api.get(f"/api/versions/{vid}/status", headers=as_user("sam"))).status_code == 403


async def test_retire_hides_from_listing(api):
    doc = (await upload(api)).json()
    assert (await api.post(f"/api/documents/{doc['document_id']}/retire", headers=as_user("alex"))).status_code == 200
    assert (await api.get("/api/documents", headers=as_user("sam"))).json() == []


async def test_delete_requires_compliance_and_enqueues(api, pool):
    doc = (await upload(api)).json()
    assert (await api.delete(f"/api/documents/{doc['document_id']}", headers=as_user("alex"))).status_code == 403
    assert (await api.delete(f"/api/documents/{doc['document_id']}", headers=as_user("taylor"))).status_code == 202
    assert await scalar(pool, "SELECT count(*) FROM outbox WHERE event_type='document.delete'") == 1


async def test_me_and_health(api):
    me = (await api.get("/api/me", headers=as_user("jordan"))).json()
    assert me["user_id"] == "jordan" and "pharmacy" in me["groups"] and me["profile"] == "lite"
    assert me["department"] == "Pharmacy"
    assert me["hospital"] == {"name": "Riverside General Hospital", "code": "RGH-001", "campus": "Main campus"}
    assert (await api.get("/api/auth/config")).json()["hospital"] == me["hospital"]
    assert (await api.get("/healthz")).status_code == 200
    assert (await api.get("/readyz")).status_code == 200
    personas = (await api.get("/api/personas")).json()
    assert len(personas) == 7
