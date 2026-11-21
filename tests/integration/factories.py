import uuid

from common.blob.local import LocalBlobStore
from common.config import Settings
from common.embed import HashingEmbedder
from pipeline.consumer import Ctx


def make_ctx(pool, tmp_path, redis=None, embedder=None, name="w1"):
    settings = Settings(_env_file=None, blob_root=str(tmp_path))
    return Ctx(pool=pool, redis=redis, blobs=LocalBlobStore(str(tmp_path)),
               embedder=embedder or HashingEmbedder(), settings=settings, consumer_name=name)


async def create_version(ctx, content: bytes, filename="policy.md", status="QUEUED", document_id=None,
                         version_number=1, title="Hand Hygiene Policy", groups=("all-staff",),
                         classification="internal", category="Infection Control", uploaded_by="alex"):
    did = document_id or str(uuid.uuid4())
    vid = str(uuid.uuid4())
    key = f"originals/{did}/{vid}/{filename}"
    await ctx.blobs.put(key, content, "application/octet-stream")
    async with ctx.pool.connection() as conn, conn.transaction():
        if document_id is None:
            await conn.execute(
                "INSERT INTO documents (document_id, title, category, department, classification, owner_id) "
                "VALUES (%s, %s, %s, 'Nursing', %s, %s)", (did, title, category, classification, uploaded_by))
            for group in groups:
                await conn.execute("INSERT INTO document_acl VALUES (%s, %s)", (did, group))
        await conn.execute(
            "INSERT INTO document_versions (version_id, document_id, version_number, status, object_key, filename, "
            "content_type, content_sha256, uploaded_by, approved_by) VALUES (%s,%s,%s,%s,%s,%s,'text/plain','h',%s,%s)",
            (vid, did, version_number, status, key, filename, uploaded_by, "taylor"))
    return did, vid


async def scalar(pool, sql, params=()):
    async with pool.connection() as conn:
        return (await (await conn.execute(sql, params)).fetchone())[0]


async def outbox_events(pool, event_type):
    async with pool.connection() as conn:
        rows = await (await conn.execute(
            "SELECT payload FROM outbox WHERE event_type = %s ORDER BY id", (event_type,))).fetchall()
    return [r[0] for r in rows]


async def run_pipeline(ctx, vid):
    """Drive one version through every stage directly (no Redis): extract → each batch → finalize."""
    from pipeline.stages import embed, extract, finalize
    await extract.handle_approved(ctx, {"version_id": vid})
    for payload in await outbox_events(ctx.pool, "batch.ready"):
        if payload["version_id"] == vid:
            await embed.handle_batch(ctx, payload)
    if any(p["version_id"] == vid for p in await outbox_events(ctx.pool, "version.embedded")):
        await finalize.handle_embedded(ctx, {"version_id": vid})
