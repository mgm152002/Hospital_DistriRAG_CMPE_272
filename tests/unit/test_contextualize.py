"""Covers: FR-10. UX decision: a follow-up ("where do I document it?") has no topic words, so retrieval must borrow
the previous question or it can never find anything."""
import asyncio

from assistant.contextualize import condense, retrieval_query
from common.llm import ProviderInfo
from common.llm.fake import FakeLLM, NoLLM

PREVIOUS = [("Who decides on contrast premedication for a prior reaction?", "The radiologist decides. [1]")]


def test_pronoun_follow_up_borrows_the_previous_question():
    out = retrieval_query("where do I document it?", PREVIOUS)
    assert "contrast premedication" in out and out.endswith("where do I document it?")


def test_possessive_follow_up_keeps_the_person_being_discussed():
    history = [("who is manoj", "Manoj is Manoj Ganjigatte Manjunatha [1].")]
    for question in ("whats his background", "What's her experience?", "What is their education?",
                     "Tell me about him"):
        assert "manoj" in retrieval_query(question, history), question


def test_retrying_a_failed_follow_up_keeps_the_original_subject():
    history = [("who is manoj", "Manoj is Manoj Ganjigatte Manjunatha [1]."),
               ("whats his background", "I couldn't find this in approved documents you can access.")]
    query = retrieval_query("whats his background", history)
    assert "manoj" in query
    assert query.count("whats his background") == 1


def test_a_chain_of_follow_ups_keeps_its_subject_and_intermediate_topic():
    history = [("who is manoj", "Manoj is Manoj Ganjigatte Manjunatha [1]."),
               ("whats his background", "He is a software engineer [1].")]
    query = retrieval_query("and where did he study?", history)
    assert "manoj" in query and "background" in query


def test_conjunction_follow_ups_borrow_it_too():
    for question in ("and with soap?", "what about a stroke alert, same number?", "can one of them stay the night?"):
        assert "contrast premedication" in retrieval_query(question, PREVIOUS), question


def test_a_standalone_question_is_left_alone():
    for question in ("What are the visiting hours?", "falls?", "How do I request patient transport?",
                     "Does this patient have sepsis?"):
        assert retrieval_query(question, PREVIOUS) == question


def test_without_history_nothing_changes():
    assert retrieval_query("where do I document it?", []) == "where do I document it?"


def test_only_the_most_recent_user_question_is_borrowed():
    history = [("How long to rub hands?", "20 s [1]"), *PREVIOUS]
    out = retrieval_query("and where do I document it?", history)
    assert "contrast" in out and "rub hands" not in out


def test_placeholders_in_the_borrowed_question_are_dropped():
    out = retrieval_query("and then?", [("[REDACTED-NAME] fell in [REDACTED-LOCATION], what now?", "x")])
    assert "[REDACTED" not in out and "fell" in out


def test_a_long_question_is_never_treated_as_a_follow_up():
    long = ("What does the visitor policy say about it when a visitor has a fever and a cough and wants to stay "
            "overnight with the patient")
    assert retrieval_query(long, PREVIOUS) == long


def _local(llm):
    llm.info = ProviderInfo("local-model", "ollama", "", "m", "", False, False, False, "local")
    return llm


async def test_condense_uses_the_model_rewrite_and_strips_its_label():
    llm = _local(FakeLLM(lambda m: 'Query: "contrast premedication documentation"\nextra line'))
    assert await condense("where do I document it?", PREVIOUS, llm) == "contrast premedication documentation"
    sent = str(llm.calls[0])
    assert "contrast premedication" in sent and "where do I document it?" in sent


async def test_condense_falls_back_to_the_heuristic_without_a_real_model_or_history():
    heuristic = retrieval_query("where do I document it?", PREVIOUS)
    assert await condense("where do I document it?", PREVIOUS, FakeLLM()) == heuristic
    assert await condense("where do I document it?", PREVIOUS, NoLLM()) == heuristic
    llm = _local(FakeLLM())
    assert await condense("where do I document it?", [], llm) == "where do I document it?" and llm.calls == []


async def test_condense_falls_back_on_timeout_and_on_empty_output():
    class Slow(FakeLLM):
        async def stream(self, messages, max_tokens=600):
            await asyncio.sleep(1)
            yield "too late"
    heuristic = retrieval_query("where do I document it?", PREVIOUS)
    assert await condense("where do I document it?", PREVIOUS, _local(Slow()), timeout=0.01) == heuristic
    assert await condense("where do I document it?", PREVIOUS, _local(FakeLLM(lambda m: "  "))) == heuristic
