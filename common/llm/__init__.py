from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ProviderInfo:
    name: str
    kind: str
    base_url: str
    model: str
    api_key_env: str
    external: bool
    baa_signed: bool
    retains_data: bool
    region: str
    max_concurrency: int = 4


class ProviderUnavailable(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class LLMProvider(Protocol):
    info: ProviderInfo

    def stream(self, messages: list[dict], max_tokens: int = 600) -> AsyncIterator[str]: ...


LOCAL_INFO = {
    "none": ProviderInfo("none", "none", "", "", "", False, False, False, "local", 1),
    "fake": ProviderInfo("fake", "fake", "", "fake-cited-answer", "", False, False, False, "local", 4),
}


def load_providers(path: str = "config/providers.yaml") -> dict[str, ProviderInfo]:
    import yaml

    with open(path, encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)["providers"]
    return {name: ProviderInfo(name=name, **fields) for name, fields in raw.items()}


def make_llm(name: str, providers: dict[str, ProviderInfo], guard=None, limit: int = 4,
             api_key: str | None = None) -> LLMProvider:
    from common.llm.fake import FakeLLM, NoLLM
    if name == "none":
        return NoLLM()
    info = providers.get(name) or LOCAL_INFO.get(name)
    if info is None or info.kind == "fake":
        return FakeLLM()
    if info.kind == "ollama":
        from common.llm.ollama import Ollama
        return Ollama(info, guard=guard)
    from common.llm.openai_compat import OpenAICompatible
    return OpenAICompatible(info, guard=guard, limit=min(limit, info.max_concurrency), api_key=api_key)
