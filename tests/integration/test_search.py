"""Covers: FR-8, FR-9, CR-1, CR-2, CR-6, CR-7, CP-5, AT-05, AT-07, AT-08."""
import os
from pathlib import Path

import pytest
import redis.asyncio as aioredis

from tests.integration.api_client import as_user, build_state, client
from tests.integration.factories import create_version, make_ctx, run_pipeline, scalar

HAND_V1 = b"# Hand Hygiene\n\n## Alcohol rub\nRub hands with alcohol-based rub for at least 15 seconds."
HAND_V2 = b"# Hand Hygiene\n\n## Alcohol rub\nRub hands with alcohol-based rub for 20 to 30 seconds until dry."
PHARM = b"# Controlled Substance Waste\n\n## Waste\nControlled substance waste needs a witness and reconciliation."
HEPARIN = (b"# High-Alert Medication Independent Double-Check\n\n## Medications\nInsulin infusions, heparin "
           b"infusions and opioid PCA require an independent double-check by a second licensed clinician.")
LONG = ("# Long Policy\n\n" + "\n\n".join(f"## Part {i}\nAlcohol rub guidance part {i}. " + "Detail. " * 120
                                         for i in range(6))).encode()


@pytest.fixture
async def seeded(pool, tmp_path):
    ctx = make_ctx(pool, tmp_path)
    hand, v1 = await create_version(ctx, HAND_V1, title="Hand Hygiene Policy")
    await run_pipeline(ctx, v1)
    _, v2 = await create_version(ctx, HAND_V2, document_id=hand, version_number=2)
    await run_pipeline(ctx, v2)
    _, pv = await create_version(ctx, PHARM, title="Controlled Substance Waste", groups=("pharmacy",),
                                 classification="restricted", category="Medication & Pharmacy")
    await run_pipeline(ctx, pv)
    _, hv = await create_version(ctx, HEPARIN, title="High-Alert Medication Independent Double-Check",
                                 groups=("clinical",), category="Medication & Pharmacy")
    await run_pipeline(ctx, hv)
    _, lv = await create_version(ctx, LONG, title="Long Policy")
    await run_pipeline(ctx, lv)
    _, pending = await create_version(ctx, b"# Draft\nAlcohol rub draft text.", title="Draft",
                                      status="PENDING_APPROVAL")
    return {"hand": hand, "v1": v1, "v2": v2, "pending": pending}


@pytest.fixture
async def api(pool, tmp_path, seeded):
    r = aioredis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    async with client(build_state(pool, r, tmp_path)) as c:
        yield c
    await r.aclose()


async def search(api, user, q, **params):
    r = await api.get("/api/search", params={"q": q, **params}, headers=as_user(user))
    assert r.status_code == 200, r.text
    return r.json()


async def test_results_carry_title_and_version(api, seeded):
    hits = await search(api, "sam", "alcohol rub how long")
    top = hits[0]
    assert top["title"] == "Hand Hygiene Policy" and top["version_number"] == 2
    assert top["section"] == "Hand Hygiene > Alcohol rub" and top["page"] == 1 and 0 < top["score"] <= 1
    assert top["highlights"] and top["category"] == "Infection Control"


async def test_pending_and_superseded_never_returned(api, seeded):
    hits = await search(api, "alex", "alcohol rub")
    versions = {h["version_id"] for h in hits}
    assert seeded["v1"] not in versions and seeded["pending"] not in versions and seeded["v2"] in versions


async def test_permission_isolation_by_persona(api):
    assert not [h for h in await search(api, "riley", "controlled substance waste") if "Controlled" in h["title"]]
    assert any("Controlled" in h["title"] for h in await search(api, "jordan", "controlled substance waste"))


async def test_category_filter(api):
    hits = await search(api, "jordan", "waste alcohol", category="Medication & Pharmacy")
    assert hits and all(h["category"] == "Medication & Pharmacy" for h in hits)


async def test_max_two_per_document(api):
    hits = await search(api, "sam", "alcohol rub guidance part detail", top_k=8)
    assert max(sum(1 for h in hits if h["document_id"] == d) for d in {h["document_id"] for h in hits}) <= 2


async def test_search_degenerate_queries(api):
    """Review Focus 4."""
    for q, status in [("   ", 422), ("x" * 501, 422), ("the and of", 200), ("🧼🙌", 200), ("lavado de manos", 200)]:
        r = await api.get("/api/search", params={"q": q}, headers=as_user("sam"))
        assert r.status_code == status, (q, r.text)


async def test_query_audit_is_redacted(api, pool):
    await search(api, "sam", "Patient John Smith MRN 00482913 hand hygiene")
    detail = await scalar(pool, "SELECT detail::text FROM audit_log WHERE action = 'search.performed'")
    assert "00482913" not in detail and "REDACTED-MRN" in detail


async def test_query_is_redacted_before_embedding(pool, tmp_path, seeded):
    """Covers: CP-3. Retrieval must not pass identifiers to an embedding provider."""
    state = build_state(pool, None, tmp_path)
    original = state.embedder

    class RecordingEmbedder:
        dim = original.dim

        def __init__(self):
            self.received = []

        async def embed(self, texts):
            self.received.extend(texts)
            return await original.embed(texts)

    recorder = RecordingEmbedder()
    state.embedder = recorder
    async with client(state) as c:
        await search(c, "sam", "Patient John Smith MRN 00482913 hand hygiene")
    assert recorder.received
    assert "John Smith" not in str(recorder.received) and "00482913" not in str(recorder.received)


async def test_phi_block_mode_does_not_retrieve(pool, tmp_path, seeded):
    state = build_state(pool, None, tmp_path, phi_mode="block")
    async with client(state) as c:
        result = await c.get("/api/search", params={"q": "MRN 00482913 hand hygiene"}, headers=as_user("sam"))
    assert result.status_code == 400 and result.json()["error_code"] == "phi_detected"


async def test_rare_terms_beat_generic_words(api):
    hits = await search(api, "sam", "How much heparin should I give a 70 kg patient?")
    assert hits[0]["title"] == "High-Alert Medication Independent Double-Check"


async def test_abbreviations_are_understood(api):
    hits = await search(api, "sam", "Who double-checks an opioid PCA?")
    assert hits and hits[0]["title"] == "High-Alert Medication Independent Double-Check"


async def test_weak_matches_are_hidden(pool, tmp_path, seeded):
    """Results scoring below MIN_RELEVANCE are noise in the list; the search page hides them."""
    r = aioredis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    async with client(build_state(pool, r, tmp_path, min_relevance=0.9)) as strict:
        hits = (await strict.get("/api/search", params={"q": "alcohol rub"}, headers=as_user("sam"))).json()
    await r.aclose()
    assert all(h["score"] >= 0.9 for h in hits)


@pytest.mark.parametrize(("question", "section"), [
    ("what is the Rapid Response Team Activation Criteria", "Activation criteria"),
    ("How do I call the rapid response team?", "How to call"),
    ("What is the purpose of the rapid response team?", "Purpose"),
])
async def test_requested_section_survives_document_diversity_limit(pool, tmp_path, question, section):
    """Covers: FR-8, FR-10. Section headings must rank the answer ahead of introductory passages."""
    from tests.integration.test_chat_api import chat

    content = (Path(__file__).resolve().parents[2] / "corpus" / "rapid-response-criteria.md").read_bytes()
    ctx = make_ctx(pool, tmp_path)
    _, vid = await create_version(ctx, content, title="Rapid Response Team Activation Criteria",
                                  category="Emergency Response")
    await run_pipeline(ctx, vid)
    state = build_state(pool, None, tmp_path)
    async with client(state) as c:
        hits = await search(c, "sam", question)
        assert hits[0]["section"] == f"Rapid Response Team Activation Criteria > {section}"
        assert len(hits) <= 2
        final = (await chat(c, "sam", question))[-1][1]
    assert final["fallback"] is None
    assert final["citations"][0]["section"] == f"Rapid Response Team Activation Criteria > {section}"
    if section == "Activation criteria":
        assert "systolic blood pressure below 90 mmHg" in final["answer"]
        assert "heart rate above 130" in final["answer"]
