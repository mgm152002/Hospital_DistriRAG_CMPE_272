"""Covers: CR-3, CR-4 (stable chunking), E4-2."""
from pipeline.stages.chunk import split

MD = """# Hand Hygiene Policy

## Purpose
Clean hands prevent infection.

## Procedure
### Alcohol rub
Rub all surfaces of both hands for 20 to 30 seconds until dry.
"""


def test_markdown_sections():
    pieces = split([MD], markdown=True)
    sections = [p.section for p in pieces]
    assert "Hand Hygiene Policy > Purpose" in sections
    assert "Hand Hygiene Policy > Procedure > Alcohol rub" in sections
    rub = next(p for p in pieces if p.section.endswith("Alcohol rub"))
    assert "20 to 30 seconds" in rub.text and rub.page == 1


def test_windows_respect_size_and_overlap():
    text = " ".join(f"word{i}" for i in range(600))
    pieces = split([text], markdown=False, size=800, overlap=100)
    assert all(len(p.text) <= 800 for p in pieces) and len(pieces) >= 4
    assert pieces[0].text[-50:].split()[-1] in pieces[1].text


def test_chunker_messy_inputs():
    """Review Focus 5: no headings, one huge line, CRLF-normalised text, empty pages."""
    assert split(["plain text without any heading at all."], markdown=True)[0].section is None
    huge = split(["x" * 50_000], markdown=False)
    assert all(0 < len(p.text) <= 800 for p in huge) and len(huge) >= 62
    pages = split(["Page one text.", "", "   ", "Page four text."], markdown=False)
    assert [p.page for p in pages] == [1, 4]
    assert all(p.text.strip() for p in pages)


def test_pdf_heading_detection():
    pieces = split(["1. Purpose\nTo keep patients safe.\n2. Procedure\nCheck two identifiers."], markdown=False)
    assert pieces[0].section in ("1. Purpose", "2. Procedure")


def test_split_is_deterministic():
    assert split([MD], markdown=True) == split([MD], markdown=True)


def test_heading_only_blocks_are_not_chunks():
    """Regression (AT-14): a document title directly above a numbered heading must not become its own chunk."""
    pieces = split(["Sepsis Screening and Escalation Protocol\n\n1. Purpose\nEarly recognition saves lives.\n"
                    "2. Screening criteria\nScreen when two or more are present."], markdown=False)
    assert all(p.text not in ("Sepsis Screening and Escalation Protocol", "1. Purpose") for p in pieces)
    assert any("Early recognition" in p.text for p in pieces)
