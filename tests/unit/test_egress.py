"""Covers: DP-5, CP-2."""
import pytest

from common.egress import EgressBlocked, EgressGuard


def test_egress_blocks_unlisted_host():
    with pytest.raises(EgressBlocked):
        EgressGuard(["postgres", "redis"], enforce=True).check("https://openrouter.ai/api/v1/chat")


def test_egress_allows_listed_host():
    EgressGuard(["openrouter.ai"], enforce=True).check("https://openrouter.ai/api/v1/chat")


def test_egress_allows_subdomain_of_listed_host():
    EgressGuard(["openai.azure.com"], enforce=True).check("https://x.openai.azure.com/v1")


def test_egress_not_enforced_allows_all():
    EgressGuard([], enforce=False).check("https://example.com")
