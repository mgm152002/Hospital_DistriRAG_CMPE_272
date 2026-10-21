"""Covers: FR-8 (retrieval quality for clinical shorthand)."""
from search.abbreviations import expand


def test_vital_sign_abbreviations_expand():
    q = expand("Patient has temp 39C, HR 125, BP 85/50")
    assert "heart rate" in q and "blood pressure" in q and "temperature" in q and q.startswith("Patient has temp")


def test_no_abbreviations_unchanged():
    assert expand("visiting hours") == "visiting hours"


def test_expansion_is_whole_word_only():
    assert "heart rate" not in expand("chronic hrs")
