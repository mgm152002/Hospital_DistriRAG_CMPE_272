import httpx
import pytest

from common.egress import EgressBlocked, EgressGuard
from common.llm import make_llm
from common.llm.preferences import ChatPreferences
from common.llm.runtime import resolve_llm
from tests.integration.api_client import as_user, build_state, client
from tests.integration.factories import scalar

PROXY_KEY = "private-proxy-client-key"
OPENROUTER_KEY = "sk-or-v1-" + "x" * 64


@pytest.fixture
async def proxy_api(pool, tmp_path, monkeypatch):
    from common.llm import proxy

    state = build_state(pool, None, tmp_path, llm_provider="local-proxy", local_proxy_api_key=PROXY_KEY,
                        local_proxy_base_url="http://proxy.test:8317/v1", local_proxy_model="gpt-6-luna",
                        chat_settings_path=str(tmp_path / "private" / "chat.json"))
    state.guard = EgressGuard(["proxy.test"])
    state.llm = make_llm("local-proxy", state.providers, state.guard, api_key=PROXY_KEY)
    ChatPreferences(state.settings.chat_settings_path).save("vendor/old:free", OPENROUTER_KEY)

    def handler(request):
        assert request.url.host == "proxy.test" and request.url.path == "/v1/models"
        if request.headers["Authorization"] != "Bearer " + PROXY_KEY:
            return httpx.Response(401)
        if state.extras.get("catalog_down"):
            return httpx.Response(503)
        return httpx.Response(200, json={"data": [{"id": "gpt-6-luna"}, {"id": "gpt-6.2-sol"},
                                                   {"id": "gpt-image-2"}]})

    original = httpx.AsyncClient

    def with_proxy_transport(**kwargs):
        if kwargs.get("transport") is None:
            kwargs["transport"] = httpx.MockTransport(handler)
        return original(**kwargs)

    monkeypatch.setattr(proxy.httpx, "AsyncClient", with_proxy_transport)
    async with client(state) as api:
        yield api, state


async def test_active_proxy_settings_show_real_provider_and_keep_keys_private(proxy_api):
    api, _ = proxy_api
    response = await api.get("/api/chat/settings", headers=as_user("sam"))
    body = response.json()
    assert body["provider"] == "local-proxy" and body["model"] == "gpt-6-luna" and not body["free_only"]
    assert body["key_configured"] and body["allowed_hosts"] == ["proxy.test"]
    assert {m["id"] for m in body["models"]} == {"gpt-6-luna", "gpt-6.2-sol"}
    assert PROXY_KEY not in response.text and OPENROUTER_KEY not in response.text


async def test_proxy_model_updates_preserve_openrouter_settings_and_do_not_log_keys(proxy_api, pool):
    api, state = proxy_api
    first = await resolve_llm(state)
    response = await api.put("/api/chat/settings", headers=as_user("alex"), json={"model": "gpt-6.2-sol"})
    assert response.status_code == 200 and response.json()["model"] == "gpt-6.2-sol"
    second = await resolve_llm(state)
    assert second.info.name == "local-proxy" and second.info.model == "gpt-6.2-sol"
    assert second.semaphore is first.semaphore
    assert second._headers()["Authorization"] == "Bearer " + PROXY_KEY
    saved = ChatPreferences(state.settings.chat_settings_path).read()
    assert saved["model"] == "vendor/old:free" and saved["api_key"] == OPENROUTER_KEY
    detail = await scalar(pool, "SELECT string_agg(detail::text, ' ') FROM audit_log WHERE action='config.changed'")
    assert PROXY_KEY not in detail and OPENROUTER_KEY not in detail


async def test_proxy_network_switch_blocks_existing_clients_and_can_be_reenabled(proxy_api):
    api, state = proxy_api
    llm = await resolve_llm(state)
    off = await api.put("/api/chat/settings", headers=as_user("alex"),
                        json={"model": "gpt-6-luna", "network_access": False})
    assert off.status_code == 200 and not off.json()["network_access"]
    with pytest.raises(EgressBlocked):
        llm.guard.check("http://proxy.test:8317/v1/chat/completions")
    assert (await resolve_llm(state)).info.name == "none"
    on = await api.put("/api/chat/settings", headers=as_user("alex"),
                       json={"model": "gpt-6-luna", "network_access": True})
    assert on.status_code == 200 and on.json()["network_access"]
    assert (await resolve_llm(state)).info.model == "gpt-6-luna"


async def test_proxy_rejects_unknown_models_and_requires_administrator_access(proxy_api):
    api, _ = proxy_api
    denied = await api.put("/api/chat/settings", headers=as_user("sam"), json={"model": "gpt-6-luna"})
    assert denied.status_code == 403
    invalid = await api.put("/api/chat/settings", headers=as_user("alex"), json={"model": "not-advertised"})
    assert invalid.status_code == 400 and invalid.json()["error_code"] == "proxy_model_unavailable"


async def test_proxy_catalog_failure_does_not_save_new_models_or_invalid_keys(proxy_api):
    api, state = proxy_api
    store = ChatPreferences(state.settings.chat_settings_path)
    original = store.read()
    state.extras["catalog_down"] = True
    failed = await api.put("/api/chat/settings", headers=as_user("alex"), json={"model": "not-advertised"})
    assert failed.status_code == 400 and failed.json()["error_code"] == "proxy_catalog_unavailable"
    state.extras["catalog_down"] = False
    bad_key = await api.put("/api/chat/settings", headers=as_user("alex"),
                            json={"model": "gpt-6-luna", "api_key": "wrong-proxy-key"})
    assert bad_key.status_code == 400
    assert store.read() == original
