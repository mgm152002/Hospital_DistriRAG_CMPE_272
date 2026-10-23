"""Covers: FR-8, UX-2."""
from search.snippet import best_window, query_terms

TEXT = ("Purpose. This policy applies to all staff. " * 10
        + "Rub hands with alcohol-based rub for 20 to 30 seconds until dry. " + "Gloves are not a substitute. " * 10)


def test_snippet_highlights_terms():
    snippet, highlights = best_window(TEXT, query_terms("alcohol rub duration"), width=300)
    assert len(snippet) <= 302
    marked = [snippet[a:b].lower() for a, b in highlights]
    assert "alcohol" in marked and "rub" in marked


def test_query_terms_drop_stop_words():
    assert query_terms("How long should the alcohol rub last?") == ["long", "alcohol", "rub", "last"]


def test_no_terms_returns_start():
    snippet, highlights = best_window(TEXT, [], width=100)
    assert snippet.startswith("Purpose") and highlights == []
