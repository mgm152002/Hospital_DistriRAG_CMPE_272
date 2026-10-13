"""Covers: RL-4, RL-5, RL-6."""
import json

from pipeline.consumer import Consumer, Ctx, PermanentError
from tests.fakes import RecordingRedis


def make(handler, on_permanent=None):
    redis = RecordingRedis()
    ctx = Ctx(pool=None, redis=redis, blobs=None, embedder=None, settings=None, consumer_name="w1")
    consumer = Consumer(ctx, "ingest.extract", "extractors", {"version.approved": handler}, on_permanent=on_permanent)
    return consumer, redis


FIELDS = {"event_id": "1", "type": "version.approved", "payload": json.dumps({"version_id": "v1"})}


async def test_ack_only_after_commit():
    async def handler(ctx, payload):
        raise RuntimeError("commit failed")
    consumer, redis = make(handler)
    assert await consumer.handle("1-0", FIELDS) == "retry"
    assert redis.acks == []


async def test_success_acks_after_handler_returns():
    order = []

    async def handler(ctx, payload):
        order.append("committed")
    consumer, redis = make(handler)
    assert await consumer.handle("1-0", FIELDS) == "ok"
    assert order == ["committed"] and redis.acks == [("ingest.extract", "extractors", "1-0")]


async def test_permanent_error_acks_once_and_records():
    recorded = []

    async def handler(ctx, payload):
        raise PermanentError("pdf_encrypted", "PDF is encrypted")

    async def on_permanent(ctx, payload, error):
        recorded.append((payload["version_id"], error.code))
    consumer, redis = make(handler, on_permanent)
    assert await consumer.handle("1-0", FIELDS) == "failed"
    assert recorded == [("v1", "pdf_encrypted")] and len(redis.acks) == 1


async def test_unknown_event_type_is_acked_and_dropped():
    consumer, redis = make(lambda ctx, p: None)
    assert await consumer.handle("1-0", {**FIELDS, "type": "nope"}) == "dropped"
    assert len(redis.acks) == 1
