"""CLIProxyAPI: a separately authenticated OpenAI-compatible endpoint forwarding to external accounts."""
import asyncio
import hashlib
from dataclasses import replace
from urllib.parse import urlparse

import httpx

from common.config import validate_compliance
from common.egress import EgressBlocked
from common.llm import ProviderInfo
from common.llm.openai_compat import OpenAICompatible
from common.llm.preferences import ChatPreferences

PROVIDER = "local-proxy"


def proxy_info(state, saved: dict) -> ProviderInfo:
    s = state.settings
    base = state.providers[PROVIDER]
    return replace(base, base_url=s.local_proxy_base_url.rstrip("/"),
                   model=saved.get("local_proxy", {}).get("model") or s.local_proxy_model)


def proxy_key(state, saved: dict) -> str:
    return saved.get("local_proxy", {}).get("api_key") or state.settings.local_proxy_api_key.get_secret_value()


class ProxyNetworkGuard:
    def __init__(self, base_url: str, settings_path: str, base_guard=None, *,
                 allow_network_override: bool = False) -> None:
        self.origin = urlparse(base_url)
        if (self.origin.scheme not in {"http", "https"} or not self.origin.hostname
                or self.origin.username or self.origin.password or self.origin.query or self.origin.fragment):
            raise ValueError("Configure the proxy with an HTTP(S) API URL without credentials, a query or a fragment.")
        self.settings_path, self.base_guard = settings_path, base_guard
        self.allow_network_override = allow_network_override

    def check(self, url: str) -> None:
        if (not self.allow_network_override
                and ChatPreferences(self.settings_path).read().get("network_access") is False):
            raise EgressBlocked("External AI network access is disabled in Settings.")
        target = urlparse(url)
        if (target.username or target.password
                or (target.scheme, target.hostname, target.port)
                != (self.origin.scheme, self.origin.hostname, self.origin.port)):
            raise EgressBlocked("The proxy key may only be used with the configured proxy endpoint.")
        if self.base_guard:
            self.base_guard.check(url)


def resolve_proxy(state, saved: dict):
    info = proxy_info(state, saved)
    validate_compliance(state.settings.model_copy(update={"llm_provider": PROVIDER}),
                        {**state.providers, PROVIDER: info})
    guard = ProxyNetworkGuard(info.base_url, state.settings.chat_settings_path, state.guard)
    guard.check(info.base_url + "/chat/completions")
    key = proxy_key(state, saved)
    fingerprint = (info.base_url, info.model, hashlib.sha256(key.encode()).hexdigest())
    current = state.extras.get("proxy_client")
    if current and current[0] == fingerprint:
        return current[1]
    limit = min(state.settings.llm_max_concurrency, info.max_concurrency)
    llm = OpenAICompatible(info, guard=guard, limit=limit, api_key=key)
    if "proxy_semaphore" not in state.extras:
        state.extras["proxy_semaphore"] = asyncio.Semaphore(limit)
    llm.semaphore = state.extras["proxy_semaphore"]
    state.extras["proxy_client"] = (fingerprint, llm)
    return llm


async def proxy_catalog(state, saved: dict, *, allow_network_override: bool = False) -> tuple[list[dict], str | None]:
    info = proxy_info(state, saved)
    fallback = [{"id": info.model, "name": info.model}]
    if state.settings.deployment_profile == "airgapped" or saved.get("network_access") is False:
        return fallback, "Network access is off. Local search remains available."
    guard = ProxyNetworkGuard(info.base_url, state.settings.chat_settings_path, state.guard,
                              allow_network_override=allow_network_override)

    async def check(request):
        guard.check(str(request.url))

    try:
        async with httpx.AsyncClient(timeout=6, event_hooks={"request": [check]}) as client:
            response = await client.get(info.base_url + "/models",
                                        headers={"Authorization": "Bearer " + proxy_key(state, saved)})
            response.raise_for_status()
        catalog = response.json()
        if not isinstance(catalog, dict) or not isinstance(catalog.get("data"), list):
            raise ValueError("Invalid proxy catalog")
        models = [{"id": entry["id"], "name": entry.get("name") or entry["id"]}
                  for entry in catalog["data"]
                  if isinstance(entry, dict) and isinstance(entry.get("id"), str)
                  and not entry["id"].startswith("gpt-image-")]
        return models or fallback, None
    except (httpx.HTTPError, ValueError, KeyError, EgressBlocked):
        return fallback, "The proxy model list is unavailable. The configured model is still selectable."
