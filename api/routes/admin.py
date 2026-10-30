"""Administrative analytics and version comparison; questions and source text stay out of analytics."""

import asyncio
from difflib import ndiff
from uuid import UUID

from fastapi import APIRouter, Depends

from api.auth import require_group
from api.deps import AppState, get_state
from api.errors import ApiError
from common.models import User
from pipeline.consumer import PermanentError
from pipeline.stages.extract import extract_pages

router = APIRouter(prefix="/api/admin")
admin = require_group("doc-admins", "compliance")


@router.get("/analytics")
async def analytics(user: User = Depends(admin), state: AppState = Depends(get_state)):
    async with state.pool.connection() as conn:
        counts = await (
            await conn.execute(
                "SELECT (SELECT count(*) FROM documents WHERE deleted_at IS NULL), "
                "(SELECT count(*) FROM documents WHERE active_version_id IS NOT NULL AND retired_at IS NULL "
                " AND deleted_at IS NULL), "
                "(SELECT count(*) FROM document_versions v JOIN documents d USING(document_id) "
                " WHERE v.status='PENDING_APPROVAL' AND d.deleted_at IS NULL AND d.retired_at IS NULL), "
                "(SELECT count(*) FROM document_versions WHERE status='PROCESSING' OR status='QUEUED'), "
                "(SELECT count(*) FROM document_versions WHERE status='FAILED'), "
                "(SELECT count(*) FROM document_versions), "
                "(SELECT count(*) FROM user_accounts WHERE disabled_at IS NULL), "
                "(SELECT count(*) FROM audit_log WHERE action='search.performed' "
                " AND created_at>now()-interval '30 days'), "
                "(SELECT count(*) FROM audit_log WHERE action IN ('chat.answered','chat.blocked') "
                " AND created_at>now()-interval '30 days')"
            )
        ).fetchone()
        categories = await (
            await conn.execute(
                "SELECT category,count(*) FROM documents WHERE deleted_at IS NULL "
                "GROUP BY category ORDER BY count(*) DESC"
            )
        ).fetchall()
        statuses = await (
            await conn.execute("SELECT status,count(*) FROM document_versions GROUP BY status ORDER BY count(*) DESC")
        ).fetchall()
        usage = await (
            await conn.execute(
                "SELECT days.day::date::text, count(a.audit_id) FILTER(WHERE a.action='search.performed'), "
                "count(a.audit_id) FILTER(WHERE a.action IN ('chat.answered','chat.blocked')) "
                "FROM generate_series(current_date-13,current_date,interval '1 day') AS days(day) "
                "LEFT JOIN audit_log a ON a.created_at>=days.day AND a.created_at<days.day+interval '1 day' "
                "AND a.action IN ('search.performed','chat.answered','chat.blocked') "
                "GROUP BY days.day ORDER BY days.day"
            )
        ).fetchall()
        activity = await (
            await conn.execute(
                "SELECT a.audit_id,a.action,a.actor_id,a.created_at FROM audit_log a "
                "WHERE a.action IN ('document.uploaded','version.approved','version.rejected','version.published', "
                "'document.retired','auth.registered') ORDER BY a.audit_id DESC LIMIT 10"
            )
        ).fetchall()
    names = (
        "documents",
        "published",
        "pending_approval",
        "processing",
        "failed",
        "versions",
        "users",
        "searches",
        "questions",
    )
    return {
        "counts": dict(zip(names, counts, strict=True)),
        "categories": [{"name": name, "count": count} for name, count in categories],
        "statuses": [{"name": name, "count": count} for name, count in statuses],
        "usage": [{"date": day, "searches": searches, "questions": questions} for day, searches, questions in usage],
        "activity": [{"id": row[0], "action": row[1], "actor": row[2], "at": row[3]} for row in activity],
    }


@router.get("/documents/{document_id}/compare")
async def compare(
    document_id: UUID,
    from_version: UUID,
    to_version: UUID,
    user: User = Depends(admin),
    state: AppState = Depends(get_state),
):
    async def version_text(vid: UUID) -> str:
        async with state.pool.connection() as conn:
            row = await (
                await conn.execute(
                    "SELECT v.object_key,v.filename,v.content_type FROM document_versions v "
                    "JOIN documents d USING(document_id) WHERE v.version_id=%s AND v.document_id=%s "
                    "AND d.deleted_at IS NULL",
                    (vid, document_id),
                )
            ).fetchone()
        if not row:
            raise ApiError(404, "not_found", "The document version was not found.")
        try:
            pages = await asyncio.to_thread(extract_pages, await state.blobs.get(row[0]), row[1], row[2])
            return "\n".join(pages)
        except PermanentError as error:
            raise ApiError(400, error.code, "This version cannot be previewed.") from error

    before, after = await asyncio.gather(version_text(from_version), version_text(to_version))
    changes = await asyncio.to_thread(lambda: list(ndiff(before.splitlines(), after.splitlines())))
    lines = [
        {"kind": {"- ": "removed", "+ ": "added", "  ": "equal"}[line[:2]], "text": line[2:]}
        for line in changes
        if line[:2] != "? "
    ]
    return {
        "document_id": str(document_id),
        "from_version": str(from_version),
        "to_version": str(to_version),
        "lines": lines,
        "added": sum(line["kind"] == "added" for line in lines),
        "removed": sum(line["kind"] == "removed" for line in lines),
    }
