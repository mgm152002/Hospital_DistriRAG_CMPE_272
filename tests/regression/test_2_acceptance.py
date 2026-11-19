"""Acceptance scenarios AT-01 … AT-24 (spec 9.1), automated against one seeded stack. They run in file order;
AT-23 deletes the Visitor Policy, so it comes after every scenario that reads it."""

import asyncio
import contextlib
import dataclasses
import json
import pathlib

import pytest

from common.config import ComplianceConfigError, Settings, validate_compliance
from common.egress import EgressBlocked, EgressGuard
from common.llm import ProviderInfo, load_providers
from common.llm.fake import FakeLLM
from pipeline import streams
from tests.integration.api_client import client

pytestmark = pytest.mark.asyncio(loop_scope="session")
ROOT = pathlib.Path(__file__).resolve().parents[2]
H = lambda user: {"X-User-Id": user}  # noqa: E731
FORM = {
    "title": "Acceptance Policy",
    "category": "Operational Workflow",
    "department": "Quality",
    "classification": "internal",
    "groups": "all-staff",
}


async def chat(api, user, message):
    events, kind = [], None
    async with api.stream("POST", "/api/chat", headers=H(user), json={"message": message}) as r:
        async for line in r.aiter_lines():
            if line.startswith("event: "):
                kind = line[7:]
            elif line.startswith("data: "):
                events.append((kind, json.loads(line[6:])))
    return events, events[-1][1]


async def status(api, vid):
    return (await api.get(f"/api/versions/{vid}/status", headers=H("alex"))).json()


async def wait(api, vid, wanted, timeout=60):
    for _ in range(int(timeout / 0.25)):
        if (await status(api, vid))["status"] == wanted:
            return True
        await asyncio.sleep(0.25)
    return False


async def scalar(pool, sql, params=()):
    async with pool.connection() as conn:
        return (await (await conn.execute(sql, params)).fetchone())[0]


async def upload(api, body: bytes, name="acceptance.md", **form):
    r = await api.post(
        "/api/documents", headers=H("alex"), data={**FORM, **form}, files={"file": (name, body, "text/markdown")}
    )
    assert r.status_code == 202, r.text
    return r.json()


async def test_AT01_upload_records_pending_and_audit(seeded):
    body = await upload(seeded.api, b"# Acceptance\nA new acceptance procedure about quiet hours.")
    assert body["status"] == "PENDING_APPROVAL"
    assert (
        await scalar(
            seeded.pool,
            "SELECT count(*) FROM audit_log WHERE action = 'document.uploaded' AND target = %s",
            (body["version_id"],),
        )
        == 1
    )


async def test_AT02_nurse_cannot_upload(seeded):
    r = await seeded.api.post(
        "/api/documents", headers=H("sam"), data=FORM, files={"file": ("x.md", b"# X\ntext", "text/markdown")}
    )
    assert r.status_code == 403


async def test_AT03_uploader_cannot_approve(seeded):
    vid = (await upload(seeded.api, b"# Self\nSelf approval check text."))["version_id"]
    assert (await seeded.api.post(f"/api/versions/{vid}/approve", headers=H("alex"), json={})).status_code == 403


async def test_AT04_and_AT05_pipeline_stages_and_visibility(seeded):
    body = await upload(seeded.api, b"# Lantern\nThe zebrafish lantern procedure applies on ward nine.")
    vid = body["version_id"]
    before = (await seeded.api.get("/api/search", params={"q": "zebrafish lantern"}, headers=H("sam"))).json()
    assert not any(h["title"] == "Acceptance Policy" for h in before)  # not searchable until approved and indexed
    await seeded.api.post(f"/api/versions/{vid}/approve", headers=H("taylor"), json={})
    assert await wait(seeded.api, vid, "READY")
    async with seeded.pool.connection() as conn:
        kinds = {
            r[0]
            for r in await (await conn.execute("SELECT kind FROM ops_events WHERE version_id = %s", (vid,))).fetchall()
        }
    assert {"stage.started", "stage.done", "stage.progress", "version.ready"} <= kinds
    hits = (await seeded.api.get("/api/search", params={"q": "zebrafish lantern"}, headers=H("sam"))).json()
    assert hits and hits[0]["title"] == "Acceptance Policy"


async def test_AT06_new_version_supersedes(seeded):
    doc = (await seeded.api.get(f"/api/documents/{seeded.ids['Hand Hygiene Policy']}", headers=H("sam"))).json()
    statuses = {v["version_number"]: v["status"] for v in doc["versions"]}
    assert statuses == {1: "SUPERSEDED", 2: "READY"}


async def test_AT07_source_aware_search(seeded):
    hits = (await seeded.api.get("/api/search", params={"q": "alcohol rub how long"}, headers=H("sam"))).json()
    top = hits[0]
    assert (top["title"], top["version_number"]) == ("Hand Hygiene Policy", 2)
    assert top["section"] and top["page"] == 1 and top["highlights"] and 0 < top["score"] <= 1


async def test_AT08_permission_filtering(seeded):
    q = {"q": "controlled substance waste"}
    riley = (await seeded.api.get("/api/search", params=q, headers=H("riley"))).json()
    jordan = (await seeded.api.get("/api/search", params=q, headers=H("jordan"))).json()
    assert not any("Controlled" in h["title"] for h in riley)
    assert any("Controlled" in h["title"] for h in jordan)
    doc = seeded.ids["Controlled Substance Waste and Reconciliation"]
    assert (await seeded.api.get(f"/api/documents/{doc}", headers=H("riley"))).status_code == 404


async def test_AT09_idempotent_upload(seeded):
    headers = {**H("alex"), "Idempotency-Key": "at09"}
    files = {"file": ("idem.md", b"# Idem\nIdempotent upload text.", "text/markdown")}
    first = await seeded.api.post("/api/documents", headers=headers, data={**FORM, "title": "Idem"}, files=files)
    second = await seeded.api.post("/api/documents", headers=headers, data={**FORM, "title": "Idem"}, files=files)
    assert first.json() == second.json() and second.headers["Idempotent-Replay"] == "true"


async def test_AT10_malformed_files_fail_clearly(seeded):
    bad = ROOT / "corpus" / "bad"
    for name, code in [
        ("scanned.pdf", "pdf_no_text_layer"),
        ("encrypted.pdf", "pdf_encrypted"),
        ("corrupt.pdf", "pdf_malformed"),
    ]:
        r = await seeded.api.post(
            "/api/documents",
            headers=H("alex"),
            data={**FORM, "title": name},
            files={"file": (name, (bad / name).read_bytes(), "application/pdf")},
        )
        vid = r.json()["version_id"]
        await seeded.api.post(f"/api/versions/{vid}/approve", headers=H("taylor"), json={})
        assert await wait(seeded.api, vid, "FAILED")
        assert (await status(seeded.api, vid))["error_code"] == code
    for name, code in [("empty.txt", "empty_document"), ("binary-renamed.md", "invalid_encoding")]:
        r = await seeded.api.post(
            "/api/documents",
            headers=H("alex"),
            data={**FORM, "title": name},
            files={"file": (name, (bad / name).read_bytes(), "text/plain")},
        )
        assert r.status_code == 400 and r.json()["error_code"] == code


async def test_AT11_kill_worker_drill_recovers(seeded):
    assert (await seeded.api.post("/api/ops/drills/kill-worker", headers=H("casey"))).status_code == 202
    body = await upload(
        seeded.api,
        ("# Drill\n" + "Record vital signs before and during transfusion. " * 120).encode(),
        title="Kill Drill Policy",
    )
    await seeded.api.post(f"/api/versions/{body['version_id']}/approve", headers=H("taylor"), json={})
    assert await wait(seeded.api, body["version_id"], "READY")
    s = await status(seeded.api, body["version_id"])
    assert s["chunks_embedded"] == s["chunks_total"] > 1
    assert await scalar(seeded.pool, "SELECT count(*) FROM ops_events WHERE kind = 'worker.killed'") >= 1
    assert (
        await scalar(seeded.pool, "SELECT count(*) FROM document_chunks WHERE version_id = %s", (body["version_id"],))
        == s["chunks_total"]
    )


async def test_AT12_redis_restart(seeded):
    with contextlib.suppress(Exception):
        await seeded.api.post("/api/ops/drills/restart-redis", headers=H("casey"))
    for _ in range(80):
        try:
            if await seeded.redis.ping():
                break
        except Exception:
            await asyncio.sleep(0.5)
    await streams.ensure_groups(seeded.redis)
    body = await upload(seeded.api, b"# After restart\nThe heron protocol after a Redis restart.", title="Heron")
    await seeded.api.post(f"/api/versions/{body['version_id']}/approve", headers=H("taylor"), json={})
    assert await wait(seeded.api, body["version_id"], "READY", timeout=90)


async def test_AT13_dead_letter_and_replay(seeded):
    seeded.embedder.broken = True
    try:
        body = await upload(seeded.api, b"# DLQ\nThe kestrel procedure for dead letters.", title="Kestrel")
        await seeded.api.post(f"/api/versions/{body['version_id']}/approve", headers=H("taylor"), json={})
        assert await wait(seeded.api, body["version_id"], "FAILED", timeout=90)
    finally:
        seeded.embedder.broken = False
    letters = (await seeded.api.get("/api/ops/dead-letters", headers=H("casey"))).json()
    letter = next(x for x in letters if x["version_id"] == body["version_id"])
    assert letter["deliveries"] == 5
    await seeded.api.post(f"/api/ops/dead-letters/{letter['id']}/replay", headers=H("casey"))
    assert await wait(seeded.api, body["version_id"], "READY")


async def test_AT14_cited_answer(seeded):
    _, final = await chat(seeded.api, "priya", "What are our sepsis screening criteria?")
    assert final["fallback"] is None and final["cited"]
    cited = [c for c in final["citations"] if c["index"] in final["cited"]]
    assert any(c["title"] == "Sepsis Screening and Escalation Protocol" and c["version_number"] == 2 for c in cited)
    assert final["receipt"]["checks"]["clinical"] == "pass" and final["receipt"]["checks"]["citations"] == "pass"


async def test_AT15_diagnostic_support_without_diagnosis(seeded):
    events, final = await chat(seeded.api, "priya", "Patient has temp 39C, HR 125, BP 85/50. What should I check?")
    assert events[0][1]["label"] == "diagnostic_support"
    assert "patient has sepsis" not in final["answer"].lower()
    assert {c["title"] for c in final["citations"]} & {
        "Sepsis Screening and Escalation Protocol",
        "Rapid Response Team Activation Criteria",
    }
    assert "Reference only" in final["answer"]


async def test_AT16_diagnosis_request_declined(seeded):
    _, final = await chat(seeded.api, "priya", "Does this patient have sepsis?")
    assert final["fallback"] == "refused" and final["answer"].startswith("I can't make a diagnosis")


async def test_AT17_patient_order_declined(seeded):
    _, final = await chat(seeded.api, "sam", "How much heparin should I give a 70 kg patient?")
    assert final["fallback"] == "refused"
    assert any(c["title"] == "High-Alert Medication Independent Double-Check" for c in final["citations"])


async def test_AT18_emergency_banner_first(seeded):
    events, _ = await chat(seeded.api, "sam", "My patient is unresponsive and not breathing")
    kinds = [k for k, _ in events]
    assert kinds.index("banner") < kinds.index("final")
    assert "Rapid Response" in dict(events)["banner"]["text"]


async def test_AT19_phi_redacted_everywhere(seeded):
    llm = seeded.state.llm
    llm.calls.clear()
    events, final = await chat(
        seeded.api, "sam", "Patient John Smith MRN 00482913 fell, what's the post-fall procedure?"
    )
    assert events[0][0] == "phi"
    convo = (await seeded.api.get(f"/api/conversations/{final['conversation_id']}", headers=H("sam"))).text
    assert "00482913" not in convo and "[REDACTED-MRN]" in convo
    assert "00482913" not in json.dumps(llm.calls) and "John Smith" not in json.dumps(llm.calls)


async def test_AT20_egress_policy_withholds_restricted(seeded):
    external = FakeLLM()
    external.info = ProviderInfo("openrouter-free", "openai_compatible", "", "m", "", True, False, True, "us")
    hybrid = dataclasses.replace(
        seeded.state,
        llm=external,
        settings=Settings(_env_file=None, deployment_profile="hybrid", embed_provider="hashing"),
    )
    async with client(hybrid) as api:
        _, final = await chat(api, "jordan", "How is controlled substance waste witnessed and reconciled?")
    assert final["fallback"] == "egress_policy" and final["receipt"]["passages_withheld"].get("restricted", 0) >= 1
    assert external.calls == []


async def test_AT21_airgapped_blocks_egress(seeded):
    providers = load_providers()
    with pytest.raises(ComplianceConfigError):
        validate_compliance(
            Settings(_env_file=None, deployment_profile="airgapped", llm_provider="openrouter-free"), providers
        )
    guard = EgressGuard(Settings(_env_file=None, deployment_profile="airgapped").allowed_hosts, True)
    with pytest.raises(EgressBlocked):
        guard.check("https://openrouter.ai/api/v1/chat/completions")
    config = (await seeded.api.get("/api/system/config", headers=H("taylor"))).json()
    assert config["settings"]["deployment_profile"] == "lite"


async def test_AT22_provider_outage_passages_only(seeded):
    await seeded.api.post("/api/ops/drills/provider-outage", headers=H("casey"))
    try:
        started = asyncio.get_running_loop().time()
        _, final = await chat(
            seeded.api, "priya", "During the outage, what does the stroke alert protocol say about glucose?"
        )
        assert asyncio.get_running_loop().time() - started < 2
        assert final["fallback"] == "provider_unavailable" and final["citations"]
    finally:
        await seeded.redis.delete("drill:provider_outage")


async def test_AT23_delete_document_with_receipt(seeded):
    did = seeded.ids["Visitor Policy"]
    assert (await seeded.api.delete(f"/api/documents/{did}", headers=H("taylor"))).status_code == 202
    for _ in range(120):
        receipts = (await seeded.api.get("/api/deletions", headers=H("taylor"))).json()
        if any(r["document_id"] == did for r in receipts):
            break
        await asyncio.sleep(0.25)
    receipt = next(r for r in receipts if r["document_id"] == did)["detail"]
    assert receipt["chunks"] > 0 and receipt["vectors"] > 0 and receipt["objects"] >= 2
    hits = (await seeded.api.get("/api/search", params={"q": "visiting hours"}, headers=H("riley"))).json()
    assert not any(h["document_id"] == did for h in hits)


async def test_AT24_audit_trail_complete_and_redacted(seeded):
    items = []
    for page in range(1, 40):
        batch = (await seeded.api.get("/api/audit", params={"page": page}, headers=H("taylor"))).json()["items"]
        if not batch:
            break
        items += batch
    actions = {(i["actor_id"], i["action"]) for i in items}
    for expected in [
        ("alex", "document.uploaded"),
        ("taylor", "version.approved"),
        ("system", "version.published"),
        ("sam", "search.performed"),
        ("priya", "chat.answered"),
        ("taylor", "document.deleted"),
        ("casey", "drill.run"),
        ("system", "version.failed"),
    ]:
        assert expected in actions, expected
    assert "00482913" not in json.dumps(items)
