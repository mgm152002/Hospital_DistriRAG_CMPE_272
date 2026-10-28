"""Feature-hashing embedder: deterministic, no model download, ~0 MB RAM. Used by the lite profile and tests."""

import hashlib
import math
import re

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "do",
        "does",
        "for",
        "from",
        "how",
        "i",
        "in",
        "is",
        "it",
        "its",
        "my",
        "of",
        "on",
        "or",
        "our",
        "should",
        "the",
        "this",
        "to",
        "was",
        "we",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "you",
        "your",
    ]
)


# Words that appear in almost every hospital document carry little meaning for retrieval.
GENERIC = frozenset({
    "patient", "patients", "staff", "hospital", "unit", "care", "give", "need", "use", "check", "policy",
    "procedure", "protocol", "document", "every", "must", "follow", "per", "after", "before",
})
GENERIC_WEIGHT = 0.2


def _stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def _tokens(text: str) -> list[str]:
    return [_stem(t) for t in _TOKEN.findall(text.lower()) if t not in _STOP]


class HashingEmbedder:
    def __init__(self, dim: int = 384) -> None:
        self.dim = dim

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        words = _tokens(text)
        weights = {w: GENERIC_WEIGHT if w in GENERIC else 1.0 for w in words}
        features = [(w, weights[w]) for w in words] + [
            (f"{a}_{b}", 0.5 * min(weights[a], weights[b])) for a, b in zip(words, words[1:], strict=False)]
        for feature, weight in features:
            digest = int.from_bytes(hashlib.blake2b(feature.encode(), digest_size=8).digest(), "big")
            vec[digest % self.dim] += weight if (digest >> 63) & 1 else -weight
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0:
            vec[0] = 1.0
            return vec
        return [v / norm for v in vec]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]
