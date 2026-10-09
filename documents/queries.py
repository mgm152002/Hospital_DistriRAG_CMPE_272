"""Read models for documents (filtered by the caller's groups)."""
from typing import Any

from psycopg import AsyncConnection

from common.models import User
from documents.service import ADMIN_GROUPS

LIST_SQL = """
SELECT d.document_id::text, d.title, d.category, d.department, d.classification, d.owner_id, d.created_at,
       d.retired_at, av.version_number, lv.version_id::text, lv.version_number, lv.status, lv.stage,
       lv.chunks_total, lv.chunks_embedded, lv.updated_at, lv.error_code,
       ARRAY(SELECT group_name FROM document_acl a WHERE a.document_id = d.document_id ORDER BY 1)
FROM documents d
LEFT JOIN document_versions av ON av.version_id = d.active_version_id
JOIN LATERAL (SELECT * FROM document_versions v WHERE v.document_id = d.document_id
              ORDER BY v.version_number DESC LIMIT 1) lv ON true
WHERE d.deleted_at IS NULL
  AND (%(admin)s OR (d.retired_at IS NULL AND d.active_version_id IS NOT NULL AND EXISTS (
       SELECT 1 FROM document_acl a WHERE a.document_id = d.document_id AND a.group_name = ANY(%(groups)s))))
  AND (%(category)s::text IS NULL OR d.category = %(category)s)
  AND (%(status)s::text IS NULL OR lv.status = %(status)s)
  AND (%(q)s::text IS NULL OR d.title ILIKE '%%' || %(q)s || '%%')
ORDER BY d.title
LIMIT 500
"""


def is_admin(user: User) -> bool:
    return bool(user.groups & ADMIN_GROUPS)


async def list_documents(conn: AsyncConnection, user: User, category: str | None, status: str | None,
                         q: str | None) -> list[dict[str, Any]]:
    rows = await (await conn.execute(LIST_SQL, {"admin": is_admin(user), "groups": list(user.groups),
                                                "category": category, "status": status, "q": q})).fetchall()
    keys = ["document_id", "title", "category", "department", "classification", "owner_id", "created_at",
            "retired_at", "active_version_number", "latest_version_id", "latest_version_number", "latest_status",
            "latest_stage", "chunks_total", "chunks_embedded", "updated_at", "error_code", "groups"]
    return [dict(zip(keys, row, strict=True)) for row in rows]


async def readable_document(conn: AsyncConnection, user: User, document_id: str) -> dict[str, Any] | None:
    row = await (await conn.execute(
        "SELECT d.document_id::text, d.title, d.category, d.department, d.classification, d.owner_id, "
        "d.active_version_id::text, d.retired_at, d.created_at, "
        "ARRAY(SELECT group_name FROM document_acl a WHERE a.document_id = d.document_id ORDER BY 1) "
        "FROM documents d WHERE d.document_id = %s AND d.deleted_at IS NULL", (document_id,))).fetchone()
    if row is None:
        return None
    keys = ["document_id", "title", "category", "department", "classification", "owner_id", "active_version_id",
            "retired_at", "created_at", "groups"]
    doc = dict(zip(keys, row, strict=True))
    if not (user.groups & set(doc["groups"])) and not is_admin(user):
        return None
    if doc["retired_at"] is not None and not is_admin(user):
        return None
    versions = await (await conn.execute(
        "SELECT version_id::text, version_number, status, stage, chunks_total, chunks_embedded, uploaded_by, "
        "approved_by, approved_at, effective_date, review_due, error_code, error, created_at, filename "
        "FROM document_versions WHERE document_id = %s ORDER BY version_number DESC", (document_id,))).fetchall()
    vkeys = ["version_id", "version_number", "status", "stage", "chunks_total", "chunks_embedded", "uploaded_by",
             "approved_by", "approved_at", "effective_date", "review_due", "error_code", "error", "created_at",
             "filename"]
    doc["versions"] = [dict(zip(vkeys, v, strict=True)) for v in versions]
    return doc


async def version_document(conn: AsyncConnection, version_id: str) -> str | None:
    row = await (await conn.execute("SELECT document_id::text FROM document_versions WHERE version_id = %s",
                                    (version_id,))).fetchone()
    return row[0] if row else None


async def version_text(conn: AsyncConnection, version_id: str) -> list[dict[str, Any]]:
    rows = await (await conn.execute(
        "SELECT chunk_id::text, chunk_index, page_number, section, text FROM document_chunks "
        "WHERE version_id = %s ORDER BY chunk_index", (version_id,))).fetchall()
    return [{"chunk_id": r[0], "chunk_index": r[1], "page": r[2], "section": r[3], "text": r[4]} for r in rows]


async def version_status(conn: AsyncConnection, version_id: str) -> dict[str, Any] | None:
    row = await (await conn.execute(
        "SELECT v.version_id::text, v.document_id::text, d.title, v.version_number, v.status, v.stage, "
        "v.chunks_total, v.chunks_embedded, v.error_code, v.error, v.updated_at FROM document_versions v "
        "JOIN documents d ON d.document_id = v.document_id WHERE v.version_id = %s", (version_id,))).fetchone()
    if row is None:
        return None
    keys = ["version_id", "document_id", "title", "version_number", "status", "stage", "chunks_total",
            "chunks_embedded", "error_code", "error", "updated_at"]
    return dict(zip(keys, row, strict=True))


async def pending_versions(conn: AsyncConnection) -> list[dict[str, Any]]:
    rows = await (await conn.execute(
        "SELECT v.version_id::text, v.document_id::text, d.title, d.category, d.classification, v.version_number, "
        "v.uploaded_by, v.created_at, v.filename, "
        "ARRAY(SELECT group_name FROM document_acl a WHERE a.document_id = d.document_id ORDER BY 1) "
        "FROM document_versions v JOIN documents d ON d.document_id = v.document_id "
        "WHERE v.status = 'PENDING_APPROVAL' AND d.deleted_at IS NULL ORDER BY v.created_at")).fetchall()
    keys = ["version_id", "document_id", "title", "category", "classification", "version_number", "uploaded_by",
            "created_at", "filename", "groups"]
    return [dict(zip(keys, r, strict=True)) for r in rows]
