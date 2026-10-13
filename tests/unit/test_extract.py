"""Covers: AG-3, RL-10. UX decisions P1: when the model cannot be used or checked, show the best sentence, cited."""
from assistant.extract import emergency_lead, extract
from tests.unit.test_answer_pipeline import passage

HAND = passage(1, "Rub all surfaces of both hands with alcohol-based hand rub for 20 to 30 seconds until dry. "
                  "This replaces the 15-second guidance in version 1.", title="Hand Hygiene Policy")
VISIT = passage(1, "General visiting hours are 7:00 to 21:00 every day. This replaces the 8:00 to 20:00 hours "
                   "in version 1.", title="Visitor Policy")
BANNER = passage(2, "SYNTHETIC — FOR DEMONSTRATION ONLY — NOT CLINICAL GUIDANCE\nHand hygiene prevents infection.")
CODE = passage(1, "A patient who is unresponsive and not breathing normally needs a Code Blue.\n"
                  "Dial extension 5555 and state \"Code Blue\" with the unit and room number. "
                  "Start chest compressions immediately.", title="Code Blue Procedure")


def test_picks_the_sentence_that_answers_not_the_supersession_note():
    result = extract("How long do I rub hands with alcohol gel?", [HAND])
    assert result.text.startswith("Rub all surfaces of both hands with alcohol-based hand rub for 20 to 30 seconds")
    assert "[1]" in result.text and result.cited == [1]


def test_visiting_hours_prefers_the_current_hours_sentence():
    result = extract("whats the visiting hours policy", [VISIT])
    assert result.text.splitlines()[0].startswith("General visiting hours are 7:00 to 21:00 every day.")


def test_sentences_are_verbatim_and_cited():
    result = extract("rub hands alcohol", [HAND], limit=2)
    for line in result.text.splitlines():
        sentence = line.rsplit(" [", 1)[0]
        assert sentence in HAND.text


def test_demo_banner_is_never_quoted():
    assert "SYNTHETIC" not in extract("hand hygiene infection", [BANNER]).text


def test_no_passages_gives_nothing():
    assert extract("anything", []).text == "" and extract("anything", []).cited == []


def test_limit_and_length_are_respected():
    result = extract("hand rub alcohol seconds dry surfaces", [HAND], limit=1)
    assert len(result.text.splitlines()) == 1 and len(result.text) <= 400


def test_emergency_lead_is_the_action_with_the_number():
    lead = emergency_lead([CODE])
    assert lead.text.startswith('Dial extension 5555 and state "Code Blue"') and lead.cited == [1]


def test_emergency_lead_empty_without_an_action_sentence():
    assert emergency_lead([HAND]).text == ""


def test_a_supersession_note_is_never_quoted_beside_the_current_value():
    """Quoting "This replaces the 8:00 to 20:00 hours in version 1" puts the retired hours next to the current ones."""
    for question, passage_ in (("whats the visiting hours policy", VISIT), ("how long to rub hands", HAND)):
        text = extract(question, [passage_], limit=2).text
        assert "replaces" not in text and "8:00 to 20:00" not in text and "15-second" not in text


def test_a_passage_that_is_only_a_supersession_note_is_still_quotable():
    only = passage(1, "This replaces the earlier hand hygiene guidance in version 1.", title="Hand Hygiene Policy")
    assert extract("hand hygiene guidance", [only]).text.startswith("This replaces the earlier")


def test_a_second_quote_must_share_words_with_the_question():
    anticoag = passage(1, "Consider reversal for life-threatening bleeding or an emergency procedure in a patient "
                          "taking an anticoagulant.", title="Anticoagulation Reversal Reference", score=0.6)
    diet = passage(2, "Weigh yourself every morning after using the toilet and before breakfast.", doc="d2",
                   title="Discharge Instructions: Heart Failure", score=0.2)
    result = extract("When should anticoagulation reversal be considered?", [anticoag, diet], limit=2)
    assert result.cited == [1] and "Weigh yourself" not in result.text


def test_the_best_quote_is_kept_even_when_it_shares_no_words():
    only = passage(1, "Dial extension 5555 and state the unit and room number.", title="Code Blue Procedure")
    assert extract("who do I phone", [only]).cited == [1]


FALL = passage(1, "Assess fall risk with the Morse Fall Scale on admission, every shift, after a fall, and after any "
                  "change in condition. A Morse score of 45 or higher means high fall risk.",
               title="Fall Risk Assessment and Prevention", score=0.6)


def test_a_schedule_question_quotes_the_sentence_that_gives_the_schedule():
    result = extract("What is the fall risk reassessment schedule?", [FALL], limit=1)
    assert result.text.startswith("Assess fall risk with the Morse Fall Scale on admission, every shift")


def test_a_threshold_question_still_quotes_the_threshold():
    result = extract("What Morse score means high fall risk?", [FALL], limit=1)
    assert result.text.startswith("A Morse score of 45 or higher")


def test_the_schedule_sentence_beats_a_higher_ranked_chunk_that_merely_mentions_the_topic():
    """Live: the 'Risk levels' chunk outranked 'Assessment', and its threshold sentence won on score alone."""
    assessment = passage(1, "Assess fall risk with the Morse Fall Scale on admission, every shift, after a fall, and "
                            "after any change in condition.", title="Fall Risk Assessment and Prevention", score=0.5)
    levels = passage(2, "A Morse score of 45 or higher means high fall risk. A score of 25 to 44 means moderate risk.",
                     title="Fall Risk Assessment and Prevention", score=0.6)
    result = extract("What is the fall risk reassessment schedule?", [assessment, levels], limit=1)
    assert result.text.startswith("Assess fall risk with the Morse Fall Scale on admission, every shift")
    assert result.cited == [1]
