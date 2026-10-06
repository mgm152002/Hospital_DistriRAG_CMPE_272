import uuid

NAMESPACE = uuid.UUID("6f1c2d5e-0000-4000-8000-d15791a90001")


def chunk_id(version_id: str, index: int) -> str:
    """Deterministic chunk id (CR-4): the same version and index always give the same id."""
    return str(uuid.uuid5(NAMESPACE, f"{version_id}:{index}"))
