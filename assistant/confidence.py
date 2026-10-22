"""Confidence score (AG-5): 100 × (0.5·R + 0.3·C + 0.2·A), computed from measurements, never asked of the model."""
from dataclasses import dataclass
from typing import Literal

UPPER = 0.85
HASHING_UPPER = 0.6  # the hashing embedder's best matches score about 0.45-0.76, never 0.85 (docs/RESULTS.md)
VERBATIM = 0.8       # share of answer sentences that are near-copies of the cited text


@dataclass(frozen=True)
class Confidence:
    score: int
    band: Literal["High", "Medium", "Low"]
    r: float
    c: float
    a: float


def band_for(score: int) -> Literal["High", "Medium", "Low"]:
    return "High" if score >= 75 else "Medium" if score >= 50 else "Low"


def score(passage_scores: list[float], coverage: float, distinct_docs: int, s,
          verbatim: float = 0.0) -> Confidence:
    """`verbatim` lets one fully quoted source count as agreement: a sentence copied from the policy needs no second
    document to corroborate it."""
    top = sorted(passage_scores, reverse=True)[:3]
    mean = sum(top) / len(top) if top else 0.0
    low = s.min_relevance
    upper = HASHING_UPPER if getattr(s, "embed_provider", "hashing") == "hashing" else UPPER
    r = min(1.0, max(0.0, (mean - low) / (upper - low))) if low < upper else 0.0
    c = min(1.0, max(0.0, coverage))
    corroborated = distinct_docs >= 2 or (distinct_docs == 1 and verbatim >= VERBATIM)
    a = 1.0 if corroborated else 0.6 if distinct_docs == 1 else 0.0
    wr, wc, wa = s.confidence_weights
    value = round(100 * (wr * r + wc * c + wa * a))
    band = band_for(value) if c > 0 else "Low"  # an answer with no verified citation is never Medium/High
    return Confidence(value, band, round(r, 3), round(c, 3), a)
