import re
from collections.abc import AsyncIterator, Callable

from common.llm import LOCAL_INFO, ProviderUnavailable

_PASSAGE = re.compile(r"^\[(\d+)\][^\n]*\n(.+?)(?=\n\[\d+\]|\Z)", re.MULTILINE | re.DOTALL)


def cited_answer(messages: list[dict]) -> str:
    """Answer by quoting the first sentence of the first two passages, each cited: deterministic for tests."""
    text = "\n".join(m.get("content", "") for m in messages)
    sentences = []
    for number, body in _PASSAGE.findall(text)[:2]:
        candidates = [" ".join(c.split()) for c in re.split(r"(?<=[.!?])\s", body.strip())]
        first = next((c for c in candidates if len(c.split()) >= 5), candidates[0] if candidates else "")
        if first:
            sentences.append(f"{first.rstrip('.')} [{number}].")
    return " ".join(sentences) or "The passages do not answer this question."


class FakeLLM:
    info = LOCAL_INFO["fake"]

    def __init__(self, script: Callable[[list[dict]], str] = cited_answer) -> None:
        self.script = script
        self.calls: list[list[dict]] = []

    async def stream(self, messages: list[dict], max_tokens: int = 600) -> AsyncIterator[str]:
        self.calls.append(messages)
        for word in self.script(messages).split(" "):
            yield word + " "


class NoLLM:
    info = LOCAL_INFO["none"]

    async def stream(self, messages: list[dict], max_tokens: int = 600) -> AsyncIterator[str]:
        raise ProviderUnavailable("No LLM provider is configured (search-only mode)")
        yield ""  # pragma: no cover
