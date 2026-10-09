"""Document intake, approval and lifecycle rules (FR-2..FR-5, FR-12). Every write is one transaction."""
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from psycopg import AsyncConnection

from common import audit
from common.blob import safe_key
from common.models import CATEGORIES, CLASSIFICATIONS, User, VersionStatus
from documents.validation import CONTENT_TYPES
from pipeline import outbox, streams

ADMIN_GROUPS = frozenset({"doc-admins", "compliance"})


class Forbidden(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


class Conflict(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


class NotFound(Exception):
    pass


class Invalid(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


@dataclass(frozen=True)
class DocumentMeta:
    title: str
    category: str
    department: str
    classification: str
    groups: tuple[str, ...]
    effective_date: date | None = None
    review_due: date | None = None


@dataclass(frozen=True)
class VersionRef:
    document_id: str
    version_id: str
    version_number: int
    status: str

    def as_dict(self) -> dict[str, Any]:
        return {"document_id": self.document_id, "version_id": self.version_id,
                "version_number": self.version_number, "status": self.status}


def check_meta(meta: DocumentMeta, known_groups: set[str]) -> None:
    if not meta.title.strip() or len(meta.title) > 200:
        raise Invalid("invalid_title", "Title must be 1–200 characters.")
    if meta.category not in CATEGORIES:
        raise Invalid("invalid_category", f"Category must be one of: {', '.join(CATEGORIES)}.")
    if meta.classification not in CLASSIFICATIONS:
        raise Invalid("invalid_classification", f"Classification must be one of: {', '.join(CLASSIFICATIONS)}.")
    if not meta.groups or not set(meta.groups) <= known_groups:
        raise Invalid("invalid_groups", f"Groups must be a non-empty subset of: {', '.join(sorted(known_groups))}.")


def require(user: User, group: str, action: str) -> None:
    if not user.has(group):
        raise Forbidden("forbidden", f"Only {group} may {action}.")


def can_read(user: User, acl: set[str]) -> bool:
    return bool(user.groups & acl) or bool(user.groups & ADMIN_GROUPS)


async def _store_version(conn: AsyncConnection, blobs, user: User, did: str, number: int, filename: str, kind: str,
                         sha: str, data: bytes, effective: date | None, review: date | None) -> VersionRef:
    vid = str(uuid.uuid4())
    key = safe_key("originals", did, vid, filename or f"upload.{kind}")
    await blobs.put(key, data, CONTENT_TYPES[kind])
    await conn.execute(
        "INSERT INTO document_versions (version_id, document_id, version_number, status, object_key, filename, "
        "content_type, content_sha256, effective_date, review_due, uploaded_by) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (vid, did, number, VersionStatus.PENDING_APPROVAL, key, filename or f"upload.{kind}", CONTENT_TYPES[kind],
         sha, effective, review, user.user_id))
    await audit.record(conn, user.user_id, "document.uploaded", vid,
                       {"document_id": did, "version_number": number, "sha256": sha})
    return VersionRef(did, vid, number, VersionStatus.PENDING_APPROVAL)


async def create_document(conn: AsyncConnection, blobs, user: User, meta: DocumentMeta, filename: str, kind: str,
                          sha: str, data: bytes, known_groups: set[str]) -> VersionRef:
    require(user, "doc-admins", "upload documents")
    check_meta(meta, known_groups)
    did = str(uuid.uuid4())
    await conn.execute(
        "INSERT INTO documents (document_id, title, category, department, classification, owner_id) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (did, meta.title.strip(), meta.category, meta.department.strip() or "General", meta.classification,
         user.user_id))
    for group in sorted(set(meta.groups)):
        await conn.execute("INSERT INTO document_acl (document_id, group_name) VALUES (%s, %s)", (did, group))
    return await _store_version(conn, blobs, user, did, 1, filename, kind, sha, data, meta.effective_date,
                                meta.review_due)


async def create_version(conn: AsyncConnection, blobs, user: User, document_id: str, filename: str, kind: str,
                         sha: str, data: bytes, effective: date | None, review: date | None) -> VersionRef:
    require(user, "doc-admins", "upload documents")
    row = await (await conn.execute(
        "SELECT deleted_at, retired_at, (SELECT coalesce(max(version_number), 0) FROM document_versions v "
        "WHERE v.document_id = d.document_id) FROM documents d WHERE d.document_id = %s FOR UPDATE",
        (document_id,))).fetchone()
    if row is None or row[0] is not None:
        raise NotFound()
    if row[1] is not None:
        raise Conflict("retired", "This document is retired.")
    return await _store_version(conn, blobs, user, document_id, row[2] + 1, filename, kind, sha, data, effective,
                                review)


async def approve(conn: AsyncConnection, user: User, version_id: str, comment: str) -> None:
    require(user, "compliance", "approve versions")
    row = await (await conn.execute(
        "SELECT status, uploaded_by, document_id::text FROM document_versions WHERE version_id = %s FOR UPDATE",
        (version_id,))).fetchone()
    if row is None:
        raise NotFound()
    status, uploaded_by, did = row
    if uploaded_by == user.user_id:
        raise Forbidden("self_approval", "You cannot approve a version you uploaded.")
    if status != VersionStatus.PENDING_APPROVAL:
        raise Conflict("not_pending", f"This version is {status}, not pending approval.")
    await conn.execute(
        "UPDATE document_versions SET status = %s, approved_by = %s, approved_at = now(), updated_at = now() "
        "WHERE version_id = %s", (VersionStatus.QUEUED, user.user_id, version_id))
    await outbox.enqueue(conn, streams.EXTRACT, "version.approved", f"extract:{version_id}",
                         {"version_id": version_id, "document_id": did})
    await audit.record(conn, user.user_id, "version.approved", version_id, {"comment": comment[:500]})


async def reject(conn: AsyncConnection, user: User, version_id: str, reason: str) -> None:
    require(user, "compliance", "reject versions")
    row = await (await conn.execute("SELECT status FROM document_versions WHERE version_id = %s FOR UPDATE",
                                    (version_id,))).fetchone()
    if row is None:
        raise NotFound()
    if row[0] != VersionStatus.PENDING_APPROVAL:
        raise Conflict("not_pending", f"This version is {row[0]}, not pending approval.")
    await conn.execute("UPDATE document_versions SET status = %s, error = %s, updated_at = now() WHERE version_id = %s",
                       (VersionStatus.REJECTED, reason[:500], version_id))
    await audit.record(conn, user.user_id, "version.rejected", version_id, {"reason": reason[:500]})


async def retire(conn: AsyncConnection, user: User, document_id: str) -> None:
    require(user, "doc-admins", "retire documents")
    result = await conn.execute("UPDATE documents SET retired_at = now() WHERE document_id = %s "
                                "AND deleted_at IS NULL AND retired_at IS NULL", (document_id,))
    if result.rowcount == 0:
        raise NotFound()
    await conn.execute("DELETE FROM answer_cache WHERE %s = ANY(document_ids)", (document_id,))
    await audit.record(conn, user.user_id, "document.retired", document_id)


async def request_delete(conn: AsyncConnection, user: User, document_id: str) -> None:
    require(user, "compliance", "delete documents")
    row = await (await conn.execute("SELECT deleted_at FROM documents WHERE document_id = %s FOR UPDATE",
                                    (document_id,))).fetchone()
    if row is None:
        raise NotFound()
    await conn.execute("UPDATE documents SET retired_at = coalesce(retired_at, now()) WHERE document_id = %s",
                       (document_id,))
    await outbox.enqueue(conn, streams.DELETE, "document.delete", f"delete:{document_id}",
                         {"document_id": document_id, "requested_by": user.user_id})
    await audit.record(conn, user.user_id, "document.delete_requested", document_id)
