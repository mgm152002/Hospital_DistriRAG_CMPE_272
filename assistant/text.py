"""Shared text helpers for guards (pure)."""
import re

STOP = frozenset({
    "the", "and", "for", "are", "with", "that", "this", "our", "your", "from", "when", "what", "should", "must",
    "have", "has", "been", "will", "can", "not", "but", "all", "any", "per", "use", "into", "than", "then", "also",
    "its", "their", "there", "these", "those", "which", "who", "how", "says", "say", "according", "policy",
    "protocol", "document", "hospital",
})
WORD = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")
CITE = re.compile(r"\[(\d+)\]")
SUPERSEDED = re.compile(r"\b(replaces|supersedes|previously|earlier version|version \d+)\b", re.IGNORECASE)
SENTENCE = re.compile(r"[^\n]+?(?:[.!?]+(?:\s*\[\d+\])*(?=\s|$)|$)", re.MULTILINE)


def content_words(text: str) -> set[str]:
    words = set()
    for w in WORD.findall(CITE.sub(" ", text.lower())):
        if len(w) < 3 or w in STOP:
            continue
        for suffix in ("ing", "ed", "es", "s"):
            if len(w) > len(suffix) + 3 and w.endswith(suffix):
                w = w[: -len(suffix)]
                break
        words.add(w)
    return words


# A full stop inside these is not a sentence end: "C. difficile", "Dr. Rao", "e.g. a mask", "ext. 4444".
_DOT = "\u2024"
_PROTECT = re.compile(r"\b(?:Dr|Mr|Mrs|Ms|St|vs)\.(?=\s)|\b(?:e\.g|i\.e)\.|\bext\.(?=\s+\d)|\b[A-Z]\.(?=\s+[a-z])")


def word_forms(word: str) -> set[str]:
    """A word and its plainer forms: "reassessment" also matches "assess", "management" matches "manage"."""
    plain = {word}
    if word.endswith("ment") and len(word) > 7:
        plain.add(word[:-4])
    plain |= {w[2:] for w in plain if w.startswith("re") and len(w) > 6}
    return plain


def sentences(text: str) -> list[str]:
    protected = _PROTECT.sub(lambda m: m.group(0).replace(".", _DOT), text)
    return [s.strip().replace(_DOT, ".") for s in SENTENCE.findall(protected) if s.strip()]


def overlap(sentence: str, source: str) -> float:
    words = content_words(sentence)
    return len(words & content_words(source)) / len(words) if words else 0.0
