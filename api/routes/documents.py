from datetime import date

import psycopg
from fastapi import APIRouter, Depends, File, Form, Header, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from api import idempotency
from api.auth import current_user, known_groups, require_group
from api.deps import AppState, get_state
from api.errors import ApiError
from common.models import User
from documents import queries, service
from documents.validation import validate_upload

router = APIRouter(prefix="/api")


def _groups(raw: str) -> tuple[str, ...]:
    return tuple(sorted({g.strip() for g in raw.split(",") if g.strip()}))


async def _idempotent(state: AppState, user: User, key: str, sha: str, create):
    """Run `create(conn)` once per Idempotency-Key, inside one transaction with the key row."""
    for _ in range(2):
        try:
            async with state.pool.connection() as conn, conn.transaction():
                if key:
                    replay = await idempotency.lookup(conn, key, user.user_id, sha)
                    if replay is not None:
                        return JSONResponse(replay, status_code=202, headers={"Idempotent-Replay": "true"})
                ref = await create(conn)
                body = ref.as_dict()
                if key:
                    await idempotency.store(conn, key, user.user_id, sha, body)
                return JSONResponse(body, status_code=202)
        except psycopg.errors.UniqueViolation:
            continue  # a concurrent request with the same key won; replay its response
    raise ApiError(409, "idempotency_conflict", "Concurrent request with the same Idempotency-Key.")


@router.post("/documents", status_code=202)
async def upload_document(
    file: UploadFile = File(...), title: str = Form(...), category: str = Form(...), department: str = Form("General"),
    classification: str = Form(...), groups: str = Form(...), effective_date: date | None = Form(None),
    review_due: date | None = Form(None), idempotency_key: str = Header(""),
    user: User = Depends(require_group("doc-admins")), state: AppState = Depends(get_state),
):
    data = await file.read()
    kind, sha = validate_upload(file.filename, file.content_type, data, state.settings.max_upload_bytes)
    meta = service.DocumentMeta(title, category, department, classification, _groups(groups), effective_date,
                                review_due)
    req = idempotency.request_hash("POST /documents", data, title, category, department, classification, groups)

    async def create(conn):
        return await service.create_document(conn, state.blobs, user, meta, file.filename or "", kind, sha, data,
                                             known_groups())
    return await _idempotent(state, user, idempotency_key, req, create)


@router.post("/documents/{document_id}/versions", status_code=202)
async def upload_version(
    document_id: str, file: UploadFile = File(...), effective_date: date | None = Form(None),
    review_due: date | None = Form(None), idempotency_key: str = Header(""),
    user: User = Depends(require_group("doc-admins")), state: AppState = Depends(get_state),
):
    data = await file.read()
    kind, sha = validate_upload(file.filename, file.content_type, data, state.settings.max_upload_bytes)
    req = idempotency.request_hash(f"POST /documents/{document_id}/versions", data)

    async def create(conn):
        return await service.create_version(conn, state.blobs, user, document_id, file.filename or "", kind, sha,
                                            data, effective_date, review_due)
    return await _idempotent(state, user, idempotency_key, req, create)


class ApproveBody(BaseModel):
    comment: str = ""


class RejectBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


@router.post("/versions/{version_id}/approve", status_code=202)
async def approve(version_id: str, body: ApproveBody, user: User = Depends(require_group("compliance")),
                  state: AppState = Depends(get_state)):
    async with state.pool.connection() as conn, conn.transaction():
        await service.approve(conn, user, version_id, body.comment)
    return {"version_id": version_id, "status": "QUEUED"}


@router.post("/versions/{version_id}/reject")
async def reject(version_id: str, body: RejectBody, user: User = Depends(require_group("compliance")),
                 state: AppState = Depends(get_state)):
    async with state.pool.connection() as conn, conn.transaction():
        await service.reject(conn, user, version_id, body.reason)
    return {"version_id": version_id, "status": "REJECTED"}


@router.get("/documents")
async def list_documents(category: str | None = None, status: str | None = None, q: str | None = None,
                         user: User = Depends(current_user), state: AppState = Depends(get_state)):
    async with state.pool.connection() as conn:
        return await queries.list_documents(conn, user, category, status, q)


@router.get("/documents/{document_id}")
async def get_document(document_id: str, user: User = Depends(current_user), state: AppState = Depends(get_state)):
    async with state.pool.connection() as conn:
        doc = await queries.readable_document(conn, user, document_id)
    if doc is None:
        raise ApiError(404, "not_found", "Not found.")
    return doc


@router.get("/versions/{version_id}/text")
async def version_text(version_id: str, user: User = Depends(current_user), state: AppState = Depends(get_state)):
    async with state.pool.connection() as conn:
        did = await queries.version_document(conn, version_id)
        doc = await queries.readable_document(conn, user, did) if did else None
        if doc is None or user.groups == frozenset({"operators"}):
            raise ApiError(404, "not_found", "Not found.")
        return {"document": {k: doc[k] for k in ("document_id", "title", "category", "classification",
                                                  "active_version_id")},
                "version": next(v for v in doc["versions"] if v["version_id"] == version_id),
                "chunks": await queries.version_text(conn, version_id)}


@router.get("/versions/{version_id}/status")
async def version_status(version_id: str, user: User = Depends(require_group("doc-admins", "compliance", "operators")),
                         state: AppState = Depends(get_state)):
    async with state.pool.connection() as conn:
        status = await queries.version_status(conn, version_id)
    if status is None:
        raise ApiError(404, "not_found", "Not found.")
    return status


@router.get("/versions")
async def versions(status: str = "PENDING_APPROVAL", user: User = Depends(require_group("compliance", "doc-admins")),
                   state: AppState = Depends(get_state)):
    async with state.pool.connection() as conn:
        return await queries.pending_versions(conn)


@router.post("/documents/{document_id}/retire")
async def retire(document_id: str, user: User = Depends(require_group("doc-admins")),
                 state: AppState = Depends(get_state)):
    async with state.pool.connection() as conn, conn.transaction():
        await service.retire(conn, user, document_id)
    return {"document_id": document_id, "retired": True}


@router.delete("/documents/{document_id}", status_code=202)
async def delete(document_id: str, user: User = Depends(require_group("compliance")),
                 state: AppState = Depends(get_state)):
    async with state.pool.connection() as conn, conn.transaction():
        await service.request_delete(conn, user, document_id)
    return {"document_id": document_id, "status": "DELETING"}
