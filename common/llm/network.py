"""Call-time network switch for the official OpenRouter endpoint only."""
from urllib.parse import urlparse

from common.egress import EgressBlocked
from common.llm.preferences import ChatPreferences


class OpenRouterNetworkGuard:
    def __init__(self, path: str, base_guard=None, airgapped: bool = False) -> None:
        self.path, self.base_guard, self.airgapped = path, base_guard, airgapped

    def check(self, url: str) -> None:
        saved = ChatPreferences(self.path).read()
        parsed = urlparse(url)
        if self.airgapped or saved.get("network_access") is False:
            raise EgressBlocked("External AI network access is disabled in Settings.")
        if parsed.scheme != "https" or parsed.hostname != "openrouter.ai" or parsed.port not in (None, 443):
            raise EgressBlocked("The network setting permits only the official OpenRouter HTTPS endpoint.")
        # An administrator's explicit switch permits this one host; it cannot expand
        # access to other providers or override an air-gapped deployment.
        if saved.get("network_access") is True:
            return
        if self.base_guard:
            self.base_guard.check(url)
