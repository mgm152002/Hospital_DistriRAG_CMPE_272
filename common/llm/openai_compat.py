"""OpenAI-compatible chat streaming: OpenRouter, Azure OpenAI, vLLM."""
import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator
from urllib.parse import urlparse

import httpx

from common.llm import ProviderInfo, ProviderUnavailable

RETRYABLE = {429, 500, 502, 503, 504}
log = logging.getLogger(__name__)


class OpenAICompatible:
    def __init__(self, info: ProviderInfo, guard=None, limit: int = 4,
                 transport: httpx.AsyncBaseTransport | None = None, timeout: float = 30.0,
                 retries: int = 2, backoff: float = 1.0, api_key: str | None = None) -> None:
        self.info = info
        self.guard = guard
        self.semaphore = asyncio.Semaphore(limit)
        self.transport = transport
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        self._api_key = api_key

    @property
    def is_openrouter(self) -> bool:
        return urlparse(self.info.base_url).hostname == "openrouter.ai"

    def _headers(self) -> dict[str, str]:
        key = self._api_key if self._api_key is not None else os.environ.get(self.info.api_key_env, "")
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
            if not self.is_openrouter:
                headers["api-key"] = key
        if self.is_openrouter:
            headers["X-Title"] = "DistriRAG"
        return headers

    async def stream(self, messages: list[dict], max_tokens: int = 600) -> AsyncIterator[str]:
        url = self.info.base_url.rstrip("/") + "/chat/completions"
        if self.guard:
            self.guard.check(url)
        body: dict = {"model": self.info.model, "messages": messages, "stream": True,
                      "max_tokens": max_tokens, "temperature": 0.1}
        if self.is_openrouter:
            from common.llm.openrouter import free_request
            try:
                body = free_request(self.info.model, messages, max_tokens)
            except ValueError as error:
                raise ProviderUnavailable("Paid OpenRouter models are disabled.") from error
            if not self._headers().get("Authorization"):
                raise ProviderUnavailable("Configure an OpenRouter API key in Settings.")
            if not self.info.retains_data:
                body["provider"]["data_collection"] = "deny"

        async def check_request(request):
            if self.guard:
                self.guard.check(str(request.url))

        async with self.semaphore:
            for attempt in range(self.retries + 1):
                answered = False
                try:
                    async with httpx.AsyncClient(transport=self.transport, timeout=self.timeout,
                                                 event_hooks={"request": [check_request]}) as client, \
                            client.stream("POST", url, headers=self._headers(), json=body) as response:
                        if response.status_code >= 400:
                            raise ProviderUnavailable(f"{self.info.name} returned {response.status_code}",
                                                      status_code=response.status_code)
                        async for line in response.aiter_lines():
                            if not line.startswith("data:"):
                                continue
                            data = line[5:].strip()
                            if data == "[DONE]":
                                break
                            payload = json.loads(data)
                            if payload.get("error"):
                                code = payload["error"].get("code")
                                raise ProviderUnavailable(f"{self.info.name} returned a stream error",
                                                          status_code=code if isinstance(code, int) else None)
                            for choice in payload.get("choices", []):
                                delta = choice.get("delta", {}).get("content")
                                if delta:
                                    answered = True
                                    yield delta
                        if not answered:  # nothing was yielded, so asking again is safe
                            raise ProviderUnavailable(f"{self.info.name} returned an empty answer")
                        return
                except (ProviderUnavailable, httpx.HTTPError) as error:
                    status = getattr(error, "status_code", None)
                    # Once text has escaped this generator, retrying would splice two different answers together.
                    if answered or attempt == self.retries or (status is not None and status not in RETRYABLE | {404}):
                        raise ProviderUnavailable(str(error), status_code=status) from error
                    if self.is_openrouter and status in RETRYABLE | {404} and body["model"] != "openrouter/free":
                        # A free model's shared upstream quota can be exhausted even with a valid OpenRouter key.
                        # Keep zero-price and data-retention constraints while the free router tries elsewhere.
                        log.warning("Free model unavailable; retrying with automatic free routing",
                                    extra={"model": body["model"], "status_code": status})
                        body["model"] = "openrouter/free"
                        continue
                    await asyncio.sleep(self.backoff * 2**attempt)
