"""Recovery (RL-5, RL-7, RL-8, CP-6): reclaim idle messages with exponential backoff, dead-letter after
max deliveries, re-drive versions stuck in Postgres, purge expired data and orphan blobs."""
import asyncio
import contextlib
import json
import logging
import time
from typing import Any

from common import audit
from common.metrics import DEAD_LETTERS, RECLAIMS
from common.models import Stage, VersionStatus
from pipeline import events, outbox, streams

log = logging.getLogger("distrirag.recovery")


def due_idle_ms(deliveries: int, base: int) -> int:
    """60 s, 120 s, 240 s … capped at 10× the base (600 s in production)."""
    return min(base * 2 ** max(deliveries - 1, 0), base * 10)


async def _pending(redis, stream: str, group: str, count: int = 50) -> list[dict]:
    return await redis.xpending_range(stream, group, min="-", max="+", count=count)


def make_reclaimer(base_idle_ms: int, max_deliveries: int):
    async def reclaim(consumer) -> list[tuple[str, dict]]:
        ctx = consumer.ctx
        for item in await _pending(ctx.redis, consumer.stream, consumer.group):
            deliveries = item["times_delivered"]
            idle = item["time_since_delivered"]
            if deliveries >= max_deliveries or idle < due_idle_ms(deliveries, base_idle_ms):
                continue
            claimed = await ctx.redis.xclaim(consumer.stream, consumer.group, ctx.consumer_name,
                                             min_idle_time=due_idle_ms(deliveries, base_idle_ms),
                                             message_ids=[item["message_id"]])
            if not claimed:
                continue
            message_id, fields = claimed[0]
            if fields is None:
                await ctx.redis.xack(consumer.stream, consumer.group, message_id)
                continue
            payload = json.loads(fields.get("payload") or "{}")
            RECLAIMS.inc()
            async with ctx.pool.connection() as conn:
                await events.emit(conn, "message.reclaimed", payload.get("version_id"), {
                    "stream": consumer.stream, "from": item["consumer"], "to": ctx.consumer_name,
                    "idle_ms": idle, "delivery": deliveries + 1})
            log.info("reclaimed %s from %s after %d ms (delivery %d)", message_id, item["consumer"], idle,
                     deliveries + 1)
            return [(message_id, fields)]
        return []
    return reclaim


async def dead_letter(ctx, stream: str, group: str, max_deliveries: int, base_idle_ms: int) -> int:
    moved = 0
    for item in await _pending(ctx.redis, stream, group, count=100):
        deliveries = item["times_delivered"]
        if deliveries < max_deliveries or item["time_since_delivered"] < due_idle_ms(deliveries, base_idle_ms):
            continue
        message_id = item["message_id"]
        found = await ctx.redis.xrange(stream, min=message_id, max=message_id)
        fields = found[0][1] if found else {}
        payload = json.loads(fields.get("payload") or "{}")
        record = {"type": fields.get("type"), "payload": payload}
        await ctx.redis.xadd(streams.dlq(stream), {"message_id": message_id, "type": fields.get("type", ""),
                                                   "payload": json.dumps(payload), "deliveries": deliveries})
        async with ctx.pool.connection() as conn, conn.transaction():
            await conn.execute("INSERT INTO dead_letters (stream, message_id, payload, deliveries, error) "
                               "VALUES (%s, %s, %s::jsonb, %s, %s)",
                               (stream, message_id, json.dumps(record), deliveries, "max_retries_exceeded"))
            if payload.get("version_id"):
                await conn.execute(
                    "UPDATE document_versions SET status = %s, error_code = 'max_retries_exceeded', "
                    "error = %s, updated_at = now() WHERE version_id = %s AND status <> 'READY'",
                    (VersionStatus.FAILED, f"Gave up after {deliveries} deliveries on {stream}",
                     payload["version_id"]))
                await audit.record(conn, "system", "version.failed", payload["version_id"],
                                   {"error_code": "max_retries_exceeded", "stream": stream})
            await events.emit(conn, "dead_lettered", payload.get("version_id"),
                              {"stream": stream, "deliveries": deliveries})
        await ctx.redis.xack(stream, group, message_id)
        DEAD_LETTERS.inc()
        moved += 1
    return moved


async def replay_dead_letter(pool, dead_letter_id: int, actor: str) -> None:
    async with pool.connection() as conn, conn.transaction():
        row = await (await conn.execute("SELECT stream, payload, replays FROM dead_letters WHERE id = %s FOR UPDATE",
                                        (dead_letter_id,))).fetchone()
        if row is None:
            raise LookupError("dead letter not found")
        stream, record, replays = row
        payload = record.get("payload", {})
        vid = payload.get("version_id")
        if vid:
            status, stage = ((VersionStatus.QUEUED, None) if stream == streams.EXTRACT
                             else (VersionStatus.PROCESSING, Stage.EMBED))
            await conn.execute("UPDATE document_versions SET status = %s, stage = %s, error_code = NULL, "
                               "error = NULL, updated_at = now() WHERE version_id = %s", (status, stage, vid))
        await outbox.enqueue(conn, stream, record.get("type") or "version.approved",
                             f"replay:{dead_letter_id}:{replays + 1}", payload)
        await conn.execute("UPDATE dead_letters SET replays = replays + 1, replayed_at = now() WHERE id = %s",
                           (dead_letter_id,))
        await audit.record(conn, actor, "dead_letter.replayed", str(dead_letter_id), {"stream": stream})


async def _pending_version_ids(redis) -> set[str]:
    ids: set[str] = set()
    for stream, group in streams.GROUPS.items():
        with contextlib.suppress(Exception):
            for item in await _pending(redis, stream, group, count=1000):
                found = await redis.xrange(stream, min=item["message_id"], max=item["message_id"])
                if found:
                    vid = json.loads(found[0][1].get("payload") or "{}").get("version_id")
                    if vid:
                        ids.add(vid)
    return ids


async def redrive_stuck(pool, redis, stuck_after_s: int) -> int:
    """Re-enqueue versions stuck in QUEUED/PROCESSING with no pending message and no unpublished outbox row.
    Covers Redis data loss and 'committed but never published'."""
    pending = await _pending_version_ids(redis)
    count = 0
    stamp = int(time.time() * 1000)
    async with pool.connection() as conn, conn.transaction():
        rows = await (await conn.execute(
            "SELECT v.version_id::text, v.status, v.stage FROM document_versions v "
            "WHERE v.status IN ('QUEUED', 'PROCESSING') AND v.updated_at < now() - make_interval(secs => %s) "
            "AND NOT EXISTS (SELECT 1 FROM outbox o WHERE o.published_at IS NULL "
            "                AND o.payload->>'version_id' = v.version_id::text) "
            "FOR UPDATE SKIP LOCKED", (stuck_after_s,))).fetchall()
        for vid, _status, stage in rows:
            if vid in pending:
                continue
            if stage in (Stage.EMBED, Stage.FINALIZE):
                missing = await (await conn.execute(
                    "SELECT batch_no FROM embed_batches WHERE version_id = %s AND done_at IS NULL", (vid,))).fetchall()
                for (number,) in missing:
                    await outbox.enqueue(conn, streams.EMBED, "batch.ready", f"embed:{vid}:{number}:redrive:{stamp}",
                                         {"version_id": vid, "batch_no": number})
                if not missing:
                    await outbox.enqueue(conn, streams.FINALIZE, "version.embedded",
                                         f"finalize:{vid}:redrive:{stamp}", {"version_id": vid})
            else:
                await outbox.enqueue(conn, streams.EXTRACT, "version.approved", f"extract:{vid}:redrive:{stamp}",
                                     {"version_id": vid})
            await conn.execute("UPDATE document_versions SET updated_at = now() WHERE version_id = %s", (vid,))
            await events.emit(conn, "redriven", vid, {"stage": stage})
            count += 1
    return count


async def purge_retention(pool, s) -> dict[str, int]:
    async with pool.connection() as conn, conn.transaction():
        conversations = (await conn.execute("DELETE FROM conversations WHERE expires_at < now()")).rowcount
        keys = (await conn.execute("DELETE FROM idempotency_keys WHERE created_at < now() - interval '24 hours'"
                                   )).rowcount
        sessions = (await conn.execute("DELETE FROM auth_sessions WHERE expires_at < now()")).rowcount
        attempts = (await conn.execute("DELETE FROM auth_attempts WHERE created_at < now()-interval '1 day'")).rowcount
        await conn.execute("SET LOCAL distrirag.allow_audit_purge = 'on'")
        audit_rows = (await conn.execute("DELETE FROM audit_log WHERE created_at < now() - make_interval(days => %s)",
                                         (s.audit_retention_days,))).rowcount
        counts = {"conversations": conversations, "idempotency_keys": keys, "audit": audit_rows,
                  "sessions": sessions, "auth_attempts": attempts}
        await audit.record(conn, "system", "retention.purged", None, counts)
    return counts


async def purge_orphan_blobs(pool, blobs, older_than_s: int = 86_400) -> int:
    removed = 0
    keys = await blobs.list_prefix("originals/")
    async with pool.connection() as conn:
        known = {r[0] for r in await (await conn.execute("SELECT version_id::text FROM document_versions")).fetchall()}
    for key in keys:
        parts = key.split("/")
        if len(parts) < 4 or parts[2] in known:
            continue
        age = await blobs.age_seconds(key) if hasattr(blobs, "age_seconds") else None
        if age is None or age < older_than_s:
            continue
        removed += await blobs.delete_prefix("/".join(parts[:3]) + "/")
    return removed


async def run(ctx, stop: asyncio.Event) -> None:
    s = ctx.settings
    last: dict[str, float] = {"redrive": 0.0, "daily": 0.0}
    while not stop.is_set():
        try:
            for stream, group in streams.GROUPS.items():
                await dead_letter(ctx, stream, group, s.max_deliveries, s.reclaim_base_idle_ms)
            now = time.monotonic()
            if now - last["redrive"] >= 60:
                last["redrive"] = now
                await redrive_stuck(ctx.pool, ctx.redis, s.stuck_after_seconds)
            if now - last["daily"] >= 86_400:
                last["daily"] = now
                await purge_retention(ctx.pool, s)
                await purge_orphan_blobs(ctx.pool, ctx.blobs)
        except Exception as error:
            log.warning("recovery loop error: %r", error)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=15)


def describe(_: Any = None) -> str:
    return "reclaim · dead letters · re-drive · retention"
