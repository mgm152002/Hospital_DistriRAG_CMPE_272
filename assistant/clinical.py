"""Clinical-safety output check (AG-2): block diagnoses and patient-specific orders, except exact quotes of a
cited passage (a protocol's own criteria may say 'give oxygen')."""
import re
from dataclasses import dataclass, field

from assistant.text import CITE, sentences
from assistant.types import Passage

DIAGNOSIS = [
    re.compile(r"\b(the|this|your|my)\s+patient\s+(likely\s+|probably\s+|most likely\s+|definitely\s+|clearly\s+)?"
               r"(has|is having|is suffering from|is in)\b", re.I),
    re.compile(r"\bdiagnosis\s+(is|of)\b", re.I),
    re.compile(r"\bconsistent with (a diagnosis of|septic|sepsis|a stroke|an? mi)\b", re.I),
    re.compile(r"\b(he|she|they)\s+(likely|probably)\s+(has|have)\b", re.I),
]
ORDERS = [
    re.compile(r"\b(give|administer|start|push|hang|prescribe|infuse)\s+(\w+\s+){0,2}\d+(\.\d+)?\s?"
               r"(mg|mcg|g|units|ml|mL|mg/kg)\b", re.I),
    re.compile(r"\bI\s+(recommend|suggest|would)\s+(starting|giving|administering|prescribing|ordering)\b", re.I),
    re.compile(r"\byou should (give|administer|start|prescribe)\b", re.I),
]
QUOTE = re.compile(r'"([^"\n]+)"|“([^”\n]+)”|‘([^’\n]+)’')
ATTRIBUTION = re.compile(r"(?:our|the(?: hospital's)?)\s+(?:protocol|policy|procedure|document)\s+"
                         r"(?:says|states|lists|specifies|reads)\s*:?", re.I)


def _normalise_quote(text: str) -> str:
    return " ".join(text.split()).casefold().rstrip(".!?")


@dataclass(frozen=True)
class SafetyVerdict:
    blocked: bool
    reasons: list[str] = field(default_factory=list)


def check(answer: str, passages: list[Passage]) -> SafetyVerdict:
    by_index = {p.index: p for p in passages}
    reasons: list[str] = []
    for sentence in sentences(answer):
        hits = [match for pattern in DIAGNOSIS + ORDERS for match in pattern.finditer(sentence)]
        if not hits:
            continue
        cited = [by_index[int(n)] for n in CITE.findall(sentence) if int(n) in by_index]
        quotes = []
        for quote in QUOTE.finditer(sentence):
            text = next(part for part in quote.groups() if part is not None)
            if any(_normalise_quote(text) == _normalise_quote(source_sentence)
                   for p in cited for source_sentence in sentences(p.text)):
                quotes.append((quote.start(), quote.end()))
        framing = CITE.sub("", QUOTE.sub("", sentence)).strip().rstrip(".!?").strip()
        if (ATTRIBUTION.fullmatch(framing)
                and all(any(start <= hit.start() and hit.end() <= end for start, end in quotes) for hit in hits)):
            continue  # every unsafe phrase is inside an explicit, exact, cited quotation
        reasons.append(sentence[:160])
    return SafetyVerdict(bool(reasons), reasons)
