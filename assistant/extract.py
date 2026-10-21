"""Extractive answers (pure): the sentences of the approved documents that best answer a question, quoted verbatim.

Used when the generated answer cannot be used or trusted (model down, citation check failed, data policy withholds the
passages from an external model) and for the instant preview, so the user always gets the policy's own words with
a source number instead of a bare list of passage cards.
"""
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from assistant.relevance import NOISE
from assistant.text import SUPERSEDED, content_words, sentences, word_forms
from assistant.types import Passage
from search.abbreviations import expand

MAX_CHARS = 400
BANNER = re.compile(r"SYNTHETIC|FOR DEMONSTRATION ONLY", re.IGNORECASE)
NUMBERING = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s+")
ACTION = re.compile(r"(?i)\b(dial|call|activate|page)\b.*\b\d{4}\b")


@dataclass(frozen=True)
class Item:
    sentence: str
    index: int


@dataclass(frozen=True)
class Extract:
    items: list[Item] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(f"{i.sentence} [{i.index}]" for i in self.items)

    @property
    def cited(self) -> list[int]:
        return list(dict.fromkeys(i.index for i in self.items))


def _candidates(passage: Passage, short_identity: bool = False) -> list[str]:
    out = []
    for line in passage.text.splitlines():
        line = NUMBERING.sub("", line).strip()
        if not line or BANNER.search(line):
            continue
        minimum = 2 if short_identity else 4
        out += [s for s in sentences(line) if len(s.split()) >= minimum and not BANNER.search(s)]
    # "This replaces the 8:00 to 20:00 hours in version 1" is a changelog note: quoting it puts the retired value next
    # to the current one. Keep it only when it is all the passage has.
    return [s for s in out if not SUPERSEDED.search(s)] or out


def extract(question: str, passages: list[Passage], limit: int = 2, *,
            accept: Callable[[str, Passage], bool] | None = None) -> Extract:
    terms = content_words(expand(question)) - NOISE
    # A person's full name can be a short heading rather than a four-word sentence.
    short_identity = bool(re.match(r"(?i)^\s*who\s+(?:is|was|are)\b", question)) and len(question.split()) <= 5
    scored: list[tuple[float, Item, int]] = []
    for passage in passages:
        for position, sentence in enumerate(_candidates(passage, short_identity)):
            if accept is not None and not accept(sentence, passage):
                continue
            words = content_words(sentence)
            shared = sum(1 for t in terms if any(content_words(f) & words for f in word_forms(t)))
            score = (shared / max(1, len(terms))) + 0.3 * passage.score - 0.01 * position
            if SUPERSEDED.search(sentence):
                score *= 0.5
            scored.append((score, Item(sentence, passage.index), shared))
    chosen: list[Item] = []
    for _, item, shared in sorted(scored, key=lambda row: row[0], reverse=True):
        if any(item.sentence == c.sentence for c in chosen):
            continue
        if chosen and shared == 0:  # a second quote must be about the question, not merely nearby
            continue
        if chosen and sum(len(c.sentence) for c in chosen) + len(item.sentence) > MAX_CHARS:
            continue
        chosen.append(item)
        if len(chosen) == limit:
            break
    return Extract(chosen)


def emergency_lead(passages: list[Passage]) -> Extract:
    """The sentence that says who to call and on which extension, so an emergency answer starts with the action."""
    for passage in sorted(passages, key=lambda p: p.score, reverse=True):
        for sentence in _candidates(passage):
            if ACTION.search(sentence):
                return Extract([Item(sentence, passage.index)])
    return Extract()
