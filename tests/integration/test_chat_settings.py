"""OpenRouter settings: authorization, secret handling, persistence and runtime selection."""
import json
from dataclasses import replace

import pytest

from api.routes import settings as settings_routes
from common.llm.runtime import model_catalog, resolve_llm
from tests.integration.api_client import as_user, build_state, client
from tests.integration.factories import scalar

KEY = "sk-or-v1-" + "x" * 64
MODELS = [{"id": "openrouter/free", "name": "Automatic free models"},
          {"id": "vendor/model:free", "name": "Free model"}]


@pytest.fixture
async def configured(pool, tmp_path, monkeypatch):
    state = build_state(pool, None, tmp_path, chat_settings_path=str(tmp_path / "private" / "chat.json"))

    async def catalog(_, provider=None):
        return MODELS, None

    monkeypatch.setattr(settings_routes, "model_catalog", catalog)
    async with client(state) as c:
        yield c, state


async def test_staff_can_view_settings_but_cannot_change_them(configured):
    api, _ = configured
    body = (await api.get("/api/chat/settings", headers=as_user("sam"))).json()
    assert body["free_only"] is True and body["can_edit"] is False
    result = await api.put("/api/chat/settings", headers=as_user("sam"), json={"model": "openrouter/free"})
    assert result.status_code == 403


async def test_secret_is_write_only_and_runtime_uses_saved_model(configured, pool):
    api, state = configured
    response = await api.put("/api/chat/settings", headers=as_user("alex"),
                             json={"model": "openrouter/free", "api_key": KEY})
    assert response.status_code == 200 and response.json()["key_configured"] is True
    assert KEY not in response.text and "api_key" not in response.json()
    first = await resolve_llm(state)
    changed = await api.put("/api/chat/settings", headers=as_user("alex"), json={"model": "vendor/model:free"})
    assert changed.status_code == 200
    second = await resolve_llm(state)
    assert second.info.model == "vendor/model:free" and first.semaphore is second.semaphore
    assert second._headers()["Authorization"] == "Bearer " + KEY
    body = (await api.get("/api/chat/settings", headers=as_user("sam"))).json()
    assert KEY not in json.dumps(body)
    detail = await scalar(pool, "SELECT string_agg(detail::text, ' ') FROM audit_log WHERE action = 'config.changed'")
    assert KEY not in detail and "key_replaced" in detail


async def test_paid_model_is_rejected_before_saving(configured):
    api, _ = configured
    result = await api.put("/api/chat/settings", headers=as_user("alex"),
                           json={"model": "openrouter/auto", "api_key": KEY})
    assert result.status_code == 400 and result.json()["error_code"] == "chat_settings_blocked"


async def test_airgapped_profile_ignores_previously_saved_external_settings(configured):
    api, state = configured
    await api.put("/api/chat/settings", headers=as_user("alex"), json={"model": "openrouter/free", "api_key": KEY})
    state.settings = state.settings.model_copy(update={"deployment_profile": "airgapped"})
    assert await resolve_llm(state) is state.llm
    result = await api.put("/api/chat/settings", headers=as_user("alex"), json={"model": "openrouter/free"})
    assert result.status_code == 400


async def test_network_can_be_disabled_without_an_api_key_and_blocks_catalog(configured):
    api, state = configured
    state.llm.info = replace(state.llm.info, external=True)
    result = await api.put("/api/chat/settings", headers=as_user("alex"),
                           json={"model": "openrouter/free", "network_access": False})
    assert result.status_code == 200 and result.json()["network_access"] is False
    resolved = await resolve_llm(state)
    assert resolved.info.name == "none"
    models, note = await model_catalog(state)
    assert models[0]["id"] == "openrouter/free" and "off" in note


async def test_network_can_be_reenabled_and_keeps_the_saved_key(configured):
    api, state = configured
    await api.put("/api/chat/settings", headers=as_user("alex"),
                  json={"model": "openrouter/free", "api_key": KEY, "network_access": False})
    result = await api.put("/api/chat/settings", headers=as_user("alex"),
                           json={"model": "openrouter/free", "network_access": True})
    assert result.status_code == 200 and result.json()["network_access"] is True
    assert (await resolve_llm(state))._headers()["Authorization"] == "Bearer " + KEY


async def test_disabling_external_network_preserves_a_local_provider(configured):
    api, state = configured
    local = state.llm
    assert not local.info.external
    result = await api.put("/api/chat/settings", headers=as_user("alex"),
                           json={"model": "openrouter/free", "network_access": False})
    assert result.status_code == 200
    assert await resolve_llm(state) is local
