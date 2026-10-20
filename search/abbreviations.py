"""Clinical shorthand and colloquial wording expansion for retrieval (pure).

The original text is kept and expansions are appended, so a query that already uses the policy's words is unchanged
and expanding twice gives the same result. Expansions are what the approved documents actually say, so a nurse's
"HH", "bedsores" or "stuck with a needle" reaches "hand hygiene", "pressure injury" and "sharps injury".
"""
import re

from search.noise import FILLER
from search.snippet import query_terms

ABBREVIATIONS = {
    "hr": "heart rate",
    "bp": "blood pressure",
    "rr": "respiratory rate",
    "temp": "temperature",
    "spo2": "oxygen saturation",
    "sats": "oxygen saturation",
    "sat": "oxygen saturation",
    "gcs": "level of consciousness",
    "sbp": "systolic blood pressure",
    "loc": "level of consciousness",
    "mrsa": "contact precautions",
    "c diff": "C. difficile",
    "cdiff": "C. difficile",
    "c-diff": "C. difficile",
    "cdi": "C. difficile",
    "iv": "intravenous",
    "po": "oral",
    "ecg": "ECG electrocardiogram",
    "ekg": "ECG",
    "pca": "patient-controlled analgesia",
    "dob": "date of birth",
    "rrt": "rapid response team",
    "hh": "hand hygiene",
    "abhr": "alcohol-based hand rub",
    "ppe": "gown gloves",
    "cp": "chest pain",
    "lkw": "last known well",
    "cs": "controlled substance",
    "vanc": "vancomycin",
    "pt": "patient",
    "pts": "patients",
}
# Wording that is not an abbreviation: irregular verbs, lay terms, and a small English-Spanish glossary for the
# questions front-desk and patient-services staff are asked. Each entry is (pattern, words to append).
PHRASES: list[tuple[str, list[str]]] = [
    (r"\bfell\b", ["fall"]),
    # "reassessment" and "assess" are one idea; "schedule" and "how often" ask for timing, which policies word as
    # "every shift".
    (r"\bre-?assess\w*", ["assess", "assessment"]),
    (r"\bschedule\b|\bhow often\b|\bfrequen\w+", ["every shift"]),
    (r"\b(?:stuck|poked|pricked)\b.{0,30}\bneedles?\b|\bneedle\s?sticks?\b",
     ["sharps injury", "needlestick", "bloodborne exposure"]),
    (r"\bbed\s?sores?\b|\bpressure\s+(?:ulcers?|sores?)\b", ["pressure injury"]),
    (r"\b(?:turn|turning|flip|flipping)\b.{0,20}\b(?:pts?|patients?)\b", ["reposition"]),
    (r"\bsurgery\b|\bpost[- ]?op(?:erative)?\b", ["post-op wound care"]),
    (r"\bcall\b.{0,20}\bcode\b(?!\s+blue)", ["code blue", "rapid response"]),
    (r"\b(?:collapsed|collapse|passed out|unconscious|isn'?t breathing|not breathing|stopped breathing|unresponsive|"
     r"no pulse|cardiac arrest)\b", ["code blue", "unresponsive not breathing"]),
    (r"\b(?:face droop\w*|facial droop\w*|slurred speech)\b", ["stroke alert", "BE-FAST"]),
    (r"\bhorario\b|\bvisitas?\b", ["visiting hours", "visitor policy"]),
    (r"\bcirug[ií]a\b|\bducha\b", ["post-op wound care", "shower"]),
]
_ABBR = re.compile(
    r"(?<![\w-])(" + "|".join(re.escape(k) for k in sorted(ABBREVIATIONS, key=len, reverse=True)) + r")(?![\w-])",
    re.IGNORECASE,
)
_PHRASES = [(re.compile(pattern, re.IGNORECASE), words) for pattern, words in PHRASES]


def expand(query: str) -> str:
    lowered = query.lower()
    found: list[str] = []

    def add(words: list[str]) -> None:
        for word in words:
            if word.lower() not in lowered and word not in found:
                found.append(word)

    for match in _ABBR.finditer(query):
        add([ABBREVIATIONS[match.group(1).lower()]])
    for pattern, words in _PHRASES:
        if pattern.search(query):
            add(words)
    return f"{query} {' '.join(found)}" if found else query


def concepts(query: str) -> list[tuple[list[str], list[str]]]:
    """For each shorthand or lay phrase in the query: (the words the user typed, the words the policy uses).
    A quote that contains any of the policy's words answers for the user's wording."""
    out = []
    for pattern in [_ABBR] + [p for p, _ in _PHRASES]:
        for match in pattern.finditer(query):
            policy = (ABBREVIATIONS[match.group(1).lower()] if pattern is _ABBR
                      else next(words for p, words in _PHRASES if p is pattern))
            out.append((query_terms(match.group(0)), policy if isinstance(policy, list) else [policy]))
    return out


def lexical_terms(query: str) -> list[str]:
    """Terms for the full-text half of the score. Wording that was expanded into the policy's own words ("stuck with
    a used needle" -> "sharps injury needlestick"), abbreviations that were spelled out, and filler are dropped, so
    they cannot count against a chunk that matches the expansion. Never empty when the query has words."""
    spans = [m.span() for m in _ABBR.finditer(query)] + [m.span() for _, m in
                                                         ((p, p.search(query)) for p, _ in _PHRASES) if m]
    triggers = {w for start, end in spans for w in query_terms(query[start:end])}
    terms = [t for t in query_terms(expand(query)) if t not in triggers and t not in FILLER]
    return terms or query_terms(query)
