"""Covers: CP-5 (no PHI or document text in logs), E11-1."""
import json
import logging

from common.logging import JsonFormatter


def test_log_record_drops_text_fields():
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "processed %s", ("v1",), None)
    record.version_id = "v1"
    record.text = "Patient John Smith"
    record.question = "MRN 123"
    out = json.loads(JsonFormatter("api").format(record))
    assert out["message"] == "processed v1" and out["version_id"] == "v1" and out["service"] == "api"
    assert "text" not in out and "question" not in out


def test_metrics_names_registered():
    from common import metrics
    names = {m.describe()[0].name for m in metrics.REGISTRY_METRICS}
    assert {"outbox_unpublished", "stream_pending", "messages_processed", "stage_duration_seconds", "reclaims",
            "dead_letters", "chat_latency_seconds", "guardrail_blocks", "egress_decisions"} <= names
