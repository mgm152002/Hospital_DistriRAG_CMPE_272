"""batch.ready → embed one batch; the transaction that completes the last batch enqueues finalize (CR-1, CR-3)."""
from common.db import vector_literal
from pipeline import events, outbox, streams
from pipeline.consumer import TransientError


async def handle_batch(ctx, payload: dict) -> None:
    vid, number = payload["version_id"], int(payload["batch_no"])
    async with ctx.pool.connection() as conn:
        row = await (await conn.execute(
            "SELECT chunk_from, chunk_to, done_at FROM embed_batches WHERE version_id = %s AND batch_no = %s",
            (vid, number))).fetchone()
        if row is None or row[2] is not None:
            return  # version deleted, or a duplicate delivery of finished work
        chunks = await (await conn.execute(
            "SELECT chunk_id::text, text FROM document_chunks WHERE version_id = %s AND chunk_index BETWEEN %s AND %s "
            "ORDER BY chunk_index", (vid, row[0], row[1]))).fetchall()
    if ctx.redis is not None and await ctx.redis.exists("drill:provider_outage"):
        raise TransientError("embedding provider outage (drill)")
    try:
        vectors = await ctx.embedder.embed([text for _, text in chunks])
    except Exception as error:
        raise TransientError(f"embedding failed: {error}") from error
    async with ctx.pool.connection() as conn, conn.transaction():
        async with conn.cursor() as cur:
            await cur.executemany(
                "INSERT INTO document_embeddings (chunk_id, embedding) VALUES (%s, %s::vector) "
                "ON CONFLICT (chunk_id) DO UPDATE SET embedding = EXCLUDED.embedding",
                [(cid, vector_literal(v)) for (cid, _), v in zip(chunks, vectors, strict=True)])
        await conn.execute("UPDATE embed_batches SET done_at = now() WHERE version_id = %s AND batch_no = %s",
                           (vid, number))
        version = await (await conn.execute(
            "SELECT chunks_total FROM document_versions WHERE version_id = %s FOR UPDATE", (vid,))).fetchone()
        if version is None:
            return
        embedded = (await (await conn.execute(
            "SELECT count(*) FROM document_chunks c JOIN document_embeddings e ON e.chunk_id = c.chunk_id "
            "WHERE c.version_id = %s", (vid,))).fetchone())[0]
        await conn.execute(
            "UPDATE document_versions SET chunks_embedded = %s, updated_at = now() WHERE version_id = %s",
            (embedded, vid))
        await events.emit(conn, "stage.progress", vid, {"stage": "EMBED", "embedded": embedded, "total": version[0],
                                                       "batch": number, "consumer": ctx.consumer_name})
        if embedded == version[0]:
            await outbox.enqueue(conn, streams.FINALIZE, "version.embedded", f"finalize:{vid}", {"version_id": vid})
