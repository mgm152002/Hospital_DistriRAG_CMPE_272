"""SQL used by the pipeline stages."""
from typing import Any

from psycopg import AsyncConnection

VERSION_COLUMNS = ("version_id, document_id, version_number, status, stage, object_key, filename, content_type, "
                   "chunks_total, text_key")


async def load_version(conn: AsyncConnection, version_id: str, lock: bool = False) -> dict[str, Any] | None:
    sql = f"SELECT {VERSION_COLUMNS} FROM document_versions WHERE version_id = %s" + (" FOR UPDATE" if lock else "")
    row = await (await conn.execute(sql, (version_id,))).fetchone()
    if row is None:
        return None
    keys = [k.strip() for k in VERSION_COLUMNS.split(",")]
    return {k: (str(v) if k in ("version_id", "document_id") else v) for k, v in zip(keys, row, strict=True)}


async def set_stage(conn: AsyncConnection, version_id: str, status: str, stage: str | None) -> None:
    await conn.execute(
        "UPDATE document_versions SET status = %s, stage = %s, updated_at = now() WHERE version_id = %s",
        (status, stage, version_id))
