import asyncio
import json
from collections.abc import AsyncIterator

import httpx

from common.llm import ProviderInfo, ProviderUnavailable


class Ollama:
    def __init__(self, info: ProviderInfo, guard=None, timeout: float = 120.0) -> None:
        self.info = info
        self.guard = guard
        self.timeout = timeout
        self.semaphore = asyncio.Semaphore(max(1, info.max_concurrency))

    async def stream(self, messages: list[dict], max_tokens: int = 600) -> AsyncIterator[str]:
        url = self.info.base_url.rstrip("/") + "/api/chat"
        if self.guard:
            self.guard.check(url)
        body = {"model": self.info.model, "messages": messages, "stream": True,
                "options": {"num_predict": max_tokens, "temperature": 0.1}}
        async with self.semaphore:
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client, \
                        client.stream("POST", url, json=body) as response:
                    if response.status_code >= 400:
                        raise ProviderUnavailable(f"ollama returned {response.status_code}")
                    async for line in response.aiter_lines():
                        if line.strip():
                            chunk = json.loads(line)
                            if chunk.get("message", {}).get("content"):
                                yield chunk["message"]["content"]
                            if chunk.get("done"):
                                return
            except httpx.HTTPError as error:
                raise ProviderUnavailable(str(error)) from error
