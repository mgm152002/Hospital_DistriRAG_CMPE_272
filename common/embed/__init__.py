from typing import Protocol

from common.config import Settings


class Embedder(Protocol):
    dim: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


from common.embed.hashing import HashingEmbedder  # noqa: E402


class SlowEmbedder:
    """Wraps an embedder with a fixed delay per batch (fault-injection tests only)."""

    def __init__(self, inner: Embedder, delay_ms: int) -> None:
        self.inner, self.delay = inner, delay_ms / 1000
        self.dim = inner.dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        import asyncio
        await asyncio.sleep(self.delay)
        return await self.inner.embed(texts)


def make_embedder(s: Settings) -> Embedder:
    inner: Embedder
    if s.embed_provider == "minilm":
        from common.embed.minilm import MiniLMEmbedder
        inner = MiniLMEmbedder(cache_dir=s.model_cache_dir)
    else:
        inner = HashingEmbedder(dim=s.embedding_dim)
    return SlowEmbedder(inner, s.embed_delay_ms) if s.embed_delay_ms else inner


__all__ = ["Embedder", "HashingEmbedder", "make_embedder"]
