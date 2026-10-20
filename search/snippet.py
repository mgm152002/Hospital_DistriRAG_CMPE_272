"""Snippet windows with highlight ranges (FR-8). Pure: no I/O; highlights are offsets, never HTML."""
import re

STOP = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does", "for", "from", "how", "i", "in", "is", "it",
    "its", "my", "of", "on", "or", "our", "should", "the", "this", "to", "was", "we", "what", "when", "where", "which",
    "who", "why", "will", "with", "you", "your", "me", "us", "they", "their", "there",
})
WORD = re.compile(r"[A-Za-z0-9]+")


def query_terms(query: str) -> list[str]:
    seen: list[str] = []
    for word in WORD.findall(query.lower()):
        if len(word) >= 3 and word not in STOP and word not in seen:
            seen.append(word)
    return seen


def best_window(text: str, terms: list[str], width: int = 300) -> tuple[str, list[tuple[int, int]]]:
    if not terms:
        return text[:width], []
    pattern = re.compile(r"\b(" + "|".join(re.escape(t) for t in terms) + r")\w*", re.IGNORECASE)
    matches = list(pattern.finditer(text))
    if not matches:
        return text[:width], []
    best_start, best_score = 0, -1
    for m in matches:
        start = max(0, m.start() - width // 4)
        window = [x for x in matches if start <= x.start() and x.end() <= start + width]
        score = len({x.group(1).lower() for x in window}) * 10 + len(window)
        if score > best_score:
            best_start, best_score = start, score
    if best_start > 0:
        space = text.find(" ", best_start)
        best_start = space + 1 if 0 <= space < best_start + 20 else best_start
    end = min(len(text), best_start + width)
    snippet = ("…" if best_start > 0 else "") + text[best_start:end]
    offset = 1 if best_start > 0 else 0
    highlights = [(m.start() - best_start + offset, m.end() - best_start + offset)
                  for m in matches if best_start <= m.start() and m.end() <= end]
    return snippet, highlights
