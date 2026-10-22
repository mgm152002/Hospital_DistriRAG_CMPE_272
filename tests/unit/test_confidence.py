"""Covers: AG-5. UX decision P2: High must cover verbatim, verified answers (14 correct answers scored below High)."""
from assistant.confidence import score
from common.config import Settings

HASHING = Settings(_env_file=None)
MINILM = Settings(_env_file=None, embed_provider="minilm")


def test_verbatim_single_source_answer_with_a_good_match_is_high():
    assert score([0.5], 1.0, 1, HASHING, verbatim=1.0).band == "High"


def test_good_hashing_match_is_high_even_without_the_verbatim_signal():
    assert score([0.57], 1.0, 1, HASHING).band == "High"


def test_weak_match_is_not_high_even_when_verbatim():
    assert score([0.27], 1.0, 1, HASHING, verbatim=1.0).band != "High"


def test_no_verified_citation_is_always_low():
    assert score([0.9], 0.0, 1, HASHING, verbatim=1.0).band == "Low"


def test_verbatim_never_lowers_the_score():
    base = score([0.4], 1.0, 1, HASHING).score
    assert score([0.4], 1.0, 1, HASHING, verbatim=1.0).score >= base


def test_two_agreeing_documents_still_score_at_least_as_high():
    assert score([0.4, 0.4], 1.0, 2, HASHING).score >= score([0.4], 1.0, 1, HASHING, verbatim=1.0).score


def test_minilm_scale_is_unchanged():
    assert score([0.5], 1.0, 1, MINILM).score == 57 and score([0.5], 1.0, 1, MINILM).band == "Medium"
