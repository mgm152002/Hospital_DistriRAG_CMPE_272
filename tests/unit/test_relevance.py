"""Covers: AG-2, AG-3. UX decision P0-4: a cited answer that does not answer the question is worse than no answer."""
from assistant.relevance import coverage, is_hedge, supports_question
from tests.unit.test_answer_pipeline import passage

ISOLATION = passage(1, "Use droplet precautions for influenza and pertussis. Wear a surgical mask within 2 metres "
                       "(6 feet) of the patient.", title="Contact and Droplet Isolation Precautions", score=0.15)
RRT = passage(1, "Call the rapid response team for systolic blood pressure below 90 mmHg, heart rate above 130.",
              title="Rapid Response Team Activation Criteria", score=0.43)
PRESSURE = passage(1, "Reposition at-risk patients at least every 2 hours, float heels, use a pressure-redistributing "
                      "mattress.", title="Pressure Injury Prevention", score=0.3)


def test_hedges_are_detected_only_in_the_lead_sentence():
    assert is_hedge("They only list droplet precautions for influenza and pertussis [1].")
    assert is_hedge("The provided passages do not state the rapid response criteria [1][2].")
    assert is_hedge("I could not find the answer in these passages.")
    assert not is_hedge("Rub for 20 to 30 seconds [1].")
    assert not is_hedge("Gloves do not replace hand hygiene [1]. Perform hand hygiene before gloving [1].")
    assert not is_hedge("Rub for 20 seconds [1]. The passages do not state a limit for gel volume [1].")


def test_unrelated_passage_has_low_coverage():
    assert coverage("What is our DVT prophylaxis protocol for surgical patients?", [ISOLATION]) < 0.4


def test_matching_passage_has_full_coverage():
    assert coverage("What are the rapid response criteria?", [RRT]) >= 0.9


def test_synonyms_count_toward_coverage():
    assert coverage("how often do i turn pts so they dont get bedsores", [PRESSURE]) >= 0.4


def test_weak_unrelated_retrieval_does_not_support_the_question():
    assert not supports_question("What is our DVT prophylaxis protocol for surgical patients?", [ISOLATION],
                                 min_relevance=0.15)


def test_strong_retrieval_is_trusted_even_when_wording_differs():
    strong = passage(1, "Reposition at-risk patients at least every 2 hours.", score=0.8)
    assert supports_question("how frequently should immobile people be moved", [strong], min_relevance=0.15)


def test_matching_weak_retrieval_is_supported():
    assert supports_question("What are the rapid response criteria?", [RRT], min_relevance=0.15)


FALL = passage(1, "Assess the patient for injury before moving them.", title="Fall Risk Assessment and Prevention",
               score=0.36)


def test_a_heading_that_names_the_topic_supports_a_weak_match():
    assert supports_question("My patient just fell getting out of bed. What do I do now?", [FALL], min_relevance=0.15)


def test_a_generic_heading_word_is_not_enough():
    pressure = passage(1, "Reposition at-risk patients at least every 2 hours.", title="Pressure Injury Prevention",
                       score=0.3)
    assert not supports_question("How do we prevent DVT in surgical patients?", [pressure], min_relevance=0.15)


def test_an_answer_made_only_of_changelog_notes_is_not_an_answer():
    from assistant.relevance import only_changelog
    assert only_changelog("This replaces the 15-second guidance in version 1. [1]")
    assert only_changelog("This replaces the old hours. [1] It supersedes version 1. [2]")
    assert not only_changelog("Rub for 20 to 30 seconds [1]. This replaces the 15-second guidance in version 1. [1]")
    assert not only_changelog("")


# ---- a quote must itself address the question ---------------------------------------------------------------------

def test_quote_coverage_separates_answers_from_near_misses():
    from assistant.relevance import QUOTE_MIN, quote_coverage
    wound = "should I rub alcohol on open wound on a patient"
    hand_rub = "Rub all surfaces of both hands with alcohol-based hand rub for 20 to 30 seconds until dry."
    assert quote_coverage(wound, hand_rub) < QUOTE_MIN  # shares "rub" and "alcohol", says nothing about wounds
    assert quote_coverage("What is our DVT prophylaxis protocol for surgical patients?",
                          "Wear a surgical mask within 2 metres (6 feet) of the patient.") < QUOTE_MIN
    for question, quote in [
        ("What are the rapid response criteria?", "Call the rapid response team for systolic blood pressure below 90."),
        ("whats the visiting hours policy", "General visiting hours are 7:00 to 21:00 every day."),
        ("How long do I rub hands with alcohol gel?", hand_rub),
        ("When should anticoagulation reversal be considered?",
         "Consider reversal for life-threatening bleeding in a patient taking an anticoagulant."),
    ]:
        assert quote_coverage(question, quote) >= QUOTE_MIN, question


def test_an_expanded_lay_phrase_counts_as_the_policy_concept_it_stands_for():
    from assistant.relevance import QUOTE_MIN, quote_coverage
    needle = "I just got stuck with a used needle"
    title = "Sharps Injury and Bloodborne Exposure"  # a quote is shown with its source, so the title is fair context
    assert quote_coverage(needle, "Dispose of sharps in a sharps container at the point of use.") >= QUOTE_MIN
    assert quote_coverage(needle, "Report the exposure to Occupational Health within 1 hour.", title) >= QUOTE_MIN
    assert quote_coverage(needle, "Weigh yourself every morning after using the toilet.") < QUOTE_MIN


def test_a_timing_question_is_answered_by_the_sentence_that_gives_the_timing():
    """"Reassessment schedule" and "assess ... every shift" say the same thing in different words."""
    from assistant.relevance import QUOTE_MIN, quote_coverage
    question = "What is the fall risk reassessment schedule?"
    quote = "Assess fall risk with the Morse Fall Scale on admission, every shift, after a fall, and after any change."
    assert quote_coverage(question, quote) >= QUOTE_MIN


def test_word_forms_match_across_re_prefix_and_ment_suffix():
    from assistant.relevance import quote_coverage
    assert quote_coverage("pressure injury reassessment", "Assess pressure injury risk every shift.") >= 0.99
    assert quote_coverage("what is the management", "Manage the airway.") >= 0.99


def test_the_open_wound_near_miss_is_still_rejected_after_loosening_word_forms():
    from assistant.relevance import QUOTE_MIN, quote_coverage
    assert quote_coverage("should I rub alcohol on open wound on a patient",
                          "Rub all surfaces of both hands with alcohol-based hand rub for 20 to 30 seconds until "
                          "dry.") < QUOTE_MIN



def test_a_generic_word_from_an_expansion_does_not_make_an_unrelated_quote_relevant():
    """"sharps injury" must not let every sentence about an injury answer a needlestick question."""
    from assistant.relevance import QUOTE_MIN, quote_coverage
    assert quote_coverage("What do I do after a needlestick injury?",
                          "Assess the patient for injury before moving them, notify the provider.") < QUOTE_MIN
    assert quote_coverage("What do I do after a needlestick injury?",
                          "Report the exposure to Occupational Health within 1 hour.",
                          "Sharps Injury and Bloodborne Exposure") >= QUOTE_MIN
    assert quote_coverage("What do I do after a needlestick injury?",
                          "Assess the patient for injury before moving them, notify the provider.",
                          "Fall Risk Assessment and Prevention") < QUOTE_MIN


def test_personal_background_question_recognizes_a_resume_as_context():
    from assistant.relevance import QUOTE_MIN, quote_coverage

    question = "who is Manoj what is his background"
    quote = "Built an incident automation service and trained engineers in site reliability."
    assert quote_coverage(question, quote, "Manoj GM Resume SWE") >= QUOTE_MIN
    assert quote_coverage(question, "Visitors must leave at 21:00.", "Visitor Policy") < QUOTE_MIN
    assert quote_coverage("what is the background radiation dose", quote, "Manoj GM Resume SWE") < QUOTE_MIN
