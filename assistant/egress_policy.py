"""Egress policy (CP-2): which passages may be sent to the configured model provider."""
from collections import Counter
from dataclasses import dataclass, field
from typing import Literal

from assistant.types import Passage
from common.llm import ProviderInfo
from common.models import classification_rank


@dataclass(frozen=True)
class EgressDecision:
    allowed: list[Passage]
    withheld: dict[str, int] = field(default_factory=dict)
    decision: Literal["local", "external_ok", "fallback_passages_only"] = "local"


def decide(info: ProviderInfo, passages: list[Passage], s) -> EgressDecision:
    if not info.external:
        return EgressDecision(list(passages), {}, "local")
    if s.deployment_profile == "airgapped":
        return EgressDecision([], dict(Counter(p.classification for p in passages)), "fallback_passages_only")
    limit = classification_rank(s.external_max_classification)
    allowed = [p for p in passages if classification_rank(p.classification) <= limit]
    withheld = dict(Counter(p.classification for p in passages if classification_rank(p.classification) > limit))
    return EgressDecision(allowed, withheld, "external_ok" if allowed else "fallback_passages_only")
