"""Covers: FR-10, FR-11, AG-9, AG-10, CP-3, CP-6, AT-14, AT-19."""
import json
import os

import pytest
import redis.asyncio as aioredis

from api.auth import persona_user
from assistant.store import make_deps
from common.llm import ProviderInfo
from common.llm.fake import FakeLLM
from tests.integration.api_client import as_user, build_state, client
from tests.integration.factories import create_version, make_ctx, run_pipeline, scalar

SEPSIS = (b"# Sepsis Screening and Escalation Protocol\n\n## Screening criteria\nScreen for sepsis when two or more "
          b"are present: temperature above 38.3 C, heart rate above 90, respiratory rate above 20, or new confusion.")


@pytest.fixture
async def api(pool, tmp_path):
    ctx = make_ctx(pool, tmp_path)
    _, vid = await create_version(ctx, SEPSIS, title="Sepsis Screening and Escalation Protocol",
                                  groups=("clinical",), category="Clinical Policy")
    await run_pipeline(ctx, vid)
    r = aioredis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    async with client(build_state(pool, r, tmp_path, llm_provider="fake", min_relevance=0.05)) as c:
        yield c
    await r.aclose()


async def chat(api, user, message, conversation_id=None):
    events = []
    async with api.stream("POST", "/api/chat", headers=as_user(user),
                          json={"message": message, "conversation_id": conversation_id}) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        event = None
        async for line in r.aiter_lines():
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                events.append((event, json.loads(line[6:])))
    return events


async def test_event_order_and_final(api, pool):
    events = await chat(api, "priya", "What are our sepsis screening criteria?")
    kinds = [e for e, _ in events]
    assert kinds[0] == "classification" and kinds[1] == "sources" and kinds[-1] == "final" and "token" in kinds
    final = events[-1][1]
    assert final["citations"][0]["title"] == "Sepsis Screening and Escalation Protocol"
    assert set(final["receipt"]) >= {"classification", "phi_redacted", "provider", "model", "external",
                                     "egress_decision", "passages_withheld", "checks", "fallback", "latency_ms"}
    assert await scalar(pool, "SELECT count(*) FROM audit_log WHERE action = 'chat.answered'") == 1


async def test_phi_redacted_in_storage(api, pool):
    events = await chat(api, "priya", "Patient John Smith MRN 00482913 — what are the sepsis screening criteria?")
    assert events[0][0] == "phi"
    stored = await scalar(pool, "SELECT string_agg(content_redacted, ' ') FROM messages")
    assert "00482913" not in stored and "[REDACTED-MRN]" in stored


async def test_history_and_delete_conversation(api):
    first = (await chat(api, "priya", "What are our sepsis screening criteria?"))[-1][1]
    cid = first["conversation_id"]
    await chat(api, "priya", "And the heart rate threshold?", cid)
    convo = (await api.get(f"/api/conversations/{cid}", headers=as_user("priya"))).json()
    assert len(convo["messages"]) == 4
    assert (await api.get(f"/api/conversations/{cid}", headers=as_user("sam"))).status_code == 404
    assert (await api.delete(f"/api/conversations/{cid}", headers=as_user("priya"))).status_code == 204
    assert (await api.get(f"/api/conversations/{cid}", headers=as_user("priya"))).status_code == 404


async def test_riley_gets_no_clinical_sources(api):
    final = (await chat(api, "riley", "What are the sepsis screening criteria?"))[-1][1]
    assert final["fallback"] == "no_sources" and final["citations"] == []


async def test_cache_invalidated_on_new_version(api, pool, tmp_path):
    await chat(api, "priya", "What are our sepsis screening criteria?")
    assert await scalar(pool, "SELECT count(*) FROM answer_cache") == 1
    ctx = make_ctx(pool, tmp_path)
    did = await scalar(pool, "SELECT document_id::text FROM documents")
    _, v2 = await create_version(ctx, SEPSIS + b" Recheck lactate within 2 hours.", document_id=did, version_number=2)
    await run_pipeline(ctx, v2)
    assert await scalar(pool, "SELECT count(*) FROM answer_cache") == 0


@pytest.mark.parametrize("change", ["classification", "access", "version"])
async def test_history_rechecks_current_source_permissions(api, pool, tmp_path, change):
    """Covers: CP-2, CR-6, CR-7. Previously stored answers cannot bypass current source controls."""
    cid = (await chat(api, "priya", "What are our sepsis screening criteria?"))[-1][1]["conversation_id"]
    external = FakeLLM()
    external.info = ProviderInfo("external", "openai_compatible", "", "model", "", True, False, True, "us")
    state = build_state(pool, None, tmp_path, llm=external, deployment_profile="hybrid")
    deps = make_deps(state)
    user = persona_user("priya")
    assert len(await deps.history(user, cid)) == 1
    if change == "classification":
        async with pool.connection() as conn:
            await conn.execute("UPDATE documents SET classification = 'restricted'")
    elif change == "access":
        async with pool.connection() as conn:
            await conn.execute("UPDATE document_acl SET group_name = 'pharmacy'")
    else:
        ctx = make_ctx(pool, tmp_path)
        did = await scalar(pool, "SELECT document_id::text FROM documents")
        _, v2 = await create_version(ctx, SEPSIS + b" Updated protocol.", document_id=did, version_number=2)
        await run_pipeline(ctx, v2)
    assert await deps.history(user, cid) == []
