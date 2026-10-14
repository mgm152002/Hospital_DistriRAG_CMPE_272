"""version.embedded → atomically publish the version (CR-1, CR-6). Never replaces a newer active version."""
from common import audit
from common.models import Stage, VersionStatus
from pipeline import events, repo
from pipeline.consumer import PermanentError, TransientError


async def handle_embedded(ctx, payload: dict) -> None:
    vid = payload["version_id"]
    async with ctx.pool.connection() as conn, conn.transaction():
        version = await repo.load_version(conn, vid)
        if version is None or version["status"] in (VersionStatus.READY, VersionStatus.SUPERSEDED):
            return
        # Serialize every publication for a document, including its first one.
        # An inner join to active_version_id locks nothing when that field is NULL.
        did = version["document_id"]
        await conn.execute("SELECT document_id FROM documents WHERE document_id = %s FOR UPDATE", (did,))
        version = await repo.load_version(conn, vid, lock=True)
        if version is None or version["status"] in (VersionStatus.READY, VersionStatus.SUPERSEDED):
            return
        total, embedded = await (await conn.execute(
            "SELECT count(c.chunk_id), count(e.chunk_id) FROM document_chunks c "
            "LEFT JOIN document_embeddings e ON e.chunk_id = c.chunk_id WHERE c.version_id = %s", (vid,))).fetchone()
        if total == 0:
            raise PermanentError("empty_document", "The document produced no chunks.")
        if embedded != total:
            raise TransientError(f"{total - embedded} chunks still lack embeddings")
        await repo.set_stage(conn, vid, VersionStatus.PROCESSING, Stage.FINALIZE)
        active = await (await conn.execute(
            "SELECT v.version_id::text, v.version_number FROM documents d "
            "JOIN document_versions v ON v.version_id = d.active_version_id WHERE d.document_id = %s",
            (did,))).fetchone()
        if active and active[1] > version["version_number"]:
            await repo.set_stage(conn, vid, VersionStatus.SUPERSEDED, None)
            await audit.record(conn, "system", "version.superseded", vid, {"newer_active": active[0]})
            await events.emit(conn, "version.superseded", vid, {"newer_active": active[0]})
            return
        if active:
            await repo.set_stage(conn, active[0], VersionStatus.SUPERSEDED, None)
        await conn.execute("UPDATE document_versions SET status = %s, stage = NULL, chunks_embedded = %s, "
                           "updated_at = now() WHERE version_id = %s", (VersionStatus.READY, embedded, vid))
        await conn.execute("UPDATE documents SET active_version_id = %s WHERE document_id = %s", (vid, did))
        await conn.execute("DELETE FROM answer_cache WHERE %s = ANY(document_ids)", (did,))
        await audit.record(conn, "system", "version.published", vid,
                           {"document_id": did, "version_number": version["version_number"], "chunks": total})
        await events.emit(conn, "version.ready", vid, {"chunks": total, "consumer": ctx.consumer_name})
