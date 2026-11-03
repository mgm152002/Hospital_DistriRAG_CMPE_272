"""Covers: CP-3. UX decision P0-1: bare patient names, ages and bed/room numbers are identifiers too."""
import pytest

from assistant.phi import screen

MUST_REDACT = [
    ("John Smith MRN 4471203 in room 12 fell, what now?", ["John Smith", "4471203", "room 12"]),
    ("bed 4 Smith, 71yo male, fell", ["Smith", "71yo", "bed 4"]),
    ("Maria Gonzalez fell last night and needs an incident report", ["Maria Gonzalez"]),
    ("my patient Robert O'Brien is on contact precautions", ["O'Brien"]),
    ("Smith, John needs a transport request", ["Smith", "John"]),
    ("Can an 84 year old male, Daniel Park, have visitors after 9pm?", ["84 year old", "Daniel Park"]),
    ("Linda Nguyen DOB 03/14/1952 asked about visiting hours", ["Linda Nguyen", "03/14/1952"]),
    ("room 3B patient is a 67 y/o female", ["room 3B", "67 y/o"]),
]

MUST_NOT_FLAG = [
    "What does the Hand Hygiene Policy say about gloves?",
    "Rapid Response Team activation criteria",
    "Code Blue procedure in the Emergency Department",
    "Contact and Droplet Isolation Precautions for MRSA",
    "Northbridge Synthetic Hospital visiting hours",
    "What is the Morse Fall Scale threshold for high risk?",
    "What Braden Scale score means at risk?",
    "Glasgow Coma Scale and Pasero Opioid-Induced Sedation Scale",
    "How does the fall policy treat patients over 65 years old?",
    "Where do I store the isolation room signage?",
    "Joint Commission patient identification requirements",
    "Mark the incident in the reporting system",
    "Will the policy change next month?",
]


@pytest.mark.parametrize("text,values", MUST_REDACT)
def test_identifiers_are_redacted(text, values):
    result = screen(text)
    assert result.found
    for value in values:
        assert value not in result.redacted, (value, result.redacted)


@pytest.mark.parametrize("text", MUST_NOT_FLAG)
def test_policy_language_is_left_alone(text):
    result = screen(text)
    assert not result.found and result.redacted == text, result.redacted


def test_search_text_drops_placeholders_but_keeps_the_question():
    result = screen("John Smith MRN 4471203 in room 12 fell, what now?")
    assert "[REDACTED" not in result.search_text
    assert "fell" in result.search_text and "what now" in result.search_text
    assert "  " not in result.search_text


def test_search_text_of_clean_question_is_unchanged():
    assert screen("How long to rub hands?").search_text == "How long to rub hands?"


def test_notice_names_what_was_removed_in_plain_words():
    notice = screen("John Smith MRN 4471203 in room 12 fell").notice
    assert notice == "Removed a name, a medical record number and a room or bed number before searching."


def test_notice_is_empty_when_nothing_found():
    assert screen("visiting hours").notice == ""


def test_a_phone_number_written_without_separators_is_found():
    for text in ("call +1 6693408639 tonight", "her number is 6693408639", "+16693408639"):
        assert "PHONE" in {f.type for f in screen(text).findings}, text


def test_short_numbers_and_extensions_are_not_phone_numbers():
    for text in ("Dial extension 4444 now", "Wash for 40 to 60 seconds", "Room 1204 isolation sign"):
        assert "PHONE" not in {f.type for f in screen(text).findings}, text
