"""Free-only routing and server-side settings, runnable without external services."""
import json
import stat
import tempfile
import unittest
from pathlib import Path


class FreeModelTests(unittest.TestCase):
    def test_only_free_router_or_explicit_free_variant_is_allowed(self):
        from common.llm.openrouter import require_free_model
        self.assertEqual(require_free_model("openrouter/free"), "openrouter/free")
        self.assertEqual(require_free_model("vendor/model:free"), "vendor/model:free")
        for model in ("openrouter/auto", "vendor/paid", "vendor/model:free,online", "https://evil/model:free", ""):
            with self.subTest(model=model), self.assertRaises(ValueError):
                require_free_model(model)

    def test_catalog_requires_explicit_zero_prices(self):
        from common.llm.openrouter import free_models
        catalog = {"data": [
            {"id": "v/yes:free", "name": "Free one", "pricing": {"prompt": "0", "completion": "0"}},
            {"id": "v/paid", "pricing": {"prompt": "1", "completion": "1"}},
            {"id": "v/deceptive:free", "pricing": {"prompt": "0", "completion": "0.001"}},
            {"id": "v/missing:free", "pricing": {"prompt": "0"}},
            {"id": "v/extra:free", "pricing": {"prompt": "0", "completion": "0", "request": "0.1"}},
            {"id": "v/nan:free", "pricing": {"prompt": "NaN", "completion": "0"}},
        ]}
        self.assertEqual({m["id"] for m in free_models(catalog)}, {"openrouter/free", "v/yes:free"})

    def test_request_caps_prices_and_has_no_paid_fallbacks(self):
        from common.llm.openrouter import free_request
        body = free_request("openrouter/free", [{"role": "user", "content": "Policy?"}], 600)
        self.assertEqual(body["provider"]["max_price"], {"prompt": 0, "completion": 0, "request": 0, "image": 0})
        self.assertNotIn("models", body)
        with self.assertRaises(ValueError):
            free_request("vendor/paid", [], 10)


class ServerSettingsTests(unittest.TestCase):
    def test_network_access_setting_persists_without_losing_key(self):
        from common.llm.preferences import ChatPreferences
        with tempfile.TemporaryDirectory() as directory:
            store = ChatPreferences(Path(directory) / "chat.json")
            key = "sk-or-v1-" + "x" * 64
            store.save("openrouter/free", key)
            store.save("openrouter/free", network_access=False)
            self.assertFalse(store.public()["network_access"])
            self.assertEqual(store.read()["api_key"], key)
            store.save("vendor/model:free")
            self.assertFalse(store.public()["network_access"])

    def test_saved_settings_survive_a_new_store_and_hide_the_key(self):
        from common.llm.preferences import ChatPreferences
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private" / "chat.json"
            store = ChatPreferences(path)
            key = "sk-or-v1-" + "x" * 64
            store.save("openrouter/free", key)
            again = ChatPreferences(path)
            self.assertEqual(again.read()["api_key"], key)
            self.assertNotIn(key, json.dumps(again.public()))
            self.assertTrue(again.public()["key_configured"])
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)

    def test_model_change_preserves_existing_key(self):
        from common.llm.preferences import ChatPreferences
        with tempfile.TemporaryDirectory() as directory:
            store = ChatPreferences(Path(directory) / "chat.json")
            key = "sk-or-v1-" + "x" * 64
            store.save("openrouter/free", key)
            store.save("vendor/model:free")
            self.assertEqual(store.read()["api_key"], key)
            self.assertEqual(store.public()["model"], "vendor/model:free")

    def test_invalid_model_or_key_does_not_replace_settings(self):
        from common.llm.preferences import ChatPreferences
        with tempfile.TemporaryDirectory() as directory:
            store = ChatPreferences(Path(directory) / "chat.json")
            store.save("openrouter/free", "sk-or-v1-" + "x" * 64)
            original = store.read()
            for model, key in (("vendor/paid", None), ("openrouter/free", "bad-key")):
                with self.assertRaises(ValueError):
                    store.save(model, key)
                self.assertEqual(store.read(), original)


class NetworkAccessTests(unittest.TestCase):
    def test_disabling_network_blocks_a_previously_created_guard(self):
        from common.egress import EgressBlocked, EgressGuard
        from common.llm.network import OpenRouterNetworkGuard
        from common.llm.preferences import ChatPreferences
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "chat.json"
            store = ChatPreferences(path)
            store.save("openrouter/free", network_access=True)
            guard = OpenRouterNetworkGuard(str(path), EgressGuard(["localhost"]))
            guard.check("https://openrouter.ai/api/v1/chat/completions")
            store.save("openrouter/free", network_access=False)
            with self.assertRaises(EgressBlocked):
                guard.check("https://openrouter.ai/api/v1/chat/completions")

    def test_airgapped_or_unapproved_hosts_are_always_blocked(self):
        from common.egress import EgressBlocked
        from common.llm.network import OpenRouterNetworkGuard
        from common.llm.preferences import ChatPreferences
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "chat.json"
            ChatPreferences(path).save("openrouter/free", network_access=True)
            with self.assertRaises(EgressBlocked):
                OpenRouterNetworkGuard(str(path), airgapped=True).check("https://openrouter.ai/api/v1/models")
            for url in ("https://example.com", "http://openrouter.ai/api/v1/models"):
                with self.assertRaises(EgressBlocked):
                    OpenRouterNetworkGuard(str(path)).check(url)


if __name__ == "__main__":
    unittest.main()
