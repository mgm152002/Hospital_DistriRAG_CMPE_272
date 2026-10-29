"""Egress guard (DP-5): refuse outbound calls to hosts that are not allow-listed."""
from urllib.parse import urlparse


class EgressBlocked(RuntimeError):
    pass


class EgressGuard:
    def __init__(self, allowed_hosts: list[str], enforce: bool = True) -> None:
        self.allowed = [h.lower() for h in allowed_hosts]
        self.enforce = enforce
        self.blocked: list[str] = []

    def allows(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return not self.enforce or any(host == h or host.endswith("." + h) for h in self.allowed)

    def check(self, url: str) -> None:
        if not self.allows(url):
            host = urlparse(url).hostname or url
            self.blocked.append(host)
            raise EgressBlocked(f"Outbound call to {host} is not allowed by ALLOWED_HOSTS")
