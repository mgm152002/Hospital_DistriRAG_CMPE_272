import asyncio
import json
import time

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from api.auth import require_group
from api.deps import AppState, get_state
from api.errors import ApiError
from common.models import User
from pipeline import drills, recovery, streams

router = APIRouter(prefix="/api")
operators = require_group("operators")
watchers = require_group("operators", "doc-admins", "compliance")

BOARD_SQL = """
SELECT v.version_id::text, v.document_id::text, d.title, v.version_number, v.status, v.stage, v.chunks_total,
       v.chunks_embedded, v.error_code, v.updated_at
FROM document_versions v JOIN documents d ON d.document_id = v.document_id
WHERE d.deleted_at IS NULL AND (%(ids)s::uuid[] IS NULL OR v.version_id = ANY(%(ids)s))
ORDER BY v.updated_at DESC LIMIT 100
"""
BOARD_KEYS = ["version_id", "document_id", "title", "version_number", "status", "stage", "chunks_total",
              "chunks_embedded", "error_code", "updated_at"]


async def board(state: AppState, ids: list[str] | None = None) -> list[dict]:
    async with state.pool.connection() as conn:
        rows = await (await conn.execute(BOARD_SQL, {"ids": ids})).fetchall()
    return [dict(zip(BOARD_KEYS, r, strict=True)) for r in rows]


@router.get("/ops/streams")
async def stream_stats(user: User = Depends(operators), state: AppState = Depends(get_state)):
    out = []
    for stream, group in streams.GROUPS.items():
        info = {"stream": stream, "group": group, "length": 0, "pending": 0, "lag": 0, "consumers": [], "dlq": 0}
        try:
            info["length"] = await state.redis.xlen(stream)
            for g in await state.redis.xinfo_groups(stream):
                if g["name"] == group:
                    info["pending"], info["lag"] = g["pending"], g.get("lag") or 0
            info["consumers"] = [{"name": c["name"], "pending": c["pending"], "idle_ms": c["idle"]}
                                 for c in await state.redis.xinfo_consumers(stream, group)]
            info["dlq"] = await state.redis.xlen(streams.dlq(stream))
        except Exception as error:
            info["error"] = type(error).__name__
        out.append(info)
    async with state.pool.connection() as conn:
        unpublished = (await (await conn.execute("SELECT count(*) FROM outbox WHERE published_at IS NULL")
                              ).fetchone())[0]
    return {"streams": out, "outbox_unpublished": unpublished}


@router.get("/ops/events")
async def ops_events(since: int = 0, user: User = Depends(watchers), state: AppState = Depends(get_state)):
    async with state.pool.connection() as conn:
        rows = await (await conn.execute(
            "SELECT id, kind, version_id::text, detail, created_at FROM ops_events WHERE id > %s ORDER BY id LIMIT 200",
            (since,))).fetchall()
    return [{"id": r[0], "kind": r[1], "version_id": r[2], "detail": r[3], "created_at": r[4]} for r in rows]


@router.get("/pipeline/board")
async def pipeline_board(user: User = Depends(watchers), state: AppState = Depends(get_state)):
    return await board(state)


@router.get("/pipeline/events")
async def pipeline_events(max_seconds: float = Query(3600, ge=0.5, le=3600), user: User = Depends(watchers),
                          state: AppState = Depends(get_state)):
    async def stream():
        async with state.pool.connection() as conn:
            last = (await (await conn.execute("SELECT coalesce(max(id), 0) FROM ops_events")).fetchone())[0]
        for card in reversed(await board(state)):
            yield f"event: version\ndata: {json.dumps(card, default=str)}\n\n"
        deadline = time.monotonic() + max_seconds
        while time.monotonic() < deadline:
            await asyncio.sleep(1)
            async with state.pool.connection() as conn:
                rows = await (await conn.execute(
                    "SELECT id, kind, version_id::text, detail FROM ops_events WHERE id > %s ORDER BY id LIMIT 200",
                    (last,))).fetchall()
            if not rows:
                yield ": keep-alive\n\n"
                continue
            last = rows[-1][0]
            ids = sorted({r[2] for r in rows if r[2]})
            for r in rows:
                event = {'id': r[0], 'kind': r[1], 'version_id': r[2], 'detail': r[3]}
                yield f"event: ops\ndata: {json.dumps(event)}\n\n"
            for card in await board(state, ids) if ids else []:
                yield f"event: version\ndata: {json.dumps(card, default=str)}\n\n"
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.get("/ops/dead-letters")
async def dead_letters(user: User = Depends(operators), state: AppState = Depends(get_state)):
    async with state.pool.connection() as conn:
        rows = await (await conn.execute(
            "SELECT id, stream, message_id, payload->'payload'->>'version_id', deliveries, error, replays, created_at, "
            "replayed_at FROM dead_letters ORDER BY id DESC LIMIT 100")).fetchall()
    keys = ["id", "stream", "message_id", "version_id", "deliveries", "error", "replays", "created_at", "replayed_at"]
    return [dict(zip(keys, r, strict=True)) for r in rows]


@router.post("/ops/dead-letters/{dead_letter_id}/replay", status_code=202)
async def replay(dead_letter_id: int, user: User = Depends(operators), state: AppState = Depends(get_state)):
    try:
        await recovery.replay_dead_letter(state.pool, dead_letter_id, user.user_id)
    except LookupError as error:
        raise ApiError(404, "not_found", "Dead letter not found.") from error
    return {"id": dead_letter_id, "status": "requeued"}


@router.post("/ops/drills/{name}", status_code=202)
async def drill(name: str, user: User = Depends(operators), state: AppState = Depends(get_state)):
    if name not in drills.DRILLS:
        raise ApiError(404, "unknown_drill", f"Drills: {', '.join(drills.DRILLS)}.")
    return await drills.run_drill(name, state, user)
