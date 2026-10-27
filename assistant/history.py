"""Keep only conversation turns whose cited sources remain readable and eligible for the provider."""
from typing import Any

from assistant.injection import redact_secrets
from assistant.phi import screen
from common.models import CLASSIFICATIONS


class ConversationHistory(list[tuple[str, str]]):
    """Turns plus the classifications of their currently eligible source documents."""

    def __init__(self, turns: list[tuple[str, str]], classifications: set[str]) -> None:
        super().__init__(turns)
        self.classifications = classifications


def permitted_turns(rows: list[tuple[str, str, list[dict] | None]], visible: dict[str, dict[str, Any]],
                    external: bool, maximum: str) -> ConversationHistory:
    turns: list[tuple[str, str]] = []
    classifications: list[set[str]] = []
    pending: str | None = None
    permitted_classes = set(CLASSIFICATIONS[:CLASSIFICATIONS.index(maximum) + 1])
    for role, content, citations in rows:
        if role == "user":
            pending = content
        elif role == "assistant" and pending is not None:
            permitted = True
            source_classes: set[str] = set()
            for citation in citations or []:
                source = visible.get(citation.get("chunk_id", ""))
                if source is None or source["version_id"] != citation.get("version_id"):
                    permitted = False
                    break
                if external and source["classification"] not in permitted_classes:
                    permitted = False
                    break
                source_classes.add(source["classification"])
            if permitted:
                question = screen(redact_secrets(pending)[0]).redacted
                reply = screen(redact_secrets(content.split("\n\nReference only.")[0])[0]).redacted
                turns.append((question, reply))
                classifications.append(source_classes)
            pending = None
    return ConversationHistory(turns[-6:], set().union(*classifications[-6:]))
