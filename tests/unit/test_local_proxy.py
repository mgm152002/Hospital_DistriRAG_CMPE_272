from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from common.config import Settings
from common.egress import EgressBlocked, EgressGuard
from common.llm import ProviderInfo, load_providers
from common.llm.fake import FakeLLM
from common.llm.preferences import ChatPreferences
from common.llm.runtime import resolve_llm


def proxy_state(tmp_path):
    settings = Settings(_env_file=None, llm_provider="local-proxy", local_proxy_base_url="http://proxy.test:8317/v1",
                        local_proxy_api_key="proxy-client-key", local_proxy_model="gpt-6-luna",
                        allowed_hosts=["proxy.test"], chat_settings_path=str(tmp_path / "chat.json"))
    initial = FakeLLM()
    initial.info = ProviderInfo("local-proxy", "openai_compatible", "http://proxy.test:8317/v1", "gpt-6-luna",
                                "LOCAL_PROXY_API_KEY", True, False, True, "proxy")
    return SimpleNamespace(settings=settings, llm=initial, providers=load_providers(),
                           guard=EgressGuard(["proxy.test"]), extras={})


def test_proxy_preferences_preserve_openrouter_credentials(tmp_path):
    store = ChatPreferences(tmp_path / "chat.json")
    old_key = "sk-or-v1-" + "x" * 64
    store.save("vendor/old-model:free", old_key)
    store.save_proxy("gpt-6-luna", "proxy-client-key", network_access=True)
    saved = ChatPreferences(tmp_path / "chat.json").read()
    assert saved["model"] == "vendor/old-model:free" and saved["api_key"] == old_key
    assert saved["local_proxy"] == {"model": "gpt-6-luna", "api_key": "proxy-client-key"}
    assert "proxy-client-key" not in str(store.public()) and old_key not in str(store.public())


async def test_proxy_deployment_ignores_enabled_openrouter_settings_and_uses_its_own_key(tmp_path):
    state = proxy_state(tmp_path)
    ChatPreferences(state.settings.chat_settings_path).save("vendor/old-model:free", "sk-or-v1-" + "x" * 64)
    llm = await resolve_llm(state)
    assert llm.info.name == "local-proxy" and llm.info.model == "gpt-6-luna"
    assert llm.info.base_url == "http://proxy.test:8317/v1" and llm.info.external
    assert llm._headers()["Authorization"] == "Bearer proxy-client-key"
    assert not llm.is_openrouter


async def test_existing_proxy_client_observes_network_disable_and_rejects_other_origins(tmp_path):
    state = proxy_state(tmp_path)
    llm = await resolve_llm(state)
    llm.guard.check("http://proxy.test:8317/v1/chat/completions")
    for url in ("http://proxy.test:9999/v1/models", "https://openrouter.ai/api/v1/models"):
        with pytest.raises(EgressBlocked):
            llm.guard.check(url)
    ChatPreferences(state.settings.chat_settings_path).save("openrouter/free", network_access=False)
    with pytest.raises(EgressBlocked):
        llm.guard.check("http://proxy.test:8317/v1/chat/completions")
    assert (await resolve_llm(state)).info.name == "none"


async def test_proxy_model_changes_preserve_shared_concurrency_and_the_environment_key(tmp_path):
    state = proxy_state(tmp_path)
    first = await resolve_llm(state)
    ChatPreferences(state.settings.chat_settings_path).save_proxy("gpt-6.2-sol")
    second = await resolve_llm(state)
    assert second.info.model == "gpt-6.2-sol" and first.info.model == "gpt-6-luna"
    assert first.semaphore is second.semaphore
    assert second._headers()["Authorization"] == "Bearer proxy-client-key"


async def test_airgapped_deployment_never_resolves_external_proxy(tmp_path):
    state = proxy_state(tmp_path)
    state.settings = state.settings.model_copy(update={"deployment_profile": "airgapped"})
    assert await resolve_llm(state) is state.llm


async def test_catalog_failure_cannot_validate_and_save_a_new_proxy_model(tmp_path, monkeypatch):
    from api.errors import ApiError
    from api.routes import settings as routes
    from common.models import User

    state = proxy_state(tmp_path)

    async def unavailable(state, saved, **kwargs):
        return [{"id": saved["local_proxy"]["model"], "name": "Fallback"}], "Proxy catalog unavailable"

    monkeypatch.setattr(routes, "proxy_catalog", unavailable)
    with pytest.raises(ApiError) as caught:
        await routes.update_proxy_settings(routes.ChatSettingsBody(model="not-advertised"),
                                           User("alex", frozenset({"doc-admins"})), state, {})
    assert caught.value.code == "proxy_catalog_unavailable"
    assert not (tmp_path / "chat.json").exists()


def openrouter_env_state(tmp_path):
    state = proxy_state(tmp_path)
    state.settings = state.settings.model_copy(update={
        "llm_provider": "openrouter-free", "openrouter_api_key": SecretStr("sk-or-v1-" + "e" * 64),
        "allowed_hosts": ["proxy.test", "openrouter.ai"]})
    state.guard = EgressGuard(["proxy.test", "openrouter.ai"])
    return state


async def test_saved_provider_overrides_the_environment_and_keeps_separate_clients(tmp_path):
    from common.llm.runtime import effective_provider

    state = openrouter_env_state(tmp_path)
    store = ChatPreferences(state.settings.chat_settings_path)
    assert effective_provider(state, store.read()) == "openrouter-free"
    openrouter = await resolve_llm(state)
    assert openrouter.info.name == "openrouter-free"
    store.save_proxy("gpt-6-luna", select=True)
    assert effective_provider(state, store.read()) == "local-proxy"
    proxy = await resolve_llm(state)
    assert proxy.info.name == "local-proxy" and proxy is not openrouter
    store.save("openrouter/free", select=True)
    assert await resolve_llm(state) is openrouter
    unknown = SimpleNamespace(settings=state.settings.model_copy(update={"llm_provider": "fake"}))
    assert effective_provider(unknown, {}) == "openrouter-free"


async def test_settings_api_lists_providers_and_switches_provider_with_model(tmp_path, monkeypatch):
    from api.routes import settings as routes
    from common.models import User

    state = openrouter_env_state(tmp_path)
    state.pool = FakePool()

    async def catalog(state, saved, **kwargs):
        return [{"id": "gpt-6-luna", "name": "Luna"}, {"id": "gpt-6.2-sol", "name": "Sol"}], None

    monkeypatch.setattr(routes, "proxy_catalog", catalog)
    monkeypatch.setattr("common.llm.proxy.proxy_catalog", catalog)
    monkeypatch.setattr("common.llm.proxy.ProxyNetworkGuard.check", lambda self, url: None)
    admin = User("alex", frozenset({"doc-admins"}))
    state.extras["openrouter_models"] = (10**12, [{"id": "openrouter/free", "name": "Router"}], None)
    public = await routes.public_settings(state, admin)
    assert public["provider"] == "openrouter-free"
    assert public["providers"] == [{"id": "local-proxy", "label": "CLI Proxy", "configured": True},
                                   {"id": "openrouter-free", "label": "OpenRouter", "configured": True}]
    listed = await routes.get_provider_models("local-proxy", admin, state)
    assert [m["id"] for m in listed["models"]] == ["gpt-6-luna", "gpt-6.2-sol"] and listed["catalog_notice"] is None
    assert ChatPreferences(state.settings.chat_settings_path).read().get("provider") is None
    switched = await routes.update_chat_settings(
        routes.ChatSettingsBody(model="gpt-6.2-sol", provider="local-proxy"), admin, state)
    assert switched["provider"] == "local-proxy" and switched["model"] == "gpt-6.2-sol"
    assert [m["id"] for m in switched["models"]] == ["gpt-6-luna", "gpt-6.2-sol"]
    back = await routes.update_chat_settings(
        routes.ChatSettingsBody(model="openrouter/free", provider="openrouter-free"), admin, state)
    assert back["provider"] == "openrouter-free" and back["model"] == "openrouter/free"


class FakePool:
    async def execute(self, *args):
        return None

    def connection(self):
        pool = self

        class Connection:
            async def __aenter__(self):
                return pool

            async def __aexit__(self, *args):
                return False
        return Connection()
