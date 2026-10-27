"""Covers: FR-1 (safe storage keys)."""
from common.blob import safe_key


def test_safe_key_strips_traversal():
    key = safe_key("originals", "d1", "v1", "../../etc/passwd")
    assert ".." not in key and key.startswith("originals/d1/v1/")


def test_safe_key_keeps_readable_names():
    assert safe_key("originals", "d", "v", "Hand Hygiene v2.PDF") == "originals/d/v/Hand_Hygiene_v2.PDF"
