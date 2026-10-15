"""Covers: FR-6, RL-6, CR-1, CR-3, CR-4, CR-6, CP-7."""
import asyncio

import pytest

from pipeline.consumer import PermanentError, TransientError
from pipeline.stages import delete, embed, extract, finalize
from tests.fixtures.make_docs import bad_fixtures
from tests.integration.factories import create_version, make_ctx, outbox_events, run_pipeline, scalar

LONG_MD = "# Policy\n\n" + "\n\n".join(f"## Section {i}\n" + ("Clean hands save lives. " * 80) for i in range(12))


@pytest.fixture
def ctx(pool, tmp_path):
    return make_ctx(pool, tmp_path)


async def status(pool, vid):
    return await scalar(pool, "SELECT status FROM document_versions WHERE version_id = %s", (vid,))


async def test_pipeline_reaches_ready(ctx):
    did, vid = await create_version(ctx, LONG_MD.encode())
    await run_pipeline(ctx, vid)
    assert await status(ctx.pool, vid) == "READY"
    total = await scalar(ctx.pool, "SELECT chunks_total FROM document_versions WHERE version_id=%s", (vid,))
    assert total > 16
    assert await scalar(ctx.pool, "SELECT count(*) FROM document_embeddings") == total
    assert str(await scalar(ctx.pool, "SELECT active_version_id FROM documents WHERE document_id=%s", (did,))) == vid


async def test_extract_handler_idempotent(ctx):
    _, vid = await create_version(ctx, LONG_MD.encode())
    await extract.handle_approved(ctx, {"version_id": vid})
    first = await scalar(ctx.pool, "SELECT array_agg(chunk_id ORDER BY chunk_index) FROM document_chunks")
    async with ctx.pool.connection() as conn:
        await conn.execute("UPDATE document_versions SET stage='EXTRACT' WHERE version_id=%s", (vid,))
    await extract.handle_approved(ctx, {"version_id": vid})
    assert await scalar(ctx.pool, "SELECT array_agg(chunk_id ORDER BY chunk_index) FROM document_chunks") == first
    batches = len(await outbox_events(ctx.pool, "batch.ready"))
    assert batches == await scalar(ctx.pool, "SELECT count(*) FROM embed_batches")


async def test_concurrent_batches_one_finalize(ctx):
    _, vid = await create_version(ctx, LONG_MD.encode())
    await extract.handle_approved(ctx, {"version_id": vid})
    payloads = await outbox_events(ctx.pool, "batch.ready")
    await asyncio.gather(*(embed.handle_batch(ctx, p) for p in payloads))
    assert len(await outbox_events(ctx.pool, "version.embedded")) == 1


async def test_duplicate_batch_delivery_no_new_vectors(ctx):
    _, vid = await create_version(ctx, LONG_MD.encode())
    await extract.handle_approved(ctx, {"version_id": vid})
    payload = (await outbox_events(ctx.pool, "batch.ready"))[0]
    await embed.handle_batch(ctx, payload)
    before = await scalar(ctx.pool, "SELECT count(*) FROM document_embeddings")
    await embed.handle_batch(ctx, payload)
    assert await scalar(ctx.pool, "SELECT count(*) FROM document_embeddings") == before


async def test_finalize_requires_all_embeddings(ctx):
    _, vid = await create_version(ctx, LONG_MD.encode())
    await extract.handle_approved(ctx, {"version_id": vid})
    await embed.handle_batch(ctx, (await outbox_events(ctx.pool, "batch.ready"))[0])
    with pytest.raises(TransientError):
        await finalize.handle_embedded(ctx, {"version_id": vid})
    assert await status(ctx.pool, vid) == "PROCESSING"


async def test_finalize_supersedes_previous(ctx):
    did, v1 = await create_version(ctx, b"# A\nVersion one text about gloves.")
    await run_pipeline(ctx, v1)
    _, v2 = await create_version(ctx, b"# A\nVersion two text about gloves.", document_id=did, version_number=2)
    await run_pipeline(ctx, v2)
    assert (await status(ctx.pool, v1), await status(ctx.pool, v2)) == ("SUPERSEDED", "READY")


async def test_finalize_never_downgrades_active_version(ctx):
    """Review Focus 1: v3 finishes first; a late v2 must not replace it."""
    did, v1 = await create_version(ctx, b"# A\nOne.")
    await run_pipeline(ctx, v1)
    _, v2 = await create_version(ctx, b"# A\nTwo.", document_id=did, version_number=2)
    _, v3 = await create_version(ctx, b"# A\nThree.", document_id=did, version_number=3)
    await run_pipeline(ctx, v3)
    await run_pipeline(ctx, v2)
    assert await status(ctx.pool, v3) == "READY"
    assert await status(ctx.pool, v2) == "SUPERSEDED"
    assert str(await scalar(ctx.pool, "SELECT active_version_id FROM documents WHERE document_id=%s", (did,))) == v3


async def test_concurrent_first_publications_leave_only_newest_ready(ctx):
    """Covers: CR-1, CR-6. Both finalizers start before the document has an active version."""
    did, v1 = await create_version(ctx, b"# A\nFirst policy version.")
    _, v2 = await create_version(ctx, b"# A\nSecond policy version.", document_id=did, version_number=2)
    for vid in (v1, v2):
        await extract.handle_approved(ctx, {"version_id": vid})
    for payload in await outbox_events(ctx.pool, "batch.ready"):
        await embed.handle_batch(ctx, payload)

    tasks = []
    try:
        async with ctx.pool.connection() as conn, conn.transaction():
            await conn.execute("SELECT document_id FROM documents WHERE document_id = %s FOR UPDATE", (did,))
            tasks = [asyncio.create_task(finalize.handle_embedded(ctx, {"version_id": vid})) for vid in (v1, v2)]

            async def both_waiting():
                while await scalar(ctx.pool, "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                                  "AND wait_event_type = 'Lock' AND query LIKE %s", ("%documents%",)) < 2:
                    await asyncio.sleep(0.01)

            await asyncio.wait_for(both_waiting(), 5)
        await asyncio.wait_for(asyncio.gather(*tasks), 5)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    assert await status(ctx.pool, v1) == "SUPERSEDED"
    assert await status(ctx.pool, v2) == "READY"
    assert str(await scalar(ctx.pool, "SELECT active_version_id FROM documents WHERE document_id=%s", (did,))) == v2


@pytest.mark.parametrize("name", ["scanned.pdf", "encrypted.pdf", "empty.txt", "binary-renamed.md"])
async def test_bad_files_fail_with_code(ctx, name):
    data, code = bad_fixtures()[name]
    _, vid = await create_version(ctx, data, filename=name)
    with pytest.raises(PermanentError) as caught:
        await extract.handle_approved(ctx, {"version_id": vid})
    await extract.on_permanent(ctx, {"version_id": vid}, caught.value)
    assert await status(ctx.pool, vid) == "FAILED"
    assert await scalar(ctx.pool, "SELECT error_code FROM document_versions WHERE version_id=%s", (vid,)) == code
    assert await scalar(ctx.pool, "SELECT count(*) FROM audit_log WHERE action='version.failed'") == 1


async def test_zero_chunks_fail_not_ready(ctx):
    _, vid = await create_version(ctx, b"# Only a heading\n")
    with pytest.raises(PermanentError) as caught:
        await extract.handle_approved(ctx, {"version_id": vid})
    assert caught.value.code == "empty_document"


async def test_delete_purges_everything_and_is_rerunnable(ctx):
    did, vid = await create_version(ctx, LONG_MD.encode())
    await run_pipeline(ctx, vid)
    receipt = await delete.handle_delete(ctx, {"document_id": did, "requested_by": "taylor"})
    assert receipt["chunks"] > 0 and receipt["vectors"] > 0 and receipt["objects"] >= 2
    assert await scalar(ctx.pool, "SELECT count(*) FROM document_chunks") == 0
    assert await ctx.blobs.list_prefix(f"originals/{did}/") == []
    again = await delete.handle_delete(ctx, {"document_id": did, "requested_by": "taylor"})
    assert again == {**again, "chunks": 0, "vectors": 0, "objects": 0}
