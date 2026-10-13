import json
from typing import Any

from psycopg import AsyncConnection


async def enqueue(conn: AsyncConnection, stream: str, event_type: str, dedupe_key: str,
                  payload: dict[str, Any]) -> None:
    """Write an event on the caller's connection, so it commits or rolls back with the state change (RL-3).
    Never talks to Redis; the relay publishes it."""
    await conn.execute(
        "INSERT INTO outbox (stream, event_type, dedupe_key, payload) VALUES (%s, %s, %s, %s::jsonb) "
        "ON CONFLICT (dedupe_key) DO NOTHING",
        (stream, event_type, dedupe_key, json.dumps(payload, default=str)),
    )
