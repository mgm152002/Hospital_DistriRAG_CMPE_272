"""Covers: CP-6 (deletion is deliberate). UX decision P1: test leftovers must not appear in staff search."""
from scripts.clean_demo import LEFTOVER, plan

MANAGED = {"Hand Hygiene Policy", "Visitor Policy"}


def doc(title, document_id=None):
    return {"document_id": document_id or title, "title": title}


def test_managed_documents_are_never_touched():
    delete, kept = plan([doc("Hand Hygiene Policy"), doc("Visitor Policy")], MANAGED, LEFTOVER)
    assert delete == [] and kept == []


def test_known_test_leftovers_are_selected_for_deletion():
    docs = [doc("Quiet Hours Policy mwwtx734"), doc("Synthetic Ward Guide 1795659174549"),
            doc("Live Demo Visitor Policy 19:19:02"), doc("Acceptance Policy"), doc("Hand Hygiene Policy")]
    delete, kept = plan(docs, MANAGED, LEFTOVER)
    assert [d["title"] for d in delete] == ["Acceptance Policy", "Quiet Hours Policy mwwtx734",
                                            "Synthetic Ward Guide 1795659174549"]
    # Nothing in the repo creates this title, so it may be someone's hand-made demo document: report, never delete.
    assert [d["title"] for d in kept] == ["Live Demo Visitor Policy 19:19:02"]


def test_an_unmanaged_document_that_does_not_look_like_a_test_is_kept_and_reported():
    delete, kept = plan([doc("Ward 7 Parking Guide"), doc("Quiet Hours Policy abc")], MANAGED, LEFTOVER)
    assert [d["title"] for d in delete] == ["Quiet Hours Policy abc"]
    assert [d["title"] for d in kept] == ["Ward 7 Parking Guide"]


def test_a_custom_pattern_changes_what_counts_as_a_leftover():
    delete, kept = plan([doc("Ward 7 Parking Guide")], MANAGED, r"^Ward 7")
    assert [d["title"] for d in delete] == ["Ward 7 Parking Guide"] and kept == []
