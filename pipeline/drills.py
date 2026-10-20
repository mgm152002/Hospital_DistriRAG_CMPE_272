"""Recovery drills for the demo (UX-8, RL-9). They need no Docker socket: each one flips a Redis switch, sends a
Redis command, or uploads a known-bad file through the normal service functions."""
import pathlib

from common import audit
from documents import service
from documents.validation import validate_upload
from pipeline import events, recovery, streams

KILL_KEY = "drill:kill"
OUTAGE_KEY = "drill:provider_outage"
POISON = pathlib.Path(__file__).resolve().parents[1] / "corpus" / "bad" / "scanned.pdf"
DRILLS = ("kill-worker", "restart-redis", "poison-file", "provider-outage", "retention-now")


class KilledByDrill(BaseException):
    """Raised inside a consumer to simulate a crash after commit and before XACK."""


async def run_drill(name: str, state, actor) -> dict:
    detail: dict = {}
    if name == "kill-worker":
        await state.redis.set(KILL_KEY, streams.EMBED, ex=300)
        detail = {"target": streams.EMBED, "when": "next embed batch, after commit and before XACK"}
    elif name == "provider-outage":
        await state.redis.set(OUTAGE_KEY, "1", ex=30)
        detail = {"seconds": 30}
    elif name == "restart-redis":
        try:
            await state.redis.execute_command("SHUTDOWN", "SAVE")
        except Exception as error:  # the server closes the connection while shutting down
            detail = {"note": type(error).__name__}
    elif name == "poison-file":
        data = POISON.read_bytes()
        kind, sha = validate_upload(POISON.name, "application/pdf", data, state.settings.max_upload_bytes)
        from api.auth import known_groups, persona_user
        alex, taylor = persona_user("alex"), persona_user("taylor")
        assert alex is not None and taylor is not None, "the alex and taylor personas are required for this drill"
        meta = service.DocumentMeta("Scanned Policy (drill)", "Operational Workflow", "Operations", "internal",
                                    ("all-staff",))
        async with state.pool.connection() as conn, conn.transaction():
            ref = await service.create_document(conn, state.blobs, alex, meta, POISON.name, kind, sha, data,
                                                known_groups())
            await service.approve(conn, taylor, ref.version_id, "drill")
        detail = {"version_id": ref.version_id}
    elif name == "retention-now":
        detail = await recovery.purge_retention(state.pool, state.settings)
    else:
        raise LookupError(name)
    async with state.pool.connection() as conn:
        await events.emit(conn, f"drill.{name}", detail.get("version_id"), detail)
        await audit.record(conn, actor.user_id, "drill.run", name, detail)
    return {"drill": name, **detail}


async def kill_switch(consumer, message_id: str) -> None:
    """Consumer.before_ack hook: the first consumer on the targeted stream dies before acknowledging."""
    redis = consumer.ctx.redis
    if consumer.stream != await redis.get(KILL_KEY):
        return
    if await redis.getdel(KILL_KEY) is None:
        return
    async with consumer.ctx.pool.connection() as conn:
        await events.emit(conn, "worker.killed", None, {"consumer": consumer.ctx.consumer_name,
                                                        "stream": consumer.stream, "message_id": message_id})
    raise KilledByDrill(consumer.ctx.consumer_name)
