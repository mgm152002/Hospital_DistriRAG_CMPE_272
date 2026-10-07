"""Idempotency-Key handling (CR-5): same key + same request → stored response; same key + different request → 409."""
import hashlib
import json
from typing import Any

from psycopg import AsyncConnection

from api.errors import ApiError


def request_hash(*parts: bytes | str) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part if isinstance(part, bytes) else part.encode())
        digest.update(b"\x1f")
    return digest.hexdigest()


async def lookup(conn: AsyncConnection, key: str, user_id: str, sha: str) -> dict[str, Any] | None:
    row = await (await conn.execute("SELECT user_id, request_sha, response FROM idempotency_keys WHERE key = %s",
                                    (f"{user_id}:{key}",))).fetchone()
    if row is None:
        return None
    if row[1] != sha:
        raise ApiError(409, "idempotency_conflict", "This Idempotency-Key was used for a different request.")
    return row[2]


async def store(conn: AsyncConnection, key: str, user_id: str, sha: str, response: dict[str, Any]) -> None:
    await conn.execute("INSERT INTO idempotency_keys (key, user_id, request_sha, response) VALUES (%s, %s, %s, %s)",
                       (f"{user_id}:{key}", user_id, sha, json.dumps(response, default=str)))
