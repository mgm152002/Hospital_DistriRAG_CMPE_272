"""Rules-first question classifier (AG-1, AG-7). Pure: no I/O."""
import pathlib
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Literal

Label = Literal["policy_lookup", "clinical_reference", "diagnostic_support", "diagnosis_request", "patient_order",
                "emergency", "out_of_scope"]
PRECEDENCE: tuple[Label, ...] = ("emergency", "diagnosis_request", "patient_order", "diagnostic_support",
                                 "out_of_scope", "clinical_reference")
RULES_FILE = pathlib.Path(__file__).with_name("rules.yaml")


@dataclass(frozen=True)
class Classification:
    label: Label
    matched_rules: list[str] = field(default_factory=list)
    method: Literal["rule", "llm", "default"] = "rule"


@lru_cache(maxsize=1)
def _rules() -> dict[str, list[re.Pattern[str]]]:
    import yaml

    raw = yaml.safe_load(RULES_FILE.read_text())
    return {label: [re.compile(p, re.IGNORECASE) for p in patterns] for label, patterns in raw.items()}


def classify(text: str) -> Classification:
    rules = _rules()
    for label in PRECEDENCE:
        matched = [p.pattern for p in rules.get(label, []) if p.search(text)]
        if matched:
            return Classification(label, matched, "rule")
    return Classification("policy_lookup", [], "default")


REFUSING: frozenset[str] = frozenset({"diagnosis_request", "patient_order"})
