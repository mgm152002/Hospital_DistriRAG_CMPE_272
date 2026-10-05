from dataclasses import dataclass, field
from enum import StrEnum


class VersionStatus(StrEnum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    REJECTED = "REJECTED"
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    READY = "READY"
    SUPERSEDED = "SUPERSEDED"
    FAILED = "FAILED"


class Stage(StrEnum):
    EXTRACT = "EXTRACT"
    CHUNK = "CHUNK"
    EMBED = "EMBED"
    FINALIZE = "FINALIZE"


CLASSIFICATIONS = ("public", "internal", "confidential", "restricted")


def classification_rank(value: str) -> int:
    return CLASSIFICATIONS.index(value)


CATEGORIES = (
    "Clinical Policy", "Nursing Procedure", "Patient Safety", "Infection Control", "Medication & Pharmacy",
    "Discharge Instructions", "Emergency Response", "Operational Workflow", "Departmental Reference",
)


@dataclass(frozen=True)
class User:
    user_id: str
    groups: frozenset[str]
    display_name: str = ""
    roles: tuple[str, ...] = field(default_factory=tuple)

    def has(self, group: str) -> bool:
        return group in self.groups
