from dataclasses import dataclass, field
from typing import Any

from fastapi import Request

from common.config import Settings
from common.egress import EgressGuard
from common.llm import ProviderInfo


@dataclass
class AppState:
    settings: Settings
    pool: Any
    redis: Any
    blobs: Any
    embedder: Any
    llm: Any
    providers: dict[str, ProviderInfo]
    guard: EgressGuard | None = None
    extras: dict[str, Any] = field(default_factory=dict)


def get_state(request: Request) -> AppState:
    return request.app.state.distrirag
