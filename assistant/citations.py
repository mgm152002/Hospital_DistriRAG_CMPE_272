"""Citation verification (AG-3): every factual sentence must cite a passage it actually overlaps with.

Answers may be markdown: paragraphs, "- " / "1. " list items and **bold** are kept line by line, so a verified list
stays a list. Two kinds of line carry no facts and are not counted: a short lead-in that ends with a colon
("The policy lists three steps:") and a plain statement of what the documents do not cover."""
import re
from dataclasses import dataclass

from assistant.text import CITE, overlap, sentences
from assistant.types import Passage

MIN_OVERLAP = 0.30
REPAIR_OVERLAP = 0.6  # an uncited sentence this close to one passage is that passage's words: cite it
END_CITE = re.compile(r"(?:\[\d+\]\s*)+[.!?]?$")
LIST_MARK = re.compile(r"^\s*(?:[-*+•]|\d{1,2}[.)])\s+")
HEADING = re.compile(r"^\s*#{1,6}\s+\S")
LEAD_IN_WORDS = 14
# "The passages do not cover wound care." is honest and useful: kept (without a citation), never counted as a claim.
DECLINE = re.compile(
    r"(?i)\b(?:do(?:es)?\s+not|don't|doesn't|did\s+not|cannot|can't|could\s+not|couldn't|unable\s+to)\s+(?:\w+\s+){0,3}?"
    r"(?:state|mention|contain|specify|include|address|cover|list|say|provide|answer|describe|find|define|give|offer)\b"
    r"|\b(?:not|no)\s+(?:found|covered|available|provided|stated|addressed|specified|answered)\b"
    r"|\bno\s+(?:information|mention|guidance)\b")
ABOUT_SOURCES = re.compile(r"(?i)\b(?:passages?|polic(?:y|ies)|documents?|sources?|guidance|guidelines?|information|"
                           r"procedures?|protocols?|text|library)\b")


@dataclass(frozen=True)
class CitationReport:
    kept_text: str
    cited_ids: list[int]
    coverage: float
    removed: int
    factual: int
    verbatim: float = 0.0


def is_decline(sentence: str) -> bool:
    """A sentence that says what the documents do not cover, rather than claiming a fact."""
    return bool(DECLINE.search(sentence) and ABOUT_SOURCES.search(sentence))


def _lead_in(line: str) -> bool:
    plain = CITE.sub("", line).strip().strip("*_ ")
    return bool(HEADING.match(line)) or (plain.endswith(":") and len(plain.split()) <= LEAD_IN_WORDS)


def verify(answer: str, passages: list[Passage]) -> CitationReport:
    by_index = {p.index: p for p in passages}
    # Section headings are part of the numbered source shown to the model (e.g. a resume's job title).
    source_text = {p.index: f"{p.section or ''}\n{p.text}" for p in passages}
    cited: set[int] = set()
    factual = removed = verbatim = kept_count = 0
    out_lines: list[str] = []
    pending_lead: str | None = None  # a lead-in is shown only if something under it survives

    for raw in answer.splitlines():
        line = raw.rstrip()
        if not line.strip():
            if out_lines and out_lines[-1] != "":
                out_lines.append("")
            continue
        if _lead_in(line) and not CITE.search(line):
            pending_lead = CITE.sub("", line).strip()
            continue
        marker = LIST_MARK.match(line)
        prefix = marker.group(0).lstrip() if marker else ""
        body = line[marker.end():] if marker else line.strip()
        kept_here: list[str] = []
        for sentence in sentences(body):
            numbers = [int(n) for n in CITE.findall(sentence)]
            if not numbers and passages:
                best = max(passages, key=lambda p: overlap(sentence, source_text[p.index]))
                if overlap(sentence, source_text[best.index]) >= REPAIR_OVERLAP:
                    text = sentence.rstrip()
                    end = text[-1] if text[-1] in ".!?" else ""
                    sentence = f"{text[:-1] if end else text} [{best.index}]{end}"
                    numbers = [best.index]
            valid = [n for n in numbers if n in by_index]
            source = " ".join(source_text[n] for n in valid)
            # The marker must close the sentence: "... [1] and sepsis is confirmed." must not borrow [1] for its tail.
            if (valid and len(valid) == len(numbers) and END_CITE.search(sentence.rstrip("*_ "))
                    and overlap(sentence, source) >= MIN_OVERLAP):
                factual += 1
                kept_here.append(sentence)
                cited.update(valid)
                kept_count += 1
                verbatim += overlap(sentence, source) >= 0.8
            elif is_decline(sentence):
                kept_here.append(re.sub(r"\s+([.!?])", r"\1", CITE.sub("", sentence)).strip())
            else:
                factual += 1
                removed += 1
        if kept_here:
            if pending_lead:
                out_lines.append(pending_lead)
            pending_lead = None
            out_lines.append(prefix + " ".join(kept_here))
    while out_lines and out_lines[-1] == "":
        out_lines.pop()
    coverage = (factual - removed) / factual if factual else 0.0
    return CitationReport("\n".join(out_lines), sorted(cited), coverage, removed, factual,
                          verbatim / kept_count if kept_count else 0.0)
