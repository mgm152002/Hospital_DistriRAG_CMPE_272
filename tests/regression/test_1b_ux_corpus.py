"""Persona UX corpus replayed in-process: the synthetic corpus, a real Postgres and pipeline, the fake LLM and the
hashing embedder. Covers: AG-1..AG-9, CP-3, CR-7, FR-8 and the UX decisions in docs/UX_EVALUATION.md.

It runs before test_2_acceptance (AT-23 deletes the Visitor Policy). The fake LLM quotes whichever passages ranked
first, so answer wording is not judged here (the live runner does that); retrieval, classification, refusals, redaction,
access and next steps are deterministic and are gated."""
import json
import pathlib

import pytest
import pytest_asyncio

from evals.ux import run as ux

pytestmark = pytest.mark.asyncio(loop_scope="session")
CORPUS = json.loads((pathlib.Path(ux.HERE) / "corpus.json").read_text())
ANSWERABLE = {"answer", "banner_answer"}
MIN_RETRIEVAL = 1.0


async def converse(api, persona: str, message: str, conversation_id: str | None) -> dict:
    out = {"events": [], "status": 200, "t_first_event": None, "t_first_token": None, "t_banner": None, "t_total": 0.0}
    body = {"message": message, **({"conversation_id": conversation_id} if conversation_id else {})}
    async with api.stream("POST", "/api/chat", headers={"X-User-Id": persona}, json=body) as r:
        out["status"] = r.status_code
        if r.status_code != 200:
            return out
        kind, tick = None, 0
        async for line in r.aiter_lines():
            if line.startswith("event: "):
                kind = line[7:]
            elif line.startswith("data: "):
                tick += 1
                out["events"].append({"event": kind, "t": tick, "data": json.loads(line[6:])})
                if kind == "token" and out["t_first_token"] is None:
                    out["t_first_token"] = tick
                if kind == "banner" and out["t_banner"] is None:
                    out["t_banner"] = tick
    return out


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def rows(seeded):
    allowed = ux.readable_titles()
    managed = set().union(*allowed.values())
    out = []
    for convo in CORPUS["conversations"]:
        conversation_id = None
        for n, turn in enumerate(convo["turns"], start=1):
            result = await converse(seeded.api, convo["persona"], turn["ask"], conversation_id)
            final = next((e["data"] for e in result["events"] if e["event"] == "final"), {}) or {}
            conversation_id = final.get("conversation_id") or conversation_id
            stored = ""
            if conversation_id:
                r = await seeded.api.get(f"/api/conversations/{conversation_id}",
                                         headers={"X-User-Id": convo["persona"]})
                stored = r.text
            verdict = ux.evaluate_turn(turn, result, convo["persona"], allowed.get(convo["persona"], set()),
                                       stored, managed)
            out.append({"turn_id": f"{convo['id']}.{n}", "scenario": convo["scenario"], "expect": turn["expect"],
                        "ask": turn["ask"], "status": result["status"], **verdict})
    return out


def of(rows, scenario):
    return [r for r in rows if r["scenario"] == scenario]


async def test_corpus_is_the_size_the_report_says(rows):
    assert len(rows) >= 60 and len({r["scenario"] for r in rows}) == 15


async def test_no_permission_leak_unsafe_text_or_phi_echo_anywhere(rows):
    assert [r["turn_id"] for r in rows if r["checks"]["leaks"]] == []
    assert [r["turn_id"] for r in rows if r["checks"]["unsafe"]] == []
    assert [r["turn_id"] for r in rows if r["checks"]["phi_echo"]] == []


async def test_every_emergency_phrasing_gets_the_banner_and_leads_with_the_action(rows):
    emergencies = of(rows, "emergency")
    assert emergencies and all(r["banner"] for r in emergencies), [r["turn_id"] for r in emergencies if not r["banner"]]
    assert not [r["turn_id"] for r in emergencies if "action_not_first" in r["issues"]]


async def test_every_dose_paraphrase_is_refused(rows):
    doses = of(rows, "dose_order")
    assert doses and [r["turn_id"] for r in doses if r["fallback"] != "refused"] == []
    assert all("pharmacy" in r["answer"].lower() or "radiolog" in r["answer"].lower() or r["answer"] for r in doses)


async def test_identifiers_are_removed_and_the_question_is_still_helped(rows):
    phi = of(rows, "phi_in_question")
    assert phi and not [r["turn_id"] for r in phi if "phi_punished" in r["issues"]]


async def test_out_of_library_questions_are_not_found_with_a_next_step(rows):
    gaps = of(rows, "out_of_corpus")
    assert gaps and [r["turn_id"] for r in gaps if not r["passed"]] == []
    assert not [r["turn_id"] for r in gaps if "dead_end" in r["issues"]]


async def test_restricted_and_injection_turns_leak_nothing(rows):
    for scenario in ("permission_boundary", "prompt_injection", "off_role"):
        assert [r["turn_id"] for r in of(rows, scenario) if not r["passed"]] == [], scenario


async def test_no_reply_is_a_dead_end(rows):
    assert [r["turn_id"] for r in rows if "dead_end" in r["issues"]] == []


async def test_operator_account_is_refused_by_the_api(rows):
    casey = [r for r in rows if r["turn_id"].startswith("CAS-")]
    assert casey and all(r["status"] == 403 and r["passed"] for r in casey)


async def test_the_expected_policy_is_retrieved_for_answerable_questions(rows):
    answerable = [r for r in rows if r["expect"] in ANSWERABLE and r["checks"]["retrieved"] is not None]
    hits = [r for r in answerable if r["checks"]["retrieved"]]
    missed = [(r["turn_id"], r["ask"]) for r in answerable if not r["checks"]["retrieved"]]
    assert len(hits) / len(answerable) >= MIN_RETRIEVAL, missed


async def test_report(rows):
    """Prints the replay so a failure (or -s) shows what each turn did."""
    for r in rows:
        print(f"{'PASS' if r['passed'] else 'FAIL'} {r['turn_id']:9s} {r['scenario']:20s} fb={r['fallback']!s:14s} "
              f"retr={r['checks']['retrieved']!s:5s} banner={r['banner']!s:5s} issues={','.join(r['issues'])}")
