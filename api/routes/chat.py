import json
import time

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from api.auth import personas, require_group
from api.deps import AppState, get_state
from api.errors import ApiError
from assistant.answer import answer
from assistant.phi import screen
from assistant.store import make_deps
from common import audit
from common.llm.runtime import resolve_llm
from common.metrics import CHAT_SECONDS, EGRESS, GUARDRAIL_BLOCKS
from common.models import User

router = APIRouter(prefix="/api")


class ChatBody(BaseModel):
    message: str = Field(min_length=2, max_length=2000)
    conversation_id: str | None = None


def record_metrics(final: dict, seconds: float) -> None:
    CHAT_SECONDS.observe(seconds)
    receipt = final["receipt"]
    if final.get("fallback") in ("refused", "clinical_guard", "citations", "egress_policy", "out_of_scope",
                                  "phi_blocked", "model_hedge"):
        GUARDRAIL_BLOCKS.labels(final["fallback"]).inc()
    if receipt.get("egress_decision") not in (None, "none"):
        EGRESS.labels(receipt["egress_decision"]).inc()


def sse(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data, default=str)}\n\n"


# The assistant is for staff; an operator-only account (no all-staff group) is refused here, not just hidden in the UI.
STAFF = Depends(require_group("all-staff"))


@router.post("/chat")
async def chat(body: ChatBody, user: User = STAFF, state: AppState = Depends(get_state)):
    persona = personas()["personas"].get(user.user_id, {})
    deps = make_deps(state, persona.get("categories_first"), llm=await resolve_llm(state))

    async def stream():
        started = time.perf_counter()
        async for event in answer(body.message, user, persona.get("role", ""), body.conversation_id, deps):
            if event.type == "final":
                record_metrics(event.data, time.perf_counter() - started)
            yield sse(event.type, event.data)
    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


TITLE_CHARS = 80


def title_of(first_question: str) -> str:
    text = " ".join(first_question.split())
    return text if len(text) <= TITLE_CHARS else text[: TITLE_CHARS - 1].rstrip() + "…"


@router.get("/conversations")
async def list_conversations(user: User = STAFF, state: AppState = Depends(get_state)):
    """The signed-in person's recent conversations, newest first, titled by their first (redacted) question."""
    async with state.pool.connection() as conn:
        rows = await (await conn.execute(
            "SELECT c.conversation_id::text, max(m.created_at) AS updated_at, count(*) AS messages, "
            "COALESCE(c.title, (SELECT f.content_redacted FROM messages f WHERE f.conversation_id = c.conversation_id "
            " AND f.role = 'user' ORDER BY f.created_at LIMIT 1)) AS title "
            "FROM conversations c JOIN messages m USING (conversation_id) "
            "WHERE c.user_id = %s AND c.expires_at > now() "
            "GROUP BY c.conversation_id ORDER BY updated_at DESC LIMIT 30", (user.user_id,))).fetchall()
    return [{"conversation_id": r[0], "updated_at": r[1], "messages": r[2], "title": title_of(r[3] or "")}
            for r in rows]


class RenameBody(BaseModel):
    title: str = Field(max_length=TITLE_CHARS)

    @field_validator("title")
    @classmethod
    def not_blank(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("A title needs at least one character.")
        return value


@router.patch("/conversations/{conversation_id}")
async def rename_conversation(conversation_id: str, body: RenameBody, user: User = STAFF,
                              state: AppState = Depends(get_state)):
    """Rename one of the person's conversations. Titles get the same PHI redaction as the questions they replace."""
    title = title_of(screen(body.title).redacted)
    async with state.pool.connection() as conn, conn.transaction():
        result = await conn.execute(
            "UPDATE conversations SET title = %s WHERE conversation_id::text = %s AND user_id = %s "
            "AND expires_at > now()", (title, conversation_id, user.user_id))
        if result.rowcount == 0:
            raise ApiError(404, "not_found", "Not found.")
        await audit.record(conn, user.user_id, "conversation.renamed", conversation_id)
    return {"conversation_id": conversation_id, "title": title}


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str, user: User = STAFF,
                           state: AppState = Depends(get_state)):
    async with state.pool.connection() as conn:
        rows = await (await conn.execute(
            "SELECT m.role, m.content_redacted, m.citations, m.confidence, m.receipt, m.created_at FROM messages m "
            "JOIN conversations c USING (conversation_id) WHERE c.conversation_id = %s AND c.user_id = %s "
            "ORDER BY m.created_at", (conversation_id, user.user_id))).fetchall()
    if not rows:
        raise ApiError(404, "not_found", "Not found.")
    keys = ["role", "content", "citations", "confidence", "receipt", "created_at"]
    return {"conversation_id": conversation_id, "messages": [dict(zip(keys, r, strict=True)) for r in rows]}


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: str, user: User = STAFF,
                              state: AppState = Depends(get_state)):
    async with state.pool.connection() as conn, conn.transaction():
        result = await conn.execute("DELETE FROM conversations WHERE conversation_id = %s AND user_id = %s",
                                    (conversation_id, user.user_id))
        if result.rowcount == 0:
            raise ApiError(404, "not_found", "Not found.")
        await audit.record(conn, user.user_id, "conversation.deleted", conversation_id)
