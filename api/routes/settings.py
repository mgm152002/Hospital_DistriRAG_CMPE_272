"""Chat model settings. Secrets are write-only and changes require a configuration administrator."""
import asyncio
from typing import Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, SecretStr

from api.auth import current_user, require_group
from api.deps import AppState, get_state
from api.errors import ApiError
from common import audit
from common.config import ComplianceConfigError, validate_compliance
from common.egress import EgressBlocked
from common.llm.openrouter import require_free_model
from common.llm.preferences import ChatPreferences
from common.llm.proxy import ProxyNetworkGuard, proxy_catalog, proxy_info, proxy_key
from common.llm.runtime import active_model, check_configuration, effective_provider, model_catalog, preferences
from common.models import User

router = APIRouter(prefix="/api/chat/settings")


ProviderId = Literal["local-proxy", "openrouter-free"]


class ChatSettingsBody(BaseModel):
    model: str = Field(min_length=1, max_length=160)
    api_key: SecretStr | None = None
    network_access: bool | None = None
    provider: ProviderId | None = None


PROVIDER_LABELS = {"local-proxy": "CLI Proxy", "openrouter-free": "OpenRouter"}


def openrouter_key(state: AppState, saved: dict) -> str:
    return saved.get("api_key") or state.settings.openrouter_api_key.get_secret_value()


async def public_settings(state: AppState, user: User) -> dict:
    saved = await preferences(state)
    provider = effective_provider(state, saved)
    models, note = await model_catalog(state, provider)
    proxy = provider == "local-proxy"
    keys = {"local-proxy": bool(proxy_key(state, saved)), "openrouter-free": bool(openrouter_key(state, saved))}
    return {"provider": provider,
            "providers": [{"id": pid, "label": label, "configured": keys[pid]}
                          for pid, label in PROVIDER_LABELS.items()],
            "model": active_model(state, saved), "free_only": not proxy,
            "enabled": bool(proxy or saved.get("enabled") or saved.get("provider")
                            or state.settings.llm_provider == "openrouter-free"),
            "key_configured": keys[provider],
            "can_edit": bool(user.groups & {"doc-admins", "compliance"}),
            "network_access": saved.get("network_access", True) and state.settings.deployment_profile != "airgapped",
            "allowed_hosts": [urlparse(proxy_info(state, saved).base_url).hostname] if proxy else ["openrouter.ai"],
            "external_max_classification": state.settings.external_max_classification,
            "models": models, "catalog_notice": note,
            "airgapped": state.settings.deployment_profile == "airgapped"}


@router.get("")
async def get_chat_settings(user: User = Depends(current_user), state: AppState = Depends(get_state)):
    return await public_settings(state, user)


@router.get("/models")
async def get_provider_models(provider: ProviderId = Query(...), user: User = Depends(current_user),
                              state: AppState = Depends(get_state)):
    """A provider's model catalog, for choosing a model before switching. Does not switch."""
    models, note = await model_catalog(state, provider)
    return {"models": models, "catalog_notice": note}


@router.put("")
async def update_chat_settings(body: ChatSettingsBody,
                               user: User = Depends(require_group("doc-admins", "compliance")),
                               state: AppState = Depends(get_state)):
    saved = await preferences(state)
    current = effective_provider(state, saved)
    target = body.provider or current
    # Persist the choice only when the administrator names a provider; otherwise keep following it.
    select = body.provider is not None
    if target == "local-proxy":
        return await update_proxy_settings(body, user, state, saved, select=select)
    network_access = body.network_access if body.network_access is not None else saved.get("network_access", True)
    try:
        require_free_model(body.model)
        if network_access:
            check_configuration(state, body.model, allow_network_override=True)
    except (ValueError, ComplianceConfigError, EgressBlocked) as error:
        raise ApiError(400, "chat_settings_blocked", str(error)) from error
    if network_access and body.model != "openrouter/free":
        models, _ = await model_catalog(state, "openrouter-free")
        if body.model not in {model["id"] for model in models}:
            raise ApiError(400, "free_model_unavailable",
                           "Choose a currently available free model, or the automatic router.")
    key = body.api_key.get_secret_value().strip() if body.api_key else None
    key = key or None
    if network_access and not (key or openrouter_key(state, saved)):
        raise ApiError(400, "api_key_required", "Add your OpenRouter API key to enable the chatbot.")
    try:
        await asyncio.to_thread(ChatPreferences(state.settings.chat_settings_path).save,
                                body.model, key, network_access, select)
    except ValueError as error:
        raise ApiError(400, "invalid_api_key", str(error)) from error
    async with state.pool.connection() as conn:
        await audit.record(conn, user.user_id, "config.changed", "chat", {
            "provider": "openrouter-free", "model": body.model, "free_only": True,
            "key_replaced": key is not None, "network_access": network_access,
            "switched_from": current if current != "openrouter-free" else None})
    return await public_settings(state, user)


async def update_proxy_settings(body: ChatSettingsBody, user: User, state: AppState, saved: dict,
                                select: bool = False):
    current = effective_provider(state, saved)
    network = body.network_access if body.network_access is not None else saved.get("network_access", True)
    key = (body.api_key.get_secret_value().strip() if body.api_key else "") or None
    if key and (len(key) > 512 or any(c.isspace() for c in key)):
        raise ApiError(400, "invalid_api_key", "Enter a valid proxy API key.")
    candidate = {**saved, "local_proxy": {**saved.get("local_proxy", {}), "model": body.model}}
    if key:
        candidate["local_proxy"]["api_key"] = key
    if state.settings.deployment_profile == "airgapped":
        raise ApiError(400, "chat_settings_blocked", "The proxy is disabled in the air-gapped deployment.")
    if network:
        if not proxy_key(state, candidate):
            raise ApiError(400, "api_key_required", "Add the proxy client API key to enable generated answers.")
        try:
            validate_compliance(state.settings.model_copy(update={"llm_provider": "local-proxy"}), state.providers)
            info = proxy_info(state, candidate)
            ProxyNetworkGuard(info.base_url, state.settings.chat_settings_path, state.guard,
                              allow_network_override=True).check(
                info.base_url + "/models")
        except (ValueError, ComplianceConfigError, EgressBlocked) as error:
            raise ApiError(400, "chat_settings_blocked", str(error)) from error
        models, notice = await proxy_catalog(state, {**candidate, "network_access": True}, allow_network_override=True)
        unchanged = current == "local-proxy" and body.model == active_model(state, saved)
        if notice and (not unchanged or key is not None):
            raise ApiError(400, "proxy_catalog_unavailable",
                           "The proxy could not validate the new model or key. Keep the current settings and retry.")
        if body.model not in {m["id"] for m in models}:
            raise ApiError(400, "proxy_model_unavailable", notice or "Choose a model advertised by the proxy.")
    try:
        await asyncio.to_thread(ChatPreferences(state.settings.chat_settings_path).save_proxy,
                                body.model, key, network, select)
    except ValueError as error:
        raise ApiError(400, "invalid_chat_settings", str(error)) from error
    async with state.pool.connection() as conn:
        await audit.record(conn, user.user_id, "config.changed", "chat", {
            "provider": "local-proxy", "model": body.model, "free_only": False,
            "key_replaced": key is not None, "network_access": network,
            "switched_from": current if current != "local-proxy" else None})
    return await public_settings(state, user)
