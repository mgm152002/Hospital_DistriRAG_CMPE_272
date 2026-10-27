"""Follow-up questions borrow their topic from the recent, permitted conversation history."""
import asyncio
import re
from typing import Any

FOLLOW_UP = re.compile(r"(?i)^\s*(and|so|ok|okay|also|then|but|what about|how about)\b|"
                       r"\b(it|its|that|those|these|them|they|their|theirs|he|him|his|she|her|hers|same|one of them)\b")
PLACEHOLDER = re.compile(r"\[REDACTED-[A-Z]+\]")
MAX_WORDS = 12


def retrieval_query(question: str, history: list[tuple[str, str]]) -> str:
    """Keep the topic through a chain of short follow-ups, stopping at the latest standalone question."""
    if not history or len(question.split()) > MAX_WORDS or not FOLLOW_UP.search(question):
        return question
    context: list[str] = []
    seen = {question.casefold().strip(" .?!")}
    for previous, _ in reversed(history[-6:]):
        clean = re.sub(r"\s+", " ", PLACEHOLDER.sub(" ", previous)).strip()
        key = clean.casefold().strip(" .?!")
        if clean and key not in seen:
            context.append(clean)
            seen.add(key)
        if len(previous.split()) > MAX_WORDS or not FOLLOW_UP.search(previous):
            break
    return " ".join([*reversed(context), question])


CONDENSE_PROMPT = ("Rewrite the user's latest message as one standalone search query for a hospital policy library. "
                   "Resolve pronouns and references (\"it\", \"them\", \"that\") using the conversation. Keep the "
                   "user's own meaning; do not answer it and do not add facts. Reply with the query only, on one line.")
CONDENSE_TIMEOUT = 4.0
CONDENSE_TOKENS = 60
MAX_QUERY_CHARS = 300
_TURN_CHARS = 400
_LOCAL = ("none", "fake")


def condense_messages(question: str, history: list[tuple[str, str]]) -> list[dict]:
    """Only the conversation's already-redacted turns (the same text the answer prompt receives) and the question."""
    lines = []
    for q, a in history[-3:]:
        lines += [f"User: {q.strip()}", f"Assistant: {a.strip()[:_TURN_CHARS]}"]
    convo = "\n".join(lines)
    return [{"role": "system", "content": CONDENSE_PROMPT},
            {"role": "user", "content": f"Conversation:\n{convo}\n\nLatest message: {question}\n\nStandalone query:"}]


def _clean(text: str) -> str:
    line = next((ln for ln in text.strip().splitlines() if ln.strip()), "")
    line = re.sub(r"(?i)^\s*(standalone\s+)?(search\s+)?query\s*:\s*", "", line)
    line = re.sub(r"\s+", " ", PLACEHOLDER.sub(" ", line)).strip().strip("\"'`*").strip()
    return line if 0 < len(line) <= MAX_QUERY_CHARS else ""


async def condense(question: str, history: list[tuple[str, str]], llm: Any,
                   timeout: float = CONDENSE_TIMEOUT) -> str:
    """A follow-up rewritten by the model into a standalone search query; the heuristic on any failure, timeout, or
    when no real model is configured. The result is used for retrieval only, never quoted back to the user."""
    fallback = retrieval_query(question, history)
    if not history or not question.strip() or getattr(getattr(llm, "info", None), "name", "none") in _LOCAL:
        return fallback
    try:
        async with asyncio.timeout(timeout):
            text = "".join([t async for t in llm.stream(condense_messages(question, history),
                                                         max_tokens=CONDENSE_TOKENS)])
    except Exception:  # noqa: BLE001 - any provider failure falls back to the heuristic
        return fallback
    return _clean(text) or fallback
