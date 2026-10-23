"""Covers: AG-3. UX decision P1: abbreviations must not split a sentence ("C. difficile" became "difficile. [1]")."""
from assistant.citations import verify
from assistant.text import sentences
from tests.unit.test_answer_pipeline import passage


def test_species_initial_does_not_split():
    out = sentences("Use soap and water for C. difficile. Wash for 40 seconds. [1]")
    assert out == ["Use soap and water for C. difficile.", "Wash for 40 seconds. [1]"]


def test_titles_and_latin_abbreviations_do_not_split():
    assert len(sentences("Dr. Rao reviews the order. Then sign it.")) == 2
    assert len(sentences("Check glucose (e.g. fingerstick) now. Recheck in 15 minutes.")) == 2
    assert len(sentences("Use a mask, i.e. a surgical mask, in droplet rooms.")) == 1
    assert len(sentences("Call ext. 4444 now.")) == 1


def test_ordinary_sentences_still_split():
    assert sentences("Heart rate above 90. Respiratory rate above 20.") == [
        "Heart rate above 90.", "Respiratory rate above 20."]
    assert len(sentences("This is version 1. This replaces 15 seconds.")) == 2


def test_citation_after_period_stays_with_its_sentence():
    assert sentences("Rub for 20 seconds. [1] Wash for 40 seconds. [2]") == [
        "Rub for 20 seconds. [1]", "Wash for 40 seconds. [2]"]


def test_c_difficile_answer_survives_verification_whole():
    p = passage(1, "Use soap and water when caring for patients with suspected or confirmed C. difficile.")
    report = verify("Use soap and water when caring for patients with suspected or confirmed C. difficile. [1]", [p])
    assert report.removed == 0 and report.kept_text.endswith("C. difficile. [1]")


def test_a_claim_taken_from_the_section_heading_the_model_was_shown_is_verified():
    """The model is shown "[2] title — section"; a job title found only in the heading is still grounded in [2]."""
    from assistant.types import Passage
    p = Passage(2, "c2", "d", "Jane Doe Resume", 1, "Jane Doe Resume > Software Engineer 1, Site Reliability", 1,
                "internal", ", halving rescheduling from 10% to 5% and preventing operational overload.", 0.2)
    report = verify("Jane works as a Software Engineer, Site Reliability [2].", [p])
    assert report.removed == 0 and report.cited_ids == [2]


def test_a_claim_found_nowhere_in_what_the_model_was_shown_is_still_removed():
    from assistant.types import Passage
    p = Passage(2, "c2", "d", "Jane Doe Resume", 1, "Jane Doe Resume > Software Engineer", 1, "internal",
                "Designed an incident automation service.", 0.2)
    assert verify("Jane is a cardiothoracic surgeon in Boston [2].", [p]).removed == 1
