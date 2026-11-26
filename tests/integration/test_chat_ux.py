"""Covers: FR-8, FR-10, AG-1..AG-9, CP-3, CP-6. UX decisions from the persona corpus: PHI redact-then-answer, jargon
search, emergency action first, relevance gate, no dead ends, preview event, operator access."""
import json
import os

import pytest
import redis.asyncio as aioredis

from tests.integration.api_client import as_user, build_state, client
from tests.integration.factories import create_version, make_ctx, run_pipeline, scalar

DOCS = [
    ("Hand Hygiene Policy", "Infection Control", ("all-staff",),
     b"# Hand Hygiene Policy\n\n## Alcohol-based hand rub\nRub all surfaces of both hands with alcohol-based hand rub "
     b"for 20 to 30 seconds until dry. This replaces the 15-second guidance in version 1.\n\n"
     b"## Soap and water\nUse soap and water when hands are visibly soiled and when caring for patients with "
     b"suspected or confirmed C. difficile. Wash for 40 to 60 seconds."),
    ("Fall Risk Assessment and Prevention", "Patient Safety", ("clinical",),
     b"# Fall Risk Assessment and Prevention\n\n"
     b"## Assessment\nAssess fall risk with the Morse Fall Scale on admission, every shift, after a fall, and after "
     b"any change in condition.\n\n"
     b"## Risk levels\nA Morse score of 45 or higher means high fall risk. A score of 25 to 44 means moderate risk."
     b"\n\n"
     b"## After a fall\nAssess the patient for injury before moving them, notify the provider, complete a post-fall "
     b"huddle within the shift, and document the fall in the incident reporting system."),
    ("Sharps Injury and Bloodborne Exposure", "Patient Safety", ("all-staff",),
     b"# Sharps Injury and Bloodborne Exposure\n\n## Reporting\nReport the exposure to Occupational Health within 1 "
     b"hour, any time of day, by calling extension 3030. Wash the area with soap and water."),
    ("Pressure Injury Prevention", "Nursing Procedure", ("nursing",),
     b"# Pressure Injury Prevention\n\n## Prevention\nReposition at-risk patients at least every 2 hours, float "
     b"heels, use a pressure-redistributing mattress, and keep skin clean and dry."),
    ("Code Blue Procedure", "Emergency Response", ("all-staff",),
     b"# Code Blue Procedure\n\n## Recognition\nA patient who is unresponsive and not breathing normally needs a "
     b"Code Blue.\n\n## Activation\nDial extension 5555 and state \"Code Blue\" with the unit and room number. "
     b"Start chest compressions immediately."),
    ("Jane Doe Resume", "Departmental Reference", ("all-staff",),
     b"# Jane Doe Resume\n\nJANE DOE\nBoston, MA\n\n## Experience\n### Staff Nurse, Cardiac Unit\n"
     b"Led the cardiac step-down unit night shift and trained new graduate nurses in telemetry monitoring.\n\n"
     b"### Charge Nurse, Emergency Department\n"
     b"Coordinated triage for a 40-bed emergency department and introduced a sepsis screening huddle.\n\n## Education\n"
     b"Bachelor of Science in Nursing, Boston College.\n\n## Skills\n"
     b"Telemetry, ACLS, PALS, sepsis screening, wound care."),
    ("Contact and Droplet Isolation Precautions", "Infection Control", ("clinical",),
     b"# Contact and Droplet Isolation Precautions\n\n## Droplet precautions\nUse droplet precautions for influenza "
     b"and pertussis. Wear a surgical mask within 2 metres (6 feet) of the patient."),
]


@pytest.fixture
async def api(pool, tmp_path):
    """These tests cover the redact path: identifiers are removed and the question still goes through."""
    ctx = make_ctx(pool, tmp_path)
    for title, category, groups, body in DOCS:
        _, vid = await create_version(ctx, body, title=title, groups=groups, category=category)
        await run_pipeline(ctx, vid)
    r = aioredis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    async with client(build_state(pool, r, tmp_path, llm_provider="fake", phi_mode="redact")) as c:
        yield c
    await r.aclose()


async def chat(api, user, message, conversation_id=None):
    events = []
    async with api.stream("POST", "/api/chat", headers=as_user(user),
                          json={"message": message, "conversation_id": conversation_id}) as r:
        assert r.status_code == 200
        event = None
        async for line in r.aiter_lines():
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                events.append((event, json.loads(line[6:])))
    return events


def final(events):
    return next(data for kind, data in events if kind == "final")


# ---- access: an operator-only account is refused by the API, not just hidden by the UI ------------------------------

async def test_operator_account_cannot_use_the_assistant(api):
    r = await api.post("/api/chat", headers=as_user("casey"), json={"message": "How do I call a code blue?"})
    assert r.status_code == 403 and r.json()["error_code"] == "forbidden"
    assert (await api.get("/api/conversations/none", headers=as_user("casey"))).status_code == 403


async def test_operator_search_still_returns_nothing_rather_than_an_error(api):
    r = await api.get("/api/search", params={"q": "hand hygiene"}, headers=as_user("casey"))
    assert r.status_code == 200 and r.json() == []


# ---- retrieval: clinical shorthand and colloquial wording reach the policy ------------------------------------

@pytest.mark.parametrize("query,title", [
    ("HH duration with ABHR", "Hand Hygiene Policy"),
    ("I just got stuck with a used needle", "Sharps Injury and Bloodborne Exposure"),
    ("how often do i turn pts so they dont get bedsores", "Pressure Injury Prevention"),
    ("my patient fell what now", "Fall Risk Assessment and Prevention"),
])
async def test_shorthand_and_lay_wording_find_the_policy(api, query, title):
    hits = (await api.get("/api/search", params={"q": query}, headers=as_user("sam"))).json()
    assert title in [h["title"] for h in hits[:3]], [h["title"] for h in hits]


async def test_a_schedule_question_retrieves_the_chunk_that_gives_the_schedule(api):
    """"Reassessment schedule" and "assess ... every shift" share no word; expansion must bridge them."""
    hits = (await api.get("/api/search", params={"q": "What is the fall risk reassessment schedule?"},
                          headers=as_user("sam"))).json()
    sections = [h["section"] for h in hits if h["title"] == "Fall Risk Assessment and Prevention"]
    assert any(s.endswith("> Assessment") for s in sections[:3]), sections


# ---- PHI: removed, noticed, never stored, and the question is still answered -------------------------------------

async def test_bare_name_is_removed_noticed_and_the_question_still_answered(api, pool):
    events = await chat(api, "sam", "John Smith MRN 4471203 in room 12 fell, what now?")
    kinds = [k for k, _ in events]
    assert kinds[0] == "phi"
    phi = events[0][1]
    assert phi["notice"].startswith("Removed a name") and "NAME" in phi["types"] and "LOCATION" in phi["types"]
    out = final(events)
    assert out["fallback"] is None and out["citations"][0]["title"] == "Fall Risk Assessment and Prevention"
    stored = await scalar(pool, "SELECT string_agg(content_redacted, ' ') FROM messages")
    for secret in ("John Smith", "4471203", "room 12"):
        assert secret not in stored


async def test_phi_in_search_is_removed_before_matching(api):
    r = await api.get("/api/search", params={"q": "Maria Gonzalez bed 4 bedsores"}, headers=as_user("sam"))
    assert r.status_code == 200
    assert "Pressure Injury Prevention" in [h["title"] for h in r.json()]


# ---- emergencies: banner first, action first ---------------------------------------------------------------------

@pytest.mark.parametrize("message", [
    "patient is not breathing",
    "A visitor collapsed in the lobby and isn't breathing",
])
async def test_emergency_gets_the_banner_and_leads_with_the_number(api, message):
    events = await chat(api, "riley", message)
    kinds = [k for k, _ in events]
    assert "banner" in kinds and kinds.index("banner") < kinds.index("final")
    first_line = final(events)["answer"].splitlines()[0]
    assert "5555" in first_line and "[" in first_line


# ---- refusals, relevance gate, dead ends ---------------------------------------------------------------------------

async def test_dose_paraphrase_is_refused_and_routed_to_pharmacy(api):
    out = final(await chat(api, "sam", "Heparin drip rate for a 90 kg pt?"))
    assert out["fallback"] == "refused" and "pharmacy" in out["answer"].lower()


async def test_question_outside_the_library_is_not_answered_with_a_cited_non_answer(api):
    out = final(await chat(api, "sam", "What is our DVT prophylaxis protocol for surgical patients?"))
    assert out["fallback"] == "no_sources" and out["citations"] == []
    assert "droplet" not in out["answer"].lower()
    assert "knowledge administrator" in out["answer"] and "Registered nurse" in out["answer"]


async def test_role_without_access_gets_an_explained_empty_answer(api):
    out = final(await chat(api, "riley", "How often do I reposition patients to prevent pressure injury?"))
    assert out["fallback"] == "no_sources" and "Patient services" in out["answer"]


# ---- answer quality ------------------------------------------------------------------------------------------------

async def test_preview_arrives_with_the_sources_before_the_answer(api):
    events = await chat(api, "sam", "How long should I rub hands with alcohol-based hand rub?")
    kinds = [k for k, _ in events]
    assert kinds.index("sources") < kinds.index("preview") < kinds.index("token") < kinds.index("final")
    assert events[kinds.index("preview")][1]["title"] == "Hand Hygiene Policy"


async def test_c_difficile_answer_is_never_cut_in_half(api):
    answer = final(await chat(api, "sam", "When must I use soap and water for C. difficile?"))["answer"]
    assert not answer.lstrip().startswith("difficile")
    assert "C. difficile" in answer or "soap and water" in answer.lower()


# ---- one-click demo questions ---------------------------------------------------------------------------------------

async def test_a_persona_is_offered_its_own_corpus_questions_grouped_by_scenario(api):
    body = (await api.get("/api/demo/questions", headers=as_user("sam"))).json()
    assert body["enabled"] is True
    asks = [t for g in body["groups"] for c in g["conversations"] for t in c["turns"]]
    assert "I just got stuck with a used needle" in asks and "What are our sepsis screening criteria?" not in asks
    multi = next(g for g in body["groups"] if g["scenario"] == "multi_turn")
    assert any(len(c["turns"]) == 3 for c in multi["conversations"])


async def test_an_operator_is_offered_nothing(api):
    body = (await api.get("/api/demo/questions", headers=as_user("casey"))).json()
    assert body == {"enabled": True, "groups": []}


async def test_demo_questions_need_a_signed_in_user(api):
    assert (await api.get("/api/demo/questions")).status_code == 401


# ---- recent conversations, for the sidebar -------------------------------------------------------------------------

async def test_recent_conversations_are_listed_newest_first_with_the_first_question_as_title(api):
    first = final(await chat(api, "sam", "How long should I rub hands with alcohol-based hand rub?"))
    await chat(api, "sam", "and with soap?", first["conversation_id"])
    second = final(await chat(api, "sam", "What do I do after a needlestick injury?"))
    body = (await api.get("/api/conversations", headers=as_user("sam"))).json()
    assert [c["conversation_id"] for c in body] == [second["conversation_id"], first["conversation_id"]]
    assert body[1]["title"] == "How long should I rub hands with alcohol-based hand rub?"
    assert body[1]["messages"] == 4 and "updated_at" in body[0]


async def test_a_persons_recent_conversations_are_theirs_alone(api):
    await chat(api, "sam", "What do I do after a needlestick injury?")
    assert (await api.get("/api/conversations", headers=as_user("riley"))).json() == []
    assert (await api.get("/api/conversations", headers=as_user("casey"))).status_code == 403


async def test_a_long_first_question_is_shortened_for_the_title_and_identifiers_stay_redacted(api):
    await chat(api, "sam", "John Smith MRN 4471203 fell out of bed during the night shift and I need to know every "
                           "step of the post-fall process including documentation please")
    title = (await api.get("/api/conversations", headers=as_user("sam"))).json()[0]["title"]
    assert len(title) <= 80 and title.endswith("…") and "John Smith" not in title and "4471203" not in title



# ---- retrieval brings the neighbouring sections of the best-matching document --------------------------------------

async def test_a_question_about_a_document_gets_its_neighbouring_sections_not_just_one_fragment(api):
    events = await chat(api, "sam", "what does the nursing resume say")
    sources = next(data for kind, data in events if kind == "sources")["passages"]
    jane = [p for p in sources if p["title"] == "Jane Doe Resume"]
    assert len(jane) >= 3, [p["section"] for p in jane]
    assert any("Staff Nurse" in (p["section"] or "") + p["text"] for p in jane)


async def test_neighbouring_sections_never_bring_in_a_document_the_person_cannot_read(api):
    events = await chat(api, "riley", "what does the nursing resume say")
    titles = {p["title"] for kind, data in events if kind == "sources" for p in data["passages"]}
    assert "Contact and Droplet Isolation Precautions" not in titles
    assert "Fall Risk Assessment and Prevention" not in titles


async def test_possessive_follow_up_has_the_resumes_experience_available(api):
    first = final(await chat(api, "sam", "what does the nursing resume say"))
    events = await chat(api, "sam", "whats her background", first["conversation_id"])
    out = final(events)
    assert out["fallback"] is None
    sources = next(data for kind, data in events if kind == "sources")["passages"]
    resume = [p for p in sources if p["title"] == "Jane Doe Resume"]
    assert any("trained new graduate nurses" in p["text"] for p in resume)
    assert len({p["chunk_id"] for p in sources}) == len(sources) <= 6


async def test_neighbouring_context_preserves_relevant_search_hits_and_scores(api, pool, tmp_path):
    from api.auth import persona_user
    from assistant.store import make_deps
    from search.query import search

    state = build_state(pool, None, tmp_path, min_relevance=0.01)
    user = persona_user("sam")
    question = "hand hygiene fall risk pressure injury code blue jane doe"
    async with pool.connection() as conn:
        hits = await search(conn, state.embedder, user, question, text_weight=state.settings.hybrid_text_weight)
    expected = [(h.chunk_id, h.score) for h in hits if h.score >= 0.01][:6]
    assert len(expected) == 6
    passages = await make_deps(state).retrieve(user, question, "policy_lookup")
    assert [(p.chunk_id, p.score) for p in passages] == expected


async def test_provider_outage_still_answers_from_the_uploaded_resume_and_a_background_follow_up(api, monkeypatch):
    from common.llm import ProviderUnavailable
    from common.llm.fake import FakeLLM

    async def unavailable(self, messages, max_tokens=600):
        raise ProviderUnavailable("Provider outage")
        yield ""

    monkeypatch.setattr(FakeLLM, "stream", unavailable)
    out = final(await chat(api, "sam", "what does the nursing resume say"))
    assert out["fallback"] == "provider_unavailable" and out["receipt"]["mode"] == "extractive"
    assert out["cited"] and all(c["title"] == "Jane Doe Resume" for c in out["citations"])
    follow_up = final(await chat(api, "sam", "what is her background", out["conversation_id"]))
    assert follow_up["receipt"].get("mode") == "extractive" and follow_up["cited"]
    # Experience and education are both background; either is a correct quote.
    assert any(t in follow_up["answer"] for t in ("trained new graduate nurses", "Bachelor of Science in Nursing"))
    assert follow_up["conversation_id"] == out["conversation_id"]
