"""Private server-side chat settings. Atomic writes, no secrets in public responses."""
import fcntl
import json
import os
import tempfile
from pathlib import Path

from common.llm.openrouter import DEFAULT_MODEL, require_free_model

PROVIDERS = ("local-proxy", "openrouter-free")


class ChatPreferences:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def read(self) -> dict:
        try:
            with self.path.open(encoding="utf-8") as handle:
                result = json.load(handle)
            require_free_model(result["model"])
            proxy = result.get("local_proxy", {})
            if (not isinstance(proxy, dict) or ("model" in proxy and not isinstance(proxy["model"], str))
                    or ("api_key" in proxy and not isinstance(proxy["api_key"], str))):
                raise ValueError("Invalid proxy settings")
            if "provider" in result and result["provider"] not in PROVIDERS:
                raise ValueError("Unknown chat provider")
            if "network_access" in result and not isinstance(result["network_access"], bool):
                raise ValueError("network_access must be a boolean")
            return result
        except FileNotFoundError:
            return {"model": DEFAULT_MODEL, "enabled": False}
        except (KeyError, TypeError, ValueError) as error:
            raise RuntimeError("The server's chat settings file is invalid.") from error

    def public(self, environment_key: bool = False) -> dict:
        data = self.read()
        return {"model": data["model"], "enabled": bool(data.get("enabled")), "free_only": True,
                "network_access": data.get("network_access", True),
                "key_configured": bool(data.get("api_key") or environment_key)}

    def save(self, model: str, api_key: str | None = None, network_access: bool | None = None,
             select: bool = False) -> None:
        """Save OpenRouter settings; `select` also makes OpenRouter the active provider."""
        require_free_model(model)
        if network_access is not None and not isinstance(network_access, bool):
            raise ValueError("Network access must be enabled or disabled.")
        if api_key is not None and (not api_key.startswith("sk-or-") or len(api_key) < 24
                                    or any(character.isspace() for character in api_key)):
            raise ValueError("Enter a valid OpenRouter API key, or leave the field blank to keep the current key.")
        changes: dict = {"model": model, "enabled": True}
        if select:
            changes["provider"] = "openrouter-free"
        if network_access is not None:
            changes["network_access"] = network_access
        if api_key is not None:
            changes["api_key"] = api_key
        self._update(changes)

    def save_proxy(self, model: str, api_key: str | None = None, network_access: bool | None = None,
                   select: bool = False) -> None:
        """Save proxy settings; `select` also makes the proxy the active provider."""
        if not model.strip() or len(model) > 160 or any(c.isspace() for c in model):
            raise ValueError("Choose a model advertised by the proxy.")
        if api_key is not None and (not api_key or len(api_key) > 512 or any(c.isspace() for c in api_key)):
            raise ValueError("Enter a valid proxy API key, or leave the field blank to keep the current key.")
        if network_access is not None and not isinstance(network_access, bool):
            raise ValueError("Network access must be enabled or disabled.")
        changes: dict = {"local_proxy": {"model": model}}
        if api_key is not None:
            changes["local_proxy"]["api_key"] = api_key
        if network_access is not None:
            changes["network_access"] = network_access
        if select:
            changes["provider"] = "local-proxy"
        self._update(changes)

    def _update(self, changes: dict) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        lock_fd = os.open(str(self.path) + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(lock_fd, "w") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            data = self.read()
            if "local_proxy" in changes:
                changes = {**changes, "local_proxy": {**data.get("local_proxy", {}), **changes["local_proxy"]}}
            data.update(changes)
            fd, temporary = tempfile.mkstemp(prefix=".chat-", dir=self.path.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(data, handle)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, self.path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
