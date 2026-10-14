"""document.delete → purge file, text, chunks, vectors and cached answers; write a deletion receipt (CP-7)."""
from common import audit
from pipeline import events


async def handle_delete(ctx, payload: dict) -> dict:
    did = payload["document_id"]
    objects = 0
    for prefix in (f"originals/{did}/", f"text/{did}/"):
        objects += await ctx.blobs.delete_prefix(prefix)
    async with ctx.pool.connection() as conn, conn.transaction():
        chunks = (await (await conn.execute("SELECT count(*) FROM document_chunks WHERE document_id = %s",
                                            (did,))).fetchone())[0]
        vectors = (await (await conn.execute(
            "SELECT count(*) FROM document_embeddings e JOIN document_chunks c ON c.chunk_id = e.chunk_id "
            "WHERE c.document_id = %s", (did,))).fetchone())[0]
        cache = await conn.execute("DELETE FROM answer_cache WHERE %s = ANY(document_ids)", (did,))
        await conn.execute("DELETE FROM document_chunks WHERE document_id = %s", (did,))
        await conn.execute("UPDATE documents SET deleted_at = coalesce(deleted_at, now()), active_version_id = NULL "
                           "WHERE document_id = %s", (did,))
        receipt = {"document_id": did, "requested_by": payload.get("requested_by", "system"), "objects": objects,
                   "chunks": chunks, "vectors": vectors, "cache_rows": cache.rowcount}
        await audit.record(conn, payload.get("requested_by", "system"), "document.deleted", did, receipt)
        await events.emit(conn, "document.deleted", None, {"document_id": did})
    return receipt
