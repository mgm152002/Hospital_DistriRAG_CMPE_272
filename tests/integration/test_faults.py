"""Fault-injection suite (spec E13-3, TS-2). Every test checks the final state AND that nothing was duplicated or lost.
Covers: RL-3, RL-4, RL-5, RL-6, RL-7, RL-8, RL-9, CR-1, CR-3, CR-5, CR-6, CR-7, FR-5, TS-2, AT-05, AT-09, AT-10,
AT-11, AT-12, AT-13."""
import asyncio
import contextlib
import os

import pytest
import redis.asyncio as aioredis

import run
from common.embed import SlowEmbedder
from pipeline import recovery, streams
from pipeline.relay import relay_once
from search.query import search
from tests.fixtures.make_docs import bad_fixtures
from tests.integration import harness
from tests.integration.api_client import as_user, build_state, client, upload_form
from tests.integration.factories import create_version, make_ctx, scalar

LONG = ("# Blood Transfusion\n\n" + "\n\n".join(
    f"## Step {i}\n" + "Check two identifiers and record vital signs before and during the transfusion. " * 12
    for i in range(10))).encode()


@pytest.fixture
async def redis():
    r = aioredis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    await r.flushall()
    await streams.ensure_groups(r)
    yield r
    await r.aclose()


@pytest.fixture
async def stack(pool, redis, tmp_path):
    """In-process relay + workers + recovery with fast timings. Yields (state, start, stop)."""
    state = build_state(pool, redis, tmp_path, reclaim_base_idle_ms=300, stuck_after_seconds=2)
    stop = asyncio.Event()
    tasks: list[asyncio.Task] = []

    async def start(roles=("relay", "worker", "recovery")):
        tasks.extend(await run.start_background(state, stop, embed_consumers=2, roles=roles))
    yield state, start, stop
    stop.set()
    await asyncio.gather(*tasks, return_exceptions=True)


async def test_worker_killed_mid_embed(pool, redis, tmp_path):
    """A real SIGKILL of a worker process in the middle of an embed batch."""
    ctx = make_ctx(pool, tmp_path, redis)
    _, vid = await create_version(ctx, LONG)
    victim = harness.start_worker(str(tmp_path), "victim", EMBED_DELAY_MS="1500")
    try:
        await harness.approve(pool, vid)
        while await relay_once(pool, redis):
            pass

        async def embedding_in_flight():
            await relay_once(pool, redis)
            info = await redis.xpending(streams.EMBED, streams.GROUPS[streams.EMBED])
            return info["pending"] > 0
        assert await harness.wait_for(embedding_in_flight, timeout=30)
    finally:
        harness.kill(victim)
    rescuer = harness.start_worker(str(tmp_path), "rescuer")
    try:
        async def relay_until_ready():
            await relay_once(pool, redis)
            return await harness.status(pool, vid) == "READY"
        assert await harness.wait_for(relay_until_ready, timeout=60)
    finally:
        harness.kill(rescuer)
    await harness.assert_no_duplicates(pool, vid)
    assert await scalar(pool, "SELECT count(*) FROM ops_events WHERE kind = 'message.reclaimed'") >= 1


async def test_relay_crash_after_xadd(pool, redis, tmp_path, stack):
    """The relay dies after XADD and before commit: the event is published twice, handled once in effect."""
    state, start, _ = stack
    _, vid = await create_version(make_ctx(pool, tmp_path), LONG)
    await harness.approve(pool, vid)

    class CrashAfterXadd:
        def __init__(self, inner):
            self.inner = inner

        async def xadd(self, *args, **kwargs):
            await self.inner.xadd(*args, **kwargs)
            raise ConnectionError("relay crashed after XADD")
    with pytest.raises(ConnectionError):
        await relay_once(pool, CrashAfterXadd(redis))
    assert await redis.xlen(streams.EXTRACT) == 1
    assert await scalar(pool, "SELECT count(*) FROM outbox WHERE published_at IS NULL") == 1
    await start()
    assert await harness.wait_status(pool, vid, "READY")
    assert await redis.xlen(streams.EXTRACT) == 2
    await harness.assert_no_duplicates(pool, vid)
    assert await scalar(pool, "SELECT count(*) FROM outbox WHERE event_type = 'version.embedded'") == 1


async def test_redis_restart(pool, redis, tmp_path, stack):
    """Redis restarts (SHUTDOWN SAVE; compose restarts it). AOF keeps pending work; workers reconnect."""
    state, start, _ = stack
    _, vid = await create_version(make_ctx(pool, tmp_path), LONG)
    await harness.approve(pool, vid)
    while await relay_once(pool, redis):
        pass
    with contextlib.suppress(Exception):  # the server closes the connection as it shuts down
        await redis.execute_command("SHUTDOWN", "SAVE")

    async def back():
        try:
            return await redis.ping()
        except Exception:
            return False
    assert await harness.wait_for(back, timeout=40, every=0.5)
    assert await redis.xlen(streams.EXTRACT) == 1
    await start()
    assert await harness.wait_status(pool, vid, "READY", timeout=60)
    await harness.assert_no_duplicates(pool, vid)


async def test_redis_data_loss(pool, redis, tmp_path, stack):
    """Redis loses everything mid-ingest: recovery re-drives from Postgres."""
    state, start, _ = stack
    ctx = make_ctx(pool, tmp_path)
    _, vid = await create_version(ctx, LONG)
    await harness.approve(pool, vid)
    while await relay_once(pool, redis):
        pass
    await redis.flushall()
    await streams.ensure_groups(redis)
    async with pool.connection() as conn:
        await conn.execute("UPDATE document_versions SET updated_at = now() - interval '1 hour' WHERE version_id = %s",
                           (vid,))
    await recovery.redrive_stuck(pool, redis, stuck_after_s=2)
    await start()
    assert await harness.wait_status(pool, vid, "READY", timeout=60)
    await harness.assert_no_duplicates(pool, vid)


async def test_duplicate_delivery(pool, redis, tmp_path, stack):
    """The same batch.ready event arrives twice: no extra vectors, one finalize."""
    state, start, _ = stack
    _, vid = await create_version(make_ctx(pool, tmp_path), LONG)
    await harness.approve(pool, vid)
    await start()
    assert await harness.wait_status(pool, vid, "READY")
    before = await scalar(pool, "SELECT count(*) FROM document_embeddings")
    first = (await redis.xrange(streams.EMBED, count=1))[0][1]
    await redis.xadd(streams.EMBED, first)
    await asyncio.sleep(2)
    assert await scalar(pool, "SELECT count(*) FROM document_embeddings") == before
    assert await scalar(pool, "SELECT count(*) FROM outbox WHERE event_type = 'version.embedded'") == 1
    assert (await redis.xpending(streams.EMBED, streams.GROUPS[streams.EMBED]))["pending"] == 0


async def test_api_crash_between_blob_and_db(pool, redis, tmp_path):
    """The API dies after storing the file and before committing: no version row; the orphan file is cleaned up."""
    state = build_state(pool, redis, tmp_path)
    real_put = state.blobs.put

    async def put_then_crash(key, data, content_type):
        await real_put(key, data, content_type)
        raise RuntimeError("api crashed after blob put")
    state.blobs.put = put_then_crash
    async with client(state) as api:
        with pytest.raises(RuntimeError):
            await api.post("/api/documents", headers=as_user("alex"), data=upload_form(),
                           files={"file": ("hand.md", b"# Hand\nRub hands.", "text/markdown")})
    assert await scalar(pool, "SELECT count(*) FROM document_versions") == 0
    assert len(await state.blobs.list_prefix("originals/")) == 1
    assert await recovery.purge_orphan_blobs(pool, state.blobs, older_than_s=0) == 1
    assert await state.blobs.list_prefix("originals/") == []


async def test_transient_embed_failure(pool, redis, tmp_path, stack):
    """The embedder fails twice with 503, then works: retried with backoff, READY, third delivery succeeds."""
    state, start, _ = stack
    calls = {"n": 0}
    inner = state.embedder

    class Flaky:
        dim = 384

        async def embed(self, texts):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise RuntimeError("503 Service Unavailable")
            return await inner.embed(texts)
    state.embedder = Flaky()
    _, vid = await create_version(make_ctx(pool, tmp_path), b"# Short\nOne small policy about gloves and gowns.")
    await harness.approve(pool, vid)
    await start()
    assert await harness.wait_status(pool, vid, "READY", timeout=30)
    deliveries = await scalar(
        pool, "SELECT max((detail->>'delivery')::int) FROM ops_events WHERE kind = 'message.reclaimed'")
    assert deliveries == 3
    await harness.assert_no_duplicates(pool, vid)


@pytest.mark.parametrize("name", ["scanned.pdf", "encrypted.pdf", "corrupt.pdf", "empty.txt", "binary-renamed.md"])
async def test_permanent_failures(pool, redis, tmp_path, stack, name):
    """Malformed files fail with a clear code and are delivered exactly once."""
    state, start, _ = stack
    data, code = bad_fixtures()[name]
    _, vid = await create_version(make_ctx(pool, tmp_path), data, filename=name)
    await harness.approve(pool, vid)
    await start()
    assert await harness.wait_status(pool, vid, "FAILED")
    assert await scalar(pool, "SELECT error_code FROM document_versions WHERE version_id = %s", (vid,)) == code
    assert await scalar(pool, "SELECT count(*) FROM ops_events WHERE kind = 'message.reclaimed'") == 0
    assert (await redis.xpending(streams.EXTRACT, streams.GROUPS[streams.EXTRACT]))["pending"] == 0


async def test_dead_letter_and_replay(pool, redis, tmp_path, stack):
    """The embedder always fails: dead-lettered after 5 deliveries; replay after the fix reaches READY."""
    state, start, _ = stack
    inner = state.embedder
    broken = {"on": True}

    class Broken:
        dim = 384

        async def embed(self, texts):
            if broken["on"]:
                raise RuntimeError("provider down")
            return await inner.embed(texts)
    state.embedder = Broken()
    _, vid = await create_version(make_ctx(pool, tmp_path), b"# Short\nA policy about sharps containers.")
    await harness.approve(pool, vid)
    state.settings.max_deliveries = 5
    await start()
    assert await harness.wait_status(pool, vid, "FAILED", timeout=60)
    assert await scalar(pool, "SELECT error_code FROM document_versions WHERE version_id = %s", (vid,)) == \
        "max_retries_exceeded"
    assert await scalar(pool, "SELECT deliveries FROM dead_letters") == 5
    broken["on"] = False
    await recovery.replay_dead_letter(pool, await scalar(pool, "SELECT id FROM dead_letters"), "casey")
    assert await harness.wait_status(pool, vid, "READY", timeout=30)
    await harness.assert_no_duplicates(pool, vid)


async def test_version_visibility(pool, redis, tmp_path, stack):
    """While v2 is processing, search returns only v1; after finalize, only v2. Never a mix."""
    state, start, _ = stack
    ctx = make_ctx(pool, tmp_path)
    did, v1 = await create_version(ctx, b"# Visitors\nVisiting hours are 8:00 to 20:00 every day.",
                                   title="Visitor Policy")
    await harness.approve(pool, v1)
    await start()
    assert await harness.wait_status(pool, v1, "READY")
    from api.auth import persona_user
    sam = persona_user("sam")
    state.embedder = SlowEmbedder(state.embedder, 1500)
    _, v2 = await create_version(ctx, b"# Visitors\nVisiting hours are 7:00 to 21:00 every day.", document_id=did,
                                 version_number=2)
    await harness.approve(pool, v2)
    seen = set()
    for _ in range(40):
        async with pool.connection() as conn:
            hits = await search(conn, state.embedder.inner, sam, "visiting hours")
        versions = {h.version_id for h in hits if h.document_id == did}
        assert len(versions) == 1, versions
        seen |= versions
        if await harness.status(pool, v2) == "READY":
            break
        await asyncio.sleep(0.25)
    async with pool.connection() as conn:
        final = {h.version_id for h in await search(conn, state.embedder.inner, sam, "visiting hours")}
    assert v1 in seen and final == {v2}


async def test_unapproved_not_indexed(pool, redis, tmp_path, stack):
    state, start, _ = stack
    await start()
    async with client(state) as api:
        r = await api.post("/api/documents", headers=as_user("alex"), data=upload_form(),
                           files={"file": ("hand.md", b"# Hand\nRub hands with alcohol rub.", "text/markdown")})
        assert r.status_code == 202
        await asyncio.sleep(1.5)
        assert await scalar(pool, "SELECT count(*) FROM outbox") == 0
        assert (await api.get("/api/search", params={"q": "alcohol rub"}, headers=as_user("sam"))).json() == []


async def test_permission_isolation(pool, redis, tmp_path, stack):
    state, start, _ = stack
    ctx = make_ctx(pool, tmp_path)
    _, vid = await create_version(ctx, b"# Waste\nControlled substance waste needs a witness.", groups=("pharmacy",),
                                  classification="restricted", title="Controlled Substance Waste")
    await harness.approve(pool, vid)
    await start()
    assert await harness.wait_status(pool, vid, "READY")
    async with client(state) as api:
        for user, visible in [("jordan", True), ("sam", False), ("riley", False), ("priya", False), ("casey", False)]:
            hits = (await api.get("/api/search", params={"q": "controlled substance waste"},
                                  headers=as_user(user))).json()
            assert bool(hits) == visible, user


async def test_idempotent_upload(pool, redis, tmp_path):
    async with client(build_state(pool, redis, tmp_path)) as api:
        files = {"file": ("hand.md", b"# Hand\nRub hands.", "text/markdown")}
        first = await api.post("/api/documents", headers=as_user("alex", **{"Idempotency-Key": "k"}),
                               data=upload_form(), files=files)
        again = await api.post("/api/documents", headers=as_user("alex", **{"Idempotency-Key": "k"}),
                               data=upload_form(), files=files)
        changed = await api.post("/api/documents", headers=as_user("alex", **{"Idempotency-Key": "k"}),
                                 data=upload_form(title="Other"), files=files)
    assert first.json() == again.json() and changed.status_code == 409
    assert await scalar(pool, "SELECT count(*) FROM document_versions") == 1
