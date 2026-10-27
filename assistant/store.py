"""Postgres-backed ChatDeps: retrieval, conversations (redacted, with expiry), audit and answer cache."""
import json
import uuid
from dataclasses import replace
from typing import Any

from assistant.answer import MAX_PASSAGES, ChatDeps
from assistant.history import permitted_turns
from assistant.injection import redact_secrets
from assistant.types import Passage
from common import audit
from search.query import search

BOOST = {"diagnostic_support": {"Clinical Policy", "Emergency Response", "Patient Safety"},
         "clinical_reference": {"Clinical Policy", "Emergency Response", "Patient Safety", "Infection Control"}}


class OutageAwareLLM:
    """Honours the provider-outage drill (a Redis key with a 30 s TTL)."""

    def __init__(self, llm, redis) -> None:
        self.llm, self.redis, self.info = llm, redis, llm.info

    async def stream(self, messages, max_tokens: int = 600):
        from common.llm import ProviderUnavailable
        try:
            down = await self.redis.exists("drill:provider_outage")
        except Exception:
            down = False
        if down:
            raise ProviderUnavailable("provider outage (drill)")
        async for token in self.llm.stream(messages, max_tokens):
            yield token


def make_deps(state, categories_first: list[str] | None = None, llm=None) -> ChatDeps:
    pool, s = state.pool, state.settings
    llm = llm or state.llm

    async def retrieve(user, question: str, label: str) -> list[Passage]:
        async with pool.connection() as conn:
            hits = await search(conn, state.embedder, user, question, top_k=8, text_weight=s.hybrid_text_weight)
            boosted = BOOST.get(label, set()) | set(categories_first or [])
            ranked = sorted(hits, key=lambda h: h.score + (0.05 if h.category in boosted else 0), reverse=True)
            passages = [Passage(i, h.chunk_id, h.document_id, h.title, h.version_number, h.section, h.page,
                                h.classification, h.text, h.score, h.version_id, h.category)
                        for i, h in enumerate(ranked, start=1)]
            if not passages or passages[0].score < s.min_relevance:
                return passages
            best = passages[0]
            # A name/title match may be only a document's header. Include nearby sections so a question about
            # the document can use its contents. Recheck eligibility here, including for chunks without embeddings.
            rows = await (await conn.execute(
                "SELECT c.chunk_id::text, c.section, c.page_number, c.text FROM document_chunks c "
                "JOIN documents d USING (document_id) JOIN document_versions v USING (version_id) "
                "JOIN document_chunks anchor ON anchor.chunk_id = %s AND anchor.version_id = c.version_id "
                "WHERE c.document_id = %s AND c.version_id = %s AND c.chunk_id <> anchor.chunk_id "
                "AND d.active_version_id = c.version_id AND v.status = 'READY' "
                "AND d.retired_at IS NULL AND d.deleted_at IS NULL "
                "AND EXISTS (SELECT 1 FROM document_acl a WHERE a.document_id = d.document_id "
                "AND a.group_name = ANY(%s)) "
                "ORDER BY abs(c.chunk_index - anchor.chunk_index), c.chunk_index LIMIT 3",
                (best.chunk_id, best.document_id, best.version_id, list(user.groups)))).fetchall()
        # Context inherits the document match, not an invented high similarity score. Each chunk keeps its own
        # citation identity, and all context still passes through the normal injection and egress guards.
        context = [Passage(0, chunk, best.document_id, best.title, best.version_number, section, page,
                           best.classification, text, s.min_relevance, best.version_id, best.category)
                   for chunk, section, page, text in rows]
        # Preserve every strong search hit and its actual score; context fills otherwise weak/free slots.
        ordered = [p for p in passages if p.score >= s.min_relevance]
        seen = {p.chunk_id for p in ordered}
        ordered.extend(p for p in context if p.chunk_id not in seen)
        seen.update(p.chunk_id for p in ordered)
        ordered.extend(p for p in passages if p.chunk_id not in seen)
        return [replace(p, index=i) for i, p in enumerate(ordered[:MAX_PASSAGES], start=1)]

    async def save(user, conversation_id: str | None, question: str, final: dict) -> str:
        async with pool.connection() as conn, conn.transaction():
            cid = conversation_id
            if cid:
                row = await (await conn.execute("SELECT user_id FROM conversations WHERE conversation_id = %s",
                                                (cid,))).fetchone()
                if row is None or row[0] != user.user_id:
                    cid = None
            if cid is None:
                cid = str(uuid.uuid4())
                await conn.execute("INSERT INTO conversations (conversation_id, user_id, expires_at) "
                                   "VALUES (%s, %s, now() + make_interval(days => %s))",
                                   (cid, user.user_id, s.chat_retention_days))
            await conn.execute("INSERT INTO messages (message_id, conversation_id, role, content_redacted) "
                               "VALUES (%s, %s, 'user', %s)", (str(uuid.uuid4()), cid, redact_secrets(question)[0]))
            await conn.execute(
                "INSERT INTO messages (message_id, conversation_id, role, content_redacted, citations, confidence, "
                "receipt) VALUES (%s, %s, 'assistant', %s, %s::jsonb, %s, %s::jsonb)",
                (str(uuid.uuid4()), cid, final["answer"], json.dumps(final["citations"], default=str),
                 final["confidence"], json.dumps(final["receipt"], default=str)))
        return cid

    async def history(user, conversation_id: str | None) -> list[tuple[str, str]]:
        if not conversation_id:
            return []
        async with pool.connection() as conn:
            rows = await (await conn.execute(
                "SELECT m.role, m.content_redacted, m.citations FROM messages m "
                "JOIN conversations c USING (conversation_id) "
                "WHERE c.conversation_id = %s AND c.user_id = %s AND c.expires_at > now() "
                "ORDER BY m.created_at, CASE WHEN m.role = 'user' THEN 0 ELSE 1 END",
                (conversation_id, user.user_id))).fetchall()
            chunk_ids = [citation["chunk_id"] for _, _, citations in rows for citation in citations or []]
            sources = await (await conn.execute(
                "SELECT c.chunk_id::text, c.version_id::text, d.classification FROM document_chunks c "
                "JOIN documents d USING (document_id) JOIN document_versions v USING (version_id) "
                "WHERE c.chunk_id = ANY(%s::uuid[]) AND d.active_version_id = c.version_id "
                "AND v.status = 'READY' AND d.retired_at IS NULL AND d.deleted_at IS NULL "
                "AND EXISTS (SELECT 1 FROM document_acl a WHERE a.document_id = d.document_id "
                "AND a.group_name = ANY(%s))", (chunk_ids, list(user.groups)))).fetchall()
        visible = {chunk: {"version_id": version, "classification": classification}
                   for chunk, version, classification in sources}
        return permitted_turns(rows, visible, llm.info.external, s.external_max_classification)

    async def record(user, action: str, detail: dict) -> None:
        async with pool.connection() as conn:
            await audit.record(conn, user.user_id, action, None, detail)

    async def cache_get(key: str) -> dict[str, Any] | None:
        async with pool.connection() as conn:
            row = await (await conn.execute("SELECT answer FROM answer_cache WHERE key = %s", (key,))).fetchone()
        return row[0] if row else None

    async def cache_put(key: str, value: dict, document_ids: list[str]) -> None:
        async with pool.connection() as conn:
            await conn.execute("INSERT INTO answer_cache (key, answer, document_ids) VALUES (%s, %s::jsonb, %s) "
                               "ON CONFLICT (key) DO UPDATE SET answer = EXCLUDED.answer, "
                               "document_ids = EXCLUDED.document_ids, created_at = now()",
                               (key, json.dumps(value), document_ids))

    return ChatDeps(retrieve=retrieve, llm=OutageAwareLLM(llm, state.redis), settings=s, save=save,
                    history=history, audit=record,
                    cache_get=cache_get, cache_put=cache_put)
