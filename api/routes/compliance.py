import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from api.auth import require_group
from api.deps import AppState, get_state
from api.errors import ApiError
from common.models import User
from pipeline.consumer import PermanentError
from pipeline.stages.extract import extract_pages

router = APIRouter(prefix="/api")
compliance = require_group("compliance")


async def _audit_rows(state: AppState, actor: str | None, action: str | None, start: datetime | None,
                      end: datetime | None, limit: int, offset: int) -> list[dict]:
    async with state.pool.connection() as conn:
        rows = await (await conn.execute(
            "SELECT audit_id, actor_id, action, target, detail, created_at FROM audit_log "
            "WHERE (%(actor)s::text IS NULL OR actor_id = %(actor)s) "
            "AND (%(action)s::text IS NULL OR action LIKE %(action)s || '%%') "
            "AND (%(start)s::timestamptz IS NULL OR created_at >= %(start)s) "
            "AND (%(end)s::timestamptz IS NULL OR created_at <= %(end)s) "
            "ORDER BY audit_id DESC LIMIT %(limit)s OFFSET %(offset)s",
            {"actor": actor, "action": action, "start": start, "end": end, "limit": limit,
             "offset": offset})).fetchall()
    keys = ["audit_id", "actor_id", "action", "target", "detail", "created_at"]
    return [dict(zip(keys, r, strict=True)) for r in rows]


@router.get("/audit")
async def audit_log(actor: str | None = None, action: str | None = None,
                    start: datetime | None = Query(None, alias="from"), end: datetime | None = Query(None, alias="to"),
                    page: int = Query(1, ge=1), user: User = Depends(compliance), state: AppState = Depends(get_state)):
    items = await _audit_rows(state, actor, action, start, end, 50, (page - 1) * 50)
    return {"page": page, "items": items}


@router.get("/audit.csv")
async def audit_csv(actor: str | None = None, action: str | None = None, user: User = Depends(compliance),
                    state: AppState = Depends(get_state)):
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["audit_id", "created_at", "actor_id", "action", "target", "detail"])
    for row in await _audit_rows(state, actor, action, None, None, 10_000, 0):
        writer.writerow([row["audit_id"], row["created_at"], row["actor_id"], row["action"], row["target"],
                         row["detail"]])
    return Response(out.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=audit.csv"})


@router.get("/egress")
async def egress(user: User = Depends(compliance), state: AppState = Depends(get_state)):
    async with state.pool.connection() as conn:
        rows = await (await conn.execute(
            "SELECT created_at, actor_id, action, detail FROM audit_log WHERE action IN "
            "('egress.llm_call', 'egress.blocked') OR (action IN ('chat.answered', 'chat.blocked') "
            "AND detail->>'egress' IS NOT NULL AND detail->>'egress' <> 'none') ORDER BY audit_id DESC LIMIT 20"
        )).fetchall()
    return [{"created_at": r[0], "actor_id": r[1], "action": r[2], "detail": r[3]} for r in rows]


@router.get("/deletions")
async def deletions(user: User = Depends(compliance), state: AppState = Depends(get_state)):
    async with state.pool.connection() as conn:
        rows = await (await conn.execute(
            "SELECT created_at, actor_id, target, detail FROM audit_log WHERE action = 'document.deleted' "
            "ORDER BY audit_id DESC LIMIT 100")).fetchall()
    return [{"created_at": r[0], "actor_id": r[1], "document_id": r[2], "detail": r[3]} for r in rows]


@router.get("/versions/{version_id}/preview")
async def preview(version_id: str, user: User = Depends(require_group("compliance", "doc-admins")),
                  state: AppState = Depends(get_state)):
    async with state.pool.connection() as conn:
        row = await (await conn.execute("SELECT object_key, filename, content_type FROM document_versions "
                                        "WHERE version_id = %s", (version_id,))).fetchone()
    if row is None:
        raise ApiError(404, "not_found", "Not found.")
    try:
        pages = extract_pages(await state.blobs.get(row[0]), row[1], row[2])
        text = "\n".join(pages)[:1000]
    except PermanentError as error:
        text = f"(Preview unavailable: {error.message})"
    return {"version_id": version_id, "text": text}
