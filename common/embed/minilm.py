"""sentence-transformers/all-MiniLM-L6-v2 through ONNX (fastembed): no PyTorch, ~90 MB model, CPU only."""
import asyncio
from typing import Any

MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class MiniLMEmbedder:
    dim = 384

    def __init__(self, cache_dir: str = "/models", batch_size: int = 16) -> None:
        self.cache_dir = cache_dir
        self.batch_size = batch_size
        self._model: Any = None

    def _load(self) -> Any:
        if self._model is None:
            from fastembed import TextEmbedding
            self._model = TextEmbedding(MODEL, cache_dir=self.cache_dir, threads=1)
        return self._model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        def run() -> list[list[float]]:
            return [list(map(float, v)) for v in self._load().embed(texts, batch_size=self.batch_size)]
        return await asyncio.to_thread(run)
