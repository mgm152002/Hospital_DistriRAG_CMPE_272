"""Covers: CP-3."""
import pathlib

import yaml

from assistant.phi import screen

CASES = yaml.safe_load((pathlib.Path(__file__).parent / "data" / "phi_cases.yaml").read_text())


def test_phi_recall_at_least_95_percent():
    hits = 0
    for case in CASES["with_phi"]:
        found = {f.type for f in screen(case["text"]).findings}
        hits += set(case["types"]) <= found
    assert hits / len(CASES["with_phi"]) >= 0.95


def test_phi_false_positives_at_most_10_percent():
    false = [t for t in CASES["without_phi"] if screen(t).findings]
    assert len(false) / len(CASES["without_phi"]) <= 0.10, false


def test_redaction_replaces_values():
    result = screen("Patient John Smith MRN 00482913 fell")
    assert "John" not in result.redacted and "00482913" not in result.redacted
    assert "[REDACTED-NAME]" in result.redacted and "[REDACTED-MRN]" in result.redacted


def test_no_phi_returns_text_unchanged():
    text = "What is our hand hygiene policy?"
    assert screen(text).redacted == text


def test_place_and_institution_names_are_not_people():
    for text in ["an M.S. at San Jose State University", "trained at George Washington University",
                 "transferred from St. Paul Hospital"]:
        assert not screen(text).found, text


def test_bare_patient_names_are_still_caught():
    assert screen("Maria Gonzalez has a fever").found
    assert screen("ask Jose Ramirez about it").found


def test_a_stated_name_is_caught_even_when_unlisted_or_lowercase():
    for text in ["Hi my patients name is Manoj", "my patient's name is manoj and he fell", "patient name: Ravi Kumar",
                 "his name was Lee, what now?", "the patient's full name is Aarav Sharma"]:
        result = screen(text)
        assert result.found and "NAME" in {f.type for f in result.findings}, text
    assert "Ravi Kumar" not in screen("patient name: Ravi Kumar").redacted


def test_policy_wording_about_names_is_not_a_name():
    for text in ["the patient name is required on every label", "Check that the patient's name is correct",
                 "the name is not enough to identify a patient"]:
        assert not screen(text).found, text


def test_a_stated_personal_field_is_caught_whatever_its_value_looks_like():
    for text, kind in [("My patiendts address is 28N", "ADDRESS"), ("she lives at 28N", "ADDRESS"),
                       ("his phone number is 6693408", "PHONE"), ("her dob is March 4 1990", "DOB"),
                       ("address: 12B Lake View", "ADDRESS")]:
        assert kind in {f.type for f in screen(text).findings}, text


def test_policy_wording_about_personal_fields_is_left_alone():
    for text in ["the address is required on every referral", "the phone number is on the badge",
                 "Age is a risk factor for falls", "the patient lives in a care home",
                 "What number do I call for a code blue?", "Who is the contact for infection control?"]:
        assert not screen(text).found, text
