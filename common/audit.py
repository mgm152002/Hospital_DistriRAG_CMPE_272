import json
from typing import Any

from psycopg import AsyncConnection


async def record(conn: AsyncConnection, actor: str, action: str, target: str | None = None,
                 detail: dict[str, Any] | None = None) -> None:
    """Append one audit entry on the caller's connection, so it commits with the action it describes."""
    await conn.execute(
        "INSERT INTO audit_log (actor_id, action, target, detail) VALUES (%s, %s, %s, %s::jsonb)",
        (actor, action, target, json.dumps(detail or {}, default=str)),
    )
