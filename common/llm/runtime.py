"""Resolve persisted chat preferences without mutating an in-flight request's provider."""
import asyncio
import hashlib
import time
from dataclasses import replace

from common.config import validate_compliance
from common.llm.fake import NoLLM
from common.llm.network import OpenRouterNetworkGuard
from common.llm.openai_compat import OpenAICompatible
from common.llm.openrouter import ROUTER, free_models, require_free_model
from common.llm.preferences import PROVIDERS, ChatPreferences


async def preferences(state) -> dict:
    return await asyncio.to_thread(ChatPreferences(state.settings.chat_settings_path).read)


def effective_provider(state, saved: dict) -> str:
    """The administrator's saved choice wins; otherwise the deployment's LLM_PROVIDER, else OpenRouter."""
    if saved.get("provider") in PROVIDERS:
        return saved["provider"]
    if state.settings.llm_provider in PROVIDERS:
        return state.settings.llm_provider
    return "openrouter-free"


def active_model(state, saved: dict) -> str:
    if effective_provider(state, saved) == "local-proxy":
        from common.llm.proxy import proxy_info
        return proxy_info(state, saved).model
    return saved["model"] if saved.get("enabled") else state.settings.openrouter_model


def check_configuration(state, model: str, allow_network_override: bool = False) -> None:
    require_free_model(model)
    settings = state.settings.model_copy(update={"llm_provider": "openrouter-free"})
    validate_compliance(settings, state.providers)
    info = state.providers["openrouter-free"]
    if (info.base_url.rstrip("/") != "https://openrouter.ai/api/v1"
            or info.kind != "openai_compatible" or not info.external):
        raise ValueError("OpenRouter must use its official HTTPS endpoint.")
    if state.guard and not allow_network_override:
        state.guard.check(info.base_url + "/chat/completions")


async def resolve_llm(state):
    if state.settings.deployment_profile == "airgapped":
        return state.llm
    saved = await preferences(state)
    if saved.get("network_access") is False:
        return NoLLM() if state.llm.info.external else state.llm
    if effective_provider(state, saved) == "local-proxy":
        from common.llm.proxy import resolve_proxy
        return resolve_proxy(state, saved)
    # Without an explicit choice, a deployment on another provider keeps its startup client.
    if (not saved.get("enabled") and not saved.get("provider")
            and state.settings.llm_provider != "openrouter-free"):
        return state.llm
    model = active_model(state, saved)
    check_configuration(state, model, allow_network_override=saved.get("network_access") is True)
    key = saved.get("api_key") or state.settings.openrouter_api_key.get_secret_value()
    fingerprint = (model, hashlib.sha256(key.encode()).hexdigest())
    current = state.extras.get("openrouter_client")
    if current and current[0] == fingerprint:
        return current[1]
    info = replace(state.providers["openrouter-free"], model=model)
    guard = OpenRouterNetworkGuard(state.settings.chat_settings_path, state.guard)
    llm = OpenAICompatible(info, guard=guard, limit=min(state.settings.llm_max_concurrency,
                                                     info.max_concurrency), api_key=key)
    # Model/key changes share one admission cap with requests already in flight.
    if "openrouter_semaphore" not in state.extras:
        state.extras["openrouter_semaphore"] = asyncio.Semaphore(
            min(state.settings.llm_max_concurrency, info.max_concurrency))
    llm.semaphore = state.extras["openrouter_semaphore"]
    state.extras["openrouter_client"] = (fingerprint, llm)
    return llm


async def model_catalog(state, provider: str | None = None) -> tuple[list[dict], str | None]:
    saved = await preferences(state)
    if (provider or effective_provider(state, saved)) == "local-proxy":
        from common.llm.proxy import proxy_catalog
        return await proxy_catalog(state, saved)
    if state.settings.deployment_profile == "airgapped":
        return [dict(ROUTER)], "OpenRouter is disabled in the air-gapped deployment."
    if saved.get("network_access") is False:
        return [dict(ROUTER)], "Network access is off. Local search remains available."
    cached = state.extras.get("openrouter_models")
    if cached and time.monotonic() - cached[0] < 60:
        return cached[1], cached[2]
    import httpx
    try:
        url = "https://openrouter.ai/api/v1/models"
        guard = OpenRouterNetworkGuard(state.settings.chat_settings_path, state.guard)

        async def check_request(request):
            guard.check(str(request.url))

        async with httpx.AsyncClient(timeout=6.0, event_hooks={"request": [check_request]}) as client:
            response = await client.get(url)
            response.raise_for_status()
            models = free_models(response.json())
        note = None
    except Exception:
        # The documented free router needs no stale, hard-coded individual model list.
        models, note = [dict(ROUTER)], "The model list is unavailable. The automatic free router is still selectable."
    state.extras["openrouter_models"] = (time.monotonic(), models, note)
    return models, note
