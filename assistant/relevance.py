"""Does the retrieved text answer the question? (pure)

The citation check proves a sentence matches its passage; it cannot tell that the passage is about something else.
A DVT question once returned "They only list droplet precautions [1]" with a citation. Two guards close that gap:
a lexical coverage gate for weak retrieval, and a hedge detector for model answers that decline in their first sentence.
"""
import re

from assistant.text import SUPERSEDED, content_words, sentences, word_forms
from assistant.types import Passage
from search.abbreviations import concepts, expand
from search.noise import FILLER

GENERIC = {"patient", "patients", "staff", "hospital", "unit", "care", "give", "need", "use", "check", "policy",
           "procedure", "protocol", "document", "every", "must", "follow", "per", "after", "before"}
NOISE = content_words(" ".join(GENERIC | FILLER))
TITLE_GENERIC = content_words("prevention assessment management administration notification identification "
                              "instructions reference workflow requirements guidance pathway")
MIN_COVERAGE = 0.4
QUOTE_MIN = 0.6  # a quoted sentence is shown as an answer only if it covers this share of what was asked
# Words an expansion shares with unrelated policies: "sharps injury" must not make every injury sentence relevant.
GENERIC_POLICY_WORDS = content_words("injury exposure care team precautions")
STRONG_SHARE = 0.5  # a top score this far between min_relevance and 1.0 is trusted without a lexical check
PERSONAL_BACKGROUND = re.compile(r"(?i)\b(?:his|her|their|professional|educational)\s+background\b")
BACKGROUND_SOURCES = content_words("resume résumé curriculum vitae education experience qualifications")

HEDGE = re.compile(
    r"(?i)\b(?:do(?:es)?\s+not|don't|doesn't|did\s+not|cannot|can't|could\s+not|couldn't|unable\s+to)\s+(?:\w+\s+){0,3}?"
    r"(?:state|mention|contain|specify|include|address|cover|list|say|provide|answer|describe|find|define|give|offer)\b"
    r"|\bonly\s+(?:list|lists|mention|mentions|cover|covers|describe|describes|state|states)\b"
    r"|\b(?:not|no)\s+(?:found|covered|available|provided|stated|addressed|specified|answered)\b"
    r"|\bno\s+(?:information|mention)\b")


def is_hedge(answer: str) -> bool:
    """True when the lead sentence of a model answer declines to answer ("the passages do not state ...")."""
    lead = sentences(answer)[:1]
    return bool(lead and HEDGE.search(lead[0]))


def only_changelog(answer: str) -> bool:
    """True when every sentence is a note about a superseded version ("This replaces the 15-second guidance ...")."""
    parts = sentences(answer)
    return bool(parts) and all(SUPERSEDED.search(p) for p in parts)


def coverage(question: str, passages: list[Passage]) -> float:
    """Share of the question's distinctive words (or their known expansions) found in the passages."""
    terms = content_words(question) - NOISE
    if not terms:
        return 1.0
    expanded = content_words(expand(question)) - NOISE
    pool = content_words(" ".join(f"{p.title} {p.section or ''} {p.text}" for p in passages))
    return min(1.0, len((terms | expanded) & pool) / len(terms))


def quote_coverage(question: str, quote: str, source_title: str = "") -> float:
    """Share of the question's distinctive words that one quoted sentence covers, read with the title of the policy it
    is shown under. A lay phrase that the policy words differently ("stuck with a needle" / "sharps") counts as covered
    when the quote or its title uses the policy's distinctive words."""
    terms = content_words(question) - NOISE
    if not terms:
        return 1.0
    pool = content_words(f"{source_title} {quote}")
    covered = {t for t in terms if any(content_words(form) & pool for form in word_forms(t))}
    # A resume's experience/education is evidence for a person's background even without the literal word.
    # Keep this scoped to personal background: e.g. "background radiation dose" still needs radiation/dose evidence.
    if PERSONAL_BACKGROUND.search(question) and BACKGROUND_SOURCES & pool:
        covered |= {"background"} & terms
    for typed, policy in concepts(question):
        words = content_words(" ".join(policy))
        if (words - GENERIC_POLICY_WORDS or words) & pool:
            covered |= content_words(" ".join(typed)) & terms
    return len(covered) / len(terms)


def names_the_topic(question: str, passages: list[Passage]) -> bool:
    """A title or heading that shares a distinctive word (or its expansion) with the question: "fell" -> "Fall Risk"."""
    terms = (content_words(question) | content_words(expand(question))) - NOISE - TITLE_GENERIC
    return any(terms & (content_words(f"{p.title} {p.section or ''}") - NOISE - TITLE_GENERIC) for p in passages)


def supports_question(question: str, passages: list[Passage], min_relevance: float) -> bool:
    if not passages:
        return False
    strong = min_relevance + STRONG_SHARE * (1 - min_relevance)
    if max(p.score for p in passages) >= strong:
        return True
    return coverage(question, passages) >= MIN_COVERAGE or names_the_topic(question, passages)
