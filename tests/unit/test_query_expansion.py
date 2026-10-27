"""Covers: FR-8. UX decision P1: clinical shorthand, colloquial wording, irregular verbs and a small glossary."""
import pytest

from search.abbreviations import expand

CASES = [
    ("HH duration with ABHR?", ["hand hygiene", "alcohol-based hand rub"]),
    ("how often do i turn pts so they dont get bedsores", ["pressure injury", "reposition", "patients"]),
    ("My patient just fell getting out of bed", ["fall"]),
    ("I just got stuck with a used needle", ["sharps injury", "needlestick"]),
    ("ECG door-to time for CP?", ["chest pain"]),
    ("LKW window for stroke alert", ["last known well"]),
    ("CS count discrepancy - report window?", ["controlled substance"]),
    ("¿Cuál es el horario de visitas?", ["visiting hours"]),
    ("A family member asked when they can shower after surgery", ["post-op wound care"]),
    ("who do I call for a code", ["code blue", "rapid response"]),
    ("vanc dose 70kg", ["vancomycin"]),
    ("CDI precautions", ["c. difficile"]),
    ("What is the fall risk reassessment schedule?", ["assessment", "every shift"]),
    ("how often should pain be reassessed", ["assess", "every shift"]),
]


@pytest.mark.parametrize("query,needles", CASES)
def test_expansion_adds_the_words_the_policy_uses(query, needles):
    expanded = expand(query).lower()
    assert expanded.startswith(query.lower())
    for needle in needles:
        assert needle in expanded, (needle, expanded)


def test_expansion_is_idempotent():
    for query, _ in CASES:
        once = expand(query)
        assert expand(once) == once


@pytest.mark.parametrize("query", ["visiting hours", "What is the Morse Fall Scale threshold?", "hand hygiene gloves"])
def test_plain_policy_wording_is_unchanged(query):
    assert expand(query) == query


def test_short_words_are_matched_whole_only():
    assert "patient" not in expand("kept the optimum dose").lower()
    assert "chest pain" not in expand("cpap setup").lower()


# ---- lexical terms: expanded lay wording must not dilute the match score ---------------------------------------

def test_expanded_lay_wording_and_filler_do_not_count_against_the_match():
    from search.abbreviations import lexical_terms
    terms = lexical_terms("I just got stuck with a used needle")
    assert not {"stuck", "just", "got", "used"} & set(terms)
    assert {"sharps", "injury", "needlestick", "exposure"} <= set(terms)


def test_abbreviation_triggers_are_replaced_by_their_expansion():
    from search.abbreviations import lexical_terms
    assert lexical_terms("HH duration") == ["duration", "hand", "hygiene"]


def test_a_query_that_needs_no_expansion_keeps_its_terms():
    from search.abbreviations import lexical_terms
    assert lexical_terms("visiting hours policy") == ["visiting", "hours", "policy"]


def test_terms_are_never_all_dropped():
    from search.abbreviations import lexical_terms
    assert lexical_terms("just now") == ["just", "now"]
