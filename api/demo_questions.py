"""One-click demo questions: the persona corpus (evals/ux/corpus.json) offered to the signed-in persona.

The corpus is the single source of truth for what the evaluation asks, so the demo can replay exactly those questions.
Only demo setups offer them: a production deployment must not show prompts such as the prompt-injection test.
"""
import functools
import json
import pathlib

from common.config import Settings

CORPUS_PATH = pathlib.Path(__file__).resolve().parents[1] / "evals" / "ux" / "corpus.json"
GENERAL_STAFF = "riley"  # a registered (non-demo) account with all-staff access gets the general-staff questions


@functools.lru_cache(maxsize=1)
def load_corpus() -> dict:
    return json.loads(CORPUS_PATH.read_text())


def demo_enabled(settings: Settings) -> bool:
    return settings.demo_accounts_enabled or settings.auth_mode == "header"


def groups_for(user_id: str, groups: set[str] | frozenset[str], corpus: dict) -> list[dict]:
    """The persona's questions grouped by scenario, in corpus order. Empty for an account without the assistant."""
    if "all-staff" not in groups:
        return []
    personas = {c["persona"] for c in corpus["conversations"]}
    persona = user_id if user_id in personas else GENERAL_STAFF
    out = []
    for scenario, description in corpus["scenarios"].items():
        conversations = [{"id": c["id"], "turns": [t["ask"] for t in c["turns"]]}
                         for c in corpus["conversations"] if c["persona"] == persona and c["scenario"] == scenario]
        if conversations:
            out.append({"scenario": scenario, "title": scenario.replace("_", " ").capitalize(),
                        "description": description, "conversations": conversations})
    return out
