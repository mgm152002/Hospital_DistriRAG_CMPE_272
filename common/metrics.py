"""Prometheus metrics (spec E11-1)."""
from prometheus_client import Counter, Gauge, Histogram

OUTBOX_UNPUBLISHED = Gauge("outbox_unpublished", "Outbox rows not yet published to Redis")
STREAM_PENDING = Gauge("stream_pending", "Pending (delivered, unacknowledged) messages", ["stream"])
MESSAGES = Counter("messages_processed", "Stream messages handled", ["stream", "result"])
STAGE_SECONDS = Histogram("stage_duration_seconds", "Handler duration", ["stream"],
                          buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60))
RECLAIMS = Counter("reclaims", "Messages reclaimed from another consumer")
DEAD_LETTERS = Counter("dead_letters", "Messages moved to a dead-letter stream")
CHAT_SECONDS = Histogram("chat_latency_seconds", "Chat request duration", buckets=(0.25, 0.5, 1, 2, 5, 10, 20, 60))
GUARDRAIL_BLOCKS = Counter("guardrail_blocks", "Answers replaced by a guardrail", ["check"])
EGRESS = Counter("egress_decisions", "Egress policy decisions", ["decision"])
REGISTRY_METRICS = [OUTBOX_UNPUBLISHED, STREAM_PENDING, MESSAGES, STAGE_SECONDS, RECLAIMS, DEAD_LETTERS, CHAT_SECONDS,
                    GUARDRAIL_BLOCKS, EGRESS]


async def refresh_gauges(state) -> None:
    from pipeline import streams
    async with state.pool.connection() as conn:
        row = await (await conn.execute("SELECT count(*) FROM outbox WHERE published_at IS NULL")).fetchone()
        OUTBOX_UNPUBLISHED.set(row[0])
    for stream, group in streams.GROUPS.items():
        try:
            info = await state.redis.xpending(stream, group)
            STREAM_PENDING.labels(stream).set(info["pending"])
        except Exception:
            STREAM_PENDING.labels(stream).set(0)
