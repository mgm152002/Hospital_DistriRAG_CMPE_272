"""Covers: AG-1..AG-9, RL-10, CP-2, CP-3. UX decisions: no dead ends, extractive fallbacks, emergency action first,
PHI redact-then-answer, relevance gate, early preview."""
from assistant.answer import DISCLAIMER
from common.config import Settings
from common.llm import ProviderInfo, ProviderUnavailable
from common.llm.fake import FakeLLM
from tests.unit.test_answer_pipeline import RRT, SEPSIS, deps, final, passage, run

CODE = passage(1, "A patient who is unresponsive and not breathing normally needs a Code Blue.\n"
                  "Dial extension 5555 and state \"Code Blue\" with the unit and room number. "
                  "Start chest compressions immediately.", title="Code Blue Procedure", score=0.5)
RRT_P = passage(1, RRT, title="Rapid Response Team Activation Criteria", score=0.5)
ISOLATION = passage(1, "Use droplet precautions for influenza and pertussis. Wear a surgical mask within 2 metres "
                       "(6 feet) of the patient.", title="Contact and Droplet Isolation Precautions", score=0.15)
RESTRICTED = passage(1, "Every controlled substance waste needs a second licensed witness who co-signs the record.",
                     cls="restricted", title="Controlled Substance Waste and Reconciliation", score=0.5)


def uncited(_messages):
    return "This answer has no citation at all"


def hedge(_messages):
    return "The provided passages do not state the criteria [1]."


def body(out):
    return out["answer"].removesuffix(DISCLAIMER).strip()


# ---- extractive fallbacks (decisions P1: citation failure, egress, outage) --------------------------------------

async def test_failed_citation_check_shows_the_closest_source_sentence():
    d, _ = deps([RRT_P], llm=FakeLLM(uncited))
    out = final(await run("What are the rapid response criteria?", d))
    assert out["fallback"] == "citations" and out["receipt"]["mode"] == "extractive"
    assert body(out).startswith("Call the rapid response team for systolic blood pressure below 90")
    assert "could not be checked" in out["note"]
    assert out["cited"] == [1] and out["band"] == "Medium"  # quoted text is never High


async def test_egress_policy_still_answers_from_the_withheld_policy_text():
    ext = ProviderInfo("openrouter-free", "openai_compatible", "", "m", "", True, False, True, "us")
    llm = FakeLLM()
    llm.info = ext
    d, _ = deps([RESTRICTED], llm=llm, settings=Settings(_env_file=None, deployment_profile="hybrid"))
    out = final(await run("How is controlled substance waste witnessed?", d))
    assert llm.calls == [] and out["fallback"] == "egress_policy" and out["receipt"]["mode"] == "extractive"
    assert body(out).startswith("Every controlled substance waste needs a second licensed witness")
    assert "confidential" in out["note"] and "can't be sent" not in out["answer"]


async def test_provider_outage_still_answers_from_the_source():
    class Down(FakeLLM):
        async def stream(self, messages, max_tokens=600):
            raise ProviderUnavailable("down")
            yield ""
    d, _ = deps([RRT_P], llm=Down())
    out = final(await run("What are the rapid response criteria?", d))
    assert out["fallback"] == "provider_unavailable"
    assert body(out).startswith("Call the rapid response team")
    assert out["note"].startswith("The AI service is unavailable")


# ---- hedges and the relevance gate (decision P0-4) ---------------------------------------------------------------

async def test_model_hedge_is_trusted_and_returned_in_its_own_words_without_a_quote():
    d, _ = deps([RRT_P], llm=FakeLLM(hedge))
    out = final(await run("What are the rapid response criteria?", d))
    assert out["fallback"] == "no_sources" and body(out).startswith("The provided passages do not state the criteria.")
    assert "Call the rapid response team" not in out["answer"] and "[1]" not in out["answer"]
    assert out["citations"] == [] and out["note"] is None and out["receipt"].get("mode") != "extractive"


async def test_cited_non_answer_becomes_not_found():
    llm = FakeLLM(lambda m: "They only list droplet precautions for influenza and pertussis [1].")
    d, _ = deps([ISOLATION], llm=llm)
    out = final(await run("What is our DVT prophylaxis protocol for surgical patients?", d))
    assert out["fallback"] == "no_sources" and "droplet" not in out["answer"]
    assert llm.calls == []  # the relevance gate stops it before any model call


async def test_hedge_without_support_in_the_passages_is_not_found():
    llm = FakeLLM(lambda m: "The passages do not mention this [1].")
    d, _ = deps([passage(1, SEPSIS, score=0.6)], llm=llm)
    out = final(await run("What is the parking permit procedure for night shift?", d))
    assert out["fallback"] == "no_sources"


# ---- no dead ends (decision P2) ----------------------------------------------------------------------------------

async def test_not_found_names_the_role_and_a_next_step():
    d, _ = deps([passage(1, SEPSIS, score=0.05)])
    out = final(await run("Where is the cafeteria?", d, role="Patient services / front desk"))
    assert out["answer"].startswith("I couldn't find this in approved documents you can access.")
    assert "Patient services / front desk" in out["answer"] and "try different words" in out["answer"].lower()
    assert "knowledge administrator" in out["answer"]


async def test_not_found_without_a_known_role_still_has_a_next_step():
    d, _ = deps([passage(1, SEPSIS, score=0.05)])
    out = final(await run("Where is the cafeteria?", d, role=""))
    assert "try different words" in out["answer"].lower()


async def test_dose_refusal_routes_to_pharmacy():
    d, _ = deps([passage(1, "Do not calculate weight-based doses at the bedside. Request a pharmacy consult.")])
    out = final(await run("Heparin drip rate for a 90 kg pt?", d))
    assert out["fallback"] == "refused" and "pharmacy" in out["answer"].lower()
    assert out["answer"].startswith("I can't give or calculate doses")


async def test_diagnosis_refusal_keeps_its_wording_and_points_to_criteria():
    d, _ = deps([passage(1, SEPSIS)])
    out = final(await run("Does this patient have sepsis?", d))
    assert out["answer"].startswith("I can't make a diagnosis or patient-specific recommendation.")
    assert "criteria" in out["answer"].lower()


# ---- emergencies: action first (decision P0-3) -------------------------------------------------------------------

async def test_emergency_answer_leads_with_the_action_and_number():
    d, _ = deps([CODE])
    events = await run("patient is not breathing", d)
    assert [e.type for e in events][:3] == ["classification", "banner", "sources"]
    first_line = final(events)["answer"].splitlines()[0]
    assert "5555" in first_line and "[1]" in first_line


async def test_new_emergency_phrasing_gets_the_banner_before_any_answer():
    d, _ = deps([CODE])
    events = await run("A visitor collapsed in the lobby and isn't breathing", d)
    types = [e.type for e in events]
    assert types.index("banner") < types.index("sources") and types.index("banner") < types.index("final")


# ---- PHI: redact, answer, explain (decision P0-1) ----------------------------------------------------------------

async def test_bare_name_is_redacted_everywhere_and_the_question_is_still_answered():
    seen = {}
    llm = FakeLLM()
    d, rec = deps([passage(1, "After a fall, assess the patient for injury before moving them.",
                           title="Fall Risk Assessment and Prevention", score=0.5)], llm=llm,
                  settings=Settings(_env_file=None, phi_mode="redact"))
    original = d.retrieve

    async def spy(user, question, label):
        seen["question"] = question
        return await original(user, question, label)
    d.retrieve = spy
    events = await run("John Smith MRN 4471203 in room 12 fell, what now?", d)
    out = final(events)
    phi = next(e.data for e in events if e.type == "phi")
    assert "John" not in str(llm.calls) and "4471203" not in str(llm.calls) and "John" not in str(rec.saved)
    assert "[REDACTED" not in seen["question"] and "John" not in seen["question"]
    assert phi["notice"].startswith("Removed a name") and "NAME" in phi["types"]
    assert out["fallback"] is None and "assess the patient for injury" in out["answer"]


async def test_phi_event_comes_before_everything_else():
    d, _ = deps([passage(1, SEPSIS)])
    events = await run("Maria Gonzalez DOB 03/14/1952 asks about sepsis screening", d)
    assert events[0].type == "phi"


# ---- early preview (decision P2: first passage fast) -------------------------------------------------------------

async def test_preview_arrives_with_the_sources_before_the_model_answers():
    d, _ = deps([RRT_P])
    events = await run("What are the rapid response criteria?", d)
    types = [e.type for e in events]
    preview = next(e.data for e in events if e.type == "preview")
    assert types.index("sources") < types.index("preview") < types.index("token") < types.index("final")
    assert preview["index"] == 1 and preview["title"] == "Rapid Response Team Activation Criteria"
    assert "Call the rapid response team" in preview["text"]


async def test_no_preview_when_nothing_relevant_was_found():
    d, _ = deps([passage(1, SEPSIS, score=0.05)])
    assert "preview" not in [e.type for e in await run("Where is the cafeteria?", d)]


# ---- follow-ups: retrieval borrows the previous question ----------------------------------------------------------

async def test_follow_up_retrieves_with_the_previous_question_but_the_model_sees_both_turns():
    seen = {}
    d, _ = deps([RRT_P])
    original = d.retrieve

    async def spy(user, question, label):
        seen["question"] = question
        return await original(user, question, label)

    async def history(user, conversation_id):
        return [("What are the rapid response criteria?", "Call the team for low blood pressure. [1]")]
    d.retrieve, d.history = spy, history
    out = final(await run("how do I call them?", d))
    assert "rapid response criteria" in seen["question"] and seen["question"].endswith("how do I call them?")
    assert out["fallback"] is None


# ---- guard changes must retire answers cached under the old guards -------------------------------------------------

def test_cache_key_changes_with_the_guard_version():
    from assistant.answer import cache_key
    args = ("q", ["all-staff"], "policy_lookup", "fake", [RRT_P], [], "nurse", "m")
    assert cache_key(*args) != cache_key(*args, guard_version=2)


async def test_an_answer_cached_under_older_guards_is_not_served(monkeypatch):
    import assistant.answer as module
    llm = FakeLLM()
    d, rec = deps([RRT_P], llm=llm)
    monkeypatch.setattr(module, "GUARD_VERSION", module.GUARD_VERSION - 1)
    await run("What are the rapid response criteria?", d)  # cached under the previous guard version
    assert rec.cache and len(llm.calls) == 1
    monkeypatch.undo()
    out = final(await run("What are the rapid response criteria?", d))
    assert len(llm.calls) == 2 and out["receipt"]["cached"] is False


async def test_a_changelog_only_model_answer_is_recovered_from_the_source():
    hand = passage(1, "Rub all surfaces of both hands with alcohol-based hand rub for 20 to 30 seconds until dry. "
                      "This replaces the 15-second guidance in version 1.", title="Hand Hygiene Policy", score=0.5)
    d, _ = deps([hand], llm=FakeLLM(lambda m: "This replaces the 15-second guidance in version 1. [1]"))
    out = final(await run("How long do I rub hands with alcohol gel?", d))
    assert out["fallback"] == "model_hedge" and "20 to 30 seconds" in out["answer"]
    assert "15-second" not in out["answer"]


# ---- emergencies keep the action first on every path, including the fallbacks ---------------------------------------

async def test_emergency_action_comes_first_even_when_the_model_is_down():
    class Down(FakeLLM):
        async def stream(self, messages, max_tokens=600):
            raise ProviderUnavailable("down")
            yield ""
    d, _ = deps([CODE], llm=Down())
    out = final(await run("patient is not breathing", d))
    assert out["fallback"] == "provider_unavailable"
    assert "5555" in out["answer"].splitlines()[0]
    assert out["note"].startswith("The AI service is unavailable")


async def test_emergency_action_comes_first_when_the_citation_check_fails():
    d, _ = deps([CODE], llm=FakeLLM(uncited))
    out = final(await run("patient is not breathing", d))
    assert out["fallback"] == "citations" and "5555" in out["answer"].splitlines()[0]


async def test_a_quoted_fallback_leads_with_the_policy_and_explains_itself_in_a_note():
    class Down(FakeLLM):
        async def stream(self, messages, max_tokens=600):
            raise ProviderUnavailable("down")
            yield ""
    d, _ = deps([RRT_P], llm=Down())
    out = final(await run("What are the rapid response criteria?", d))
    assert out["answer"].startswith("Call the rapid response team")
    assert "here are the most relevant" not in out["answer"]
    assert out["note"].startswith("The AI service is unavailable")


# ---- confidential top match: never replaced by an unrelated passage the model is allowed to see --------------------

ANTICOAG = passage(1, "Consider reversal for life-threatening bleeding or an emergency procedure in a patient taking "
                      "an anticoagulant.", cls="confidential", title="Anticoagulation Reversal Reference", score=0.61)
DIET = passage(2, "Weigh yourself every morning after using the toilet and before breakfast.", cls="public", doc="d2",
               title="Discharge Instructions: Heart Failure", score=0.21)


def external(llm):
    llm.info = ProviderInfo("openrouter-free", "openai_compatible", "", "m", "", True, False, True, "us")
    return llm


async def test_withheld_top_match_is_quoted_instead_of_asking_the_model_about_an_unrelated_passage():
    """Priya asked about anticoagulation reversal; the policy is confidential, so only a diet page was sendable and
    the answer was "I couldn't find this in approved documents you can access". It exists, and she may read it."""
    llm = external(FakeLLM())
    d, _ = deps([ANTICOAG, DIET], llm=llm,
                settings=Settings(_env_file=None, deployment_profile="hybrid", min_relevance=0.15))
    out = final(await run("When should anticoagulation reversal be considered?", d, role="Attending physician"))
    assert llm.calls == [] and out["fallback"] == "egress_policy" and out["receipt"]["mode"] == "extractive"
    assert "life-threatening bleeding" in out["answer"] and "couldn't find" not in out["answer"]
    assert out["receipt"]["egress_decision"] == "fallback_passages_only"
    assert [c["title"] for c in out["citations"]] == ["Anticoagulation Reversal Reference"]


async def test_an_allowed_passage_that_outranks_the_withheld_one_still_goes_to_the_model():
    llm = external(FakeLLM())
    better = passage(2, "Weigh yourself every morning and record it.", cls="public", doc="d2", score=0.9,
                     title="Discharge Instructions: Heart Failure")
    d, _ = deps([ANTICOAG, better], llm=llm,
                settings=Settings(_env_file=None, deployment_profile="hybrid", min_relevance=0.15))
    out = final(await run("How should I weigh myself every morning?", d))
    assert len(llm.calls) == 1 and out["fallback"] is None


async def test_a_hedge_is_recovered_from_every_passage_the_user_may_read_not_only_the_sendable_ones():
    llm = external(FakeLLM(hedge))
    anticoag = passage(1, ANTICOAG.text, cls="confidential", title="Anticoagulation Reversal Reference", score=0.5)
    diet = passage(2, DIET.text, cls="public", doc="d2", title="Discharge Instructions: Heart Failure", score=0.55)
    d, _ = deps([anticoag, diet], llm=llm,
                settings=Settings(_env_file=None, deployment_profile="hybrid", min_relevance=0.15))
    out = final(await run("When should anticoagulation reversal be considered?", d, role="Attending physician"))
    assert len(llm.calls) == 1 and out["fallback"] == "model_hedge"
    assert "life-threatening bleeding" in out["answer"] and "couldn't find" not in out["answer"]


# ---- a near-miss quote is not an answer (the open-wound question) -------------------------------------------------

HAND_RUB = passage(1, "Rub all surfaces of both hands with alcohol-based hand rub for 20 to 30 seconds until dry.",
                   title="Hand Hygiene Policy", score=0.6)
SOAP = passage(2, "Use soap and water for hand hygiene, not alcohol rub alone, and clean the room with a sporicidal "
                  "agent at discharge.", title="Contact and Droplet Isolation Precautions", doc="d2", score=0.6)
WOUND = "should I rub alcohol on open wound on a patient"


async def test_a_hedge_that_the_source_cannot_resolve_is_not_papered_over_with_a_near_miss_quote():
    """The model said the passages do not cover wounds. They do not: hand rub is for hands. Quoting it was wrong."""
    d, _ = deps([HAND_RUB, SOAP], llm=FakeLLM(hedge))
    out = final(await run(WOUND, d, role="Registered nurse"))
    assert out["fallback"] == "no_sources" and out["answer"].startswith("The provided passages do not state")
    assert "Rub all surfaces" not in out["answer"] and "sporicidal" not in out["answer"]


async def test_follow_up_hedge_is_not_answered_with_the_previous_turns_quote():
    """The screenshot bug: "should I rub it on open wound" after a hand-rub question was answered by quoting the
    hand-rub sentence, matched against the merged follow-up query. The model's honest answer is shown instead."""
    d, _ = deps([HAND_RUB, SOAP], llm=FakeLLM(lambda m: "The passages do not cover applying hand rub to an open "
                                                      "wound; they only describe rubbing hands [1]."))

    async def history(user, conversation_id):
        return [("How long should I rub my hands with alcohol-based hand rub?",
                 "Rub all surfaces of both hands for 20 to 30 seconds until dry [1].")]
    d.history = history
    out = final(await run("should I rub it on open wound", d))
    assert out["fallback"] == "no_sources" and out["note"] is None
    assert "Rub all surfaces" not in out["answer"] and "do not cover" in out["answer"]


async def test_a_partial_answer_keeps_what_is_covered_and_says_what_is_not():
    llm = FakeLLM(lambda m: "The policy does not say how long to wash the wound.\n\n"
                            "- Dispose of sharps in a sharps container at the point of use [1].\n"
                            "- Report the exposure to Occupational Health within 1 hour [1].")
    sharps = passage(1, "Dispose of sharps in a sharps container at the point of use. Report the exposure to "
                        "Occupational Health within 1 hour.", title="Sharps Injury and Bloodborne Exposure", score=0.6)
    d, _ = deps([sharps], llm=llm)
    out = final(await run("What do I do after a needlestick injury?", d))
    assert out["fallback"] is None and out["cited"] == [1]
    assert "does not say how long" in out["answer"] and "\n- Report the exposure" in out["answer"]


async def test_a_conversational_markdown_answer_passes_the_citation_check():
    llm = FakeLLM(lambda m: "Call the rapid response team when vital signs cross these limits:\n\n"
                            "- **Systolic blood pressure** below 90 [1]\n- **Heart rate** above 130 [1]")
    d, _ = deps([RRT_P], llm=llm)
    out = final(await run("What are the rapid response criteria?", d))
    assert out["fallback"] is None and out["receipt"]["checks"]["citations"] == "pass"
    assert "- **Heart rate** above 130 [1]" in out["answer"]


async def test_a_follow_up_is_condensed_by_the_model_for_retrieval():
    from assistant.contextualize import CONDENSE_PROMPT
    seen = {}

    def script(messages):
        if messages[0]["content"] == CONDENSE_PROMPT:
            return "Rapid response team activation phone number"
        return "Call the rapid response team for systolic blood pressure below 90 or heart rate above 130 [1]."
    llm = FakeLLM(script)
    llm.info = ProviderInfo("local-model", "ollama", "", "m", "", False, False, False, "local")
    d, _ = deps([RRT_P], llm=llm)
    original = d.retrieve

    async def spy(user, question, label):
        seen["question"] = question
        return await original(user, question, label)

    async def history(user, conversation_id):
        return [("What are the rapid response criteria?", "Call the team for low blood pressure. [1]")]
    d.retrieve, d.history = spy, history
    out = final(await run("how do I call them?", d))
    assert seen["question"] == "Rapid response team activation phone number"
    assert len(llm.calls) == 2 and out["fallback"] is None


async def test_a_failed_citation_check_does_not_quote_an_unrelated_sentence_either():
    d, _ = deps([HAND_RUB, SOAP], llm=FakeLLM(uncited))
    out = final(await run(WOUND, d, role="Registered nurse"))
    assert out["fallback"] == "citations" and out["answer"].startswith("I couldn't verify a cited answer")
    assert "Rub all surfaces" not in out["answer"] and out["receipt"].get("mode") != "extractive"


async def test_no_closest_text_preview_is_shown_for_a_near_miss():
    d, _ = deps([HAND_RUB, SOAP])
    assert "preview" not in [e.type for e in await run(WOUND, d)]


async def test_a_lay_phrased_question_is_answered_from_the_policy_it_means():
    sharps = passage(1, "Dispose of sharps in a sharps container at the point of use. Report the exposure to "
                        "Occupational Health within 1 hour.", title="Sharps Injury and Bloodborne Exposure", score=0.6)
    d, _ = deps([sharps])
    out = final(await run("I just got stuck with a used needle", d))
    assert out["fallback"] is None and "sharps container" in out["answer"]



# ---- what users actually see: no plumbing, no wrong quotes, no needless "couldn't verify" ----------------------------

async def test_a_reply_with_nothing_quoted_explains_itself_in_the_answer_and_has_no_note():
    d, _ = deps([HAND_RUB, SOAP], llm=FakeLLM(uncited))
    out = final(await run(WOUND, d))
    assert out["answer"].startswith("I couldn't verify a cited answer") and out.get("note") is None


async def test_a_needlestick_question_quotes_the_sharps_policy_not_a_falls_sentence_about_injury():
    falls = passage(1, "Assess the patient for injury before moving them, notify the provider, and complete a "
                       "post-fall huddle.", title="Fall Risk Assessment and Prevention", score=0.6)
    sharps = passage(2, "Wash the area with soap and water. Report the exposure to Occupational Health within 1 hour "
                        "by calling extension 3030.", title="Sharps Injury and Bloodborne Exposure", doc="d2",
                     score=0.5)
    d, _ = deps([falls, sharps], llm=FakeLLM(uncited))
    out = final(await run("What do I do after a needlestick injury?", d))
    assert "post-fall" not in out["answer"] and "Occupational Health" in out["answer"]


async def test_a_sentence_copied_from_the_policy_without_its_number_is_accepted_and_cited():
    """Free models often drop the [1]. A sentence that is the policy's own words is verified by its content."""
    d, _ = deps([RRT_P], llm=FakeLLM(lambda m: "Call the rapid response team for systolic blood pressure below 90 "
                                               "or heart rate above 130."))
    out = final(await run("What are the rapid response criteria?", d))
    assert out["fallback"] is None and "[1]" in out["answer"]
    assert out["answer"].startswith("Call the rapid response team")


async def test_an_uncited_sentence_that_is_not_in_the_policy_is_still_rejected():
    d, _ = deps([RRT_P], llm=FakeLLM(lambda m: "Always call your manager first before anything else happens."))
    out = final(await run("What are the rapid response criteria?", d))
    assert out["fallback"] == "citations"


# ---- a quoted answer gets the same personal-details screen as a generated one --------------------------------------

async def test_a_sentence_with_personal_contact_details_is_never_quoted():
    """A résumé uploaded to the library was quoted back with its phone number and email address."""
    resume = passage(1, "San Jose, CA | +1 6693408639 | jane.doe@example.com | linkedin.com/in/jane-doe/",
                     title="Jane Doe Resume SWE", score=0.6)
    d, _ = deps([resume], llm=FakeLLM(uncited))
    out = final(await run("who is jane", d))
    for secret in ("6693408639", "jane.doe@example.com"):
        assert secret not in out["answer"], out["answer"]
    assert "[REDACTED" not in out["answer"]  # not quoted at all, rather than quoted full of holes


async def test_no_preview_is_built_from_a_sentence_with_personal_details():
    resume = passage(1, "Reach me at jane.doe@example.com or +1 6693408639 any time.", title="Jane Doe", score=0.6)
    d, _ = deps([resume], llm=FakeLLM(uncited))
    events = await run("how do I reach jane", d)
    assert "jane.doe@example.com" not in str([e.data for e in events if e.type == "preview"])


# ---- what was cited is saved with the reply, so a reopened conversation does not claim a source it never used -------

async def test_each_returned_passage_says_whether_the_answer_cited_it():
    d, rec = deps([HAND_RUB, SOAP], llm=FakeLLM(uncited))
    out = final(await run(WOUND, d))
    assert out["citations"] and all(c["cited"] is False for c in out["citations"])
    assert all(c["cited"] is False for c in rec.saved[-1][1]["citations"])  # and that is what gets stored


async def test_a_cited_passage_is_marked_as_cited():
    d, _ = deps([RRT_P])
    out = final(await run("What are the rapid response criteria?", d))
    assert [c["cited"] for c in out["citations"]] == [True]


async def test_an_empty_model_reply_falls_back_to_the_policy_text_not_couldnt_verify():
    d, _ = deps([RRT_P], llm=FakeLLM(lambda m: ""))
    out = final(await run("What are the rapid response criteria?", d))
    assert out["fallback"] == "provider_unavailable" and out["answer"].startswith("Call the rapid response team")


async def test_a_question_naming_a_person_is_refused_before_any_search():
    resume = passage(1, "MANOJ GANJIGATTE MANJUNATHA\n"
                        "San Jose, CA | +1 6693408639 | manoj@example.com | linkedin.com/in/manoj/",
                     title="Manoj GM Resume SWE", score=0.6)
    llm = FakeLLM()
    d, _ = deps([resume], llm=llm)
    out = final(await run("who is manoj", d))
    assert out["fallback"] == "phi_blocked" and not llm.calls and "6693408639" not in out["answer"]


async def test_outage_skips_unsafe_top_quotes_before_choosing_useful_text():
    contact = passage(1, "Contact Manoj at manoj@example.com to discuss his background.",
                      title="Manoj Resume", score=0.8)
    phone = passage(2, "Call Manoj at +1 6693408639 about his background.", title="Manoj Resume", score=0.7)
    work = passage(3, "Built an incident automation service and trained engineers in site reliability.",
                   title="Manoj Resume", score=0.2)
    d, _ = deps([contact, phone, work], llm=FakeLLM(lambda m: ""))
    out = final(await run("what incident automation service was built?", d))
    assert "Built an incident automation service" in out["answer"] and out["cited"] == [3]
    assert "manoj@example.com" not in out["answer"] and "6693408639" not in out["answer"]


async def test_slow_generation_is_cancelled_and_answered_from_the_source():
    import asyncio

    class Slow(FakeLLM):
        async def stream(self, messages, max_tokens=600):
            await asyncio.sleep(0.2)
            yield "Call the rapid response team for systolic blood pressure below 90 or heart rate above 130 [1]."

    d, _ = deps([RRT_P], llm=Slow(), settings=Settings(_env_file=None, llm_answer_timeout_seconds=0.01))
    out = final(await run("What are the rapid response criteria?", d))
    assert out["fallback"] == "provider_unavailable" and out["receipt"]["error"] == "TimeoutError"
    assert out["answer"].startswith("Call the rapid response team") and out["cited"] == [1]


async def test_background_follow_up_is_answered_from_resume_when_generation_fails():
    contact = passage(1, "MANOJ GANJIGATTE MANJUNATHA\nContact Manoj at manoj@example.com.",
                      title="Manoj GM Resume SWE", score=0.4)
    work = passage(2, "Built an incident automation service and trained engineers in site reliability.",
                   title="Manoj GM Resume SWE", score=0.15)
    d, _ = deps([contact, work], llm=FakeLLM(lambda m: ""))

    async def history(user, conversation_id):
        return [("who is Manoj", "MANOJ GANJIGATTE MANJUNATHA [1]")]

    d.history = history
    out = final(await run("what is his background", d))
    assert out["fallback"] == "provider_unavailable" and out["receipt"]["mode"] == "extractive"
    assert "Built an incident automation service" in out["answer"] and out["cited"] == [2]
    assert "manoj@example.com" not in out["answer"]


async def test_provider_status_is_retained_in_the_failure_receipt():
    class Limited(FakeLLM):
        async def stream(self, messages, max_tokens=600):
            raise ProviderUnavailable("Shared upstream quota", status_code=429)
            yield ""

    d, _ = deps([RRT_P], llm=Limited())
    out = final(await run("What are the rapid response criteria?", d))
    assert out["receipt"]["provider_status"] == 429
    assert out["cited"] and out["fallback"] == "provider_unavailable"


async def test_patient_data_is_refused_by_default_and_never_searched_or_sent():
    llm = FakeLLM()
    d, _ = deps([passage(1, SEPSIS)], llm=llm)
    searched = []
    original = d.retrieve

    async def spy(user, question, label):
        searched.append(question)
        return await original(user, question, label)
    d.retrieve = spy
    events = await run("John Smith MRN 4471203 has a fever, what now?", d)
    out = final(events)
    assert out["fallback"] == "phi_blocked" and not searched and not llm.calls
    assert next(e.data for e in events if e.type == "phi")["notice"].startswith("Not sent: found a name")


async def test_personal_details_in_passages_are_masked_before_the_model_sees_them():
    llm = FakeLLM()
    d, _ = deps([passage(1, "Escalate to Maria Gonzalez on 555-123-4567 or maria.g@example.org [policy].",
                         title="Escalation Contacts", score=0.6)], llm=llm)
    events = await run("Who do I escalate to?", d)
    sent = str(llm.calls)
    assert "Maria Gonzalez" not in sent and "555-123-4567" not in sent and "maria.g@example.org" not in sent
    assert final(events)["receipt"]["pii_masked"] == 1
