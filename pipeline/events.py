import json
import uuid
from typing import Any

from psycopg import AsyncConnection


def _as_uuid(value: str | None) -> str | None:
    try:
        return str(uuid.UUID(value)) if value else None
    except ValueError:
        return None


async def emit(conn: AsyncConnection, kind: str, version_id: str | None, detail: dict[str, Any]) -> None:
    """Operational event for the pipeline board and recovery timeline (never contains document text)."""
    vid = _as_uuid(version_id)
    if version_id and vid is None:
        detail = {**detail, "ref": version_id}
    await conn.execute("INSERT INTO ops_events (kind, version_id, detail) VALUES (%s, %s, %s::jsonb)",
                       (kind, vid, json.dumps(detail, default=str)))
