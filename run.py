"""Process runner: `python -m run {api|relay|worker|recovery|all}`.

`all` runs every role as asyncio tasks in one process (weak hardware: one Python process, one connection pool).
In split mode each role is its own container and the kill drill really exits the worker process."""
import asyncio
import contextlib
import logging
import os
import socket
import sys

from common.logging import configure
from pipeline import drills, recovery, relay, streams
from pipeline.consumer import Consumer, Ctx
from pipeline.stages import delete, embed, extract, finalize

log = logging.getLogger("distrirag.run")


def _handlers():
    return {
        streams.EXTRACT: {"version.approved": extract.handle_approved},
        streams.EMBED: {"batch.ready": embed.handle_batch},
        streams.FINALIZE: {"version.embedded": finalize.handle_embedded},
        streams.DELETE: {"document.delete": delete.handle_delete},
    }


def _ctx(state, name: str) -> Ctx:
    return Ctx(pool=state.pool, redis=state.redis, blobs=state.blobs, embedder=state.embedder,
               settings=state.settings, consumer_name=name)


async def supervise_consumer(state, stream: str, slot: int, stop: asyncio.Event, exit_on_kill: bool) -> None:
    """Run one consumer; if the kill drill fires, exit (split mode) or restart under a new name (all mode)."""
    s = state.settings
    generation = 0
    while not stop.is_set():
        name = f"{socket.gethostname()}-{os.getpid()}-{stream.split('.')[-1]}-{slot}" + (
            f"-r{generation}" if generation else "")
        consumer = Consumer(_ctx(state, name), stream, streams.GROUPS[stream], _handlers()[stream],
                            on_permanent=extract.on_permanent,
                            reclaimer=recovery.make_reclaimer(s.reclaim_base_idle_ms, s.max_deliveries),
                            before_ack=drills.kill_switch)
        try:
            await consumer.run(stop, block_ms=1000)
        except drills.KilledByDrill:
            log.warning("consumer %s killed by drill", name)
            if exit_on_kill:
                os._exit(137)
            generation += 1
            await asyncio.sleep(1)


async def start_background(state, stop: asyncio.Event, embed_consumers: int = 2, exit_on_kill: bool = False,
                           roles: tuple[str, ...] = ("relay", "worker", "recovery")) -> list[asyncio.Task]:
    tasks: list[asyncio.Task] = []
    await streams.ensure_groups(state.redis)
    if "relay" in roles:
        tasks.append(asyncio.create_task(relay.run(state.pool, state.redis, stop), name="relay"))
    if "worker" in roles:
        for stream in (streams.EXTRACT, streams.FINALIZE, streams.DELETE):
            tasks.append(asyncio.create_task(supervise_consumer(state, stream, 1, stop, exit_on_kill)))
        for slot in range(1, embed_consumers + 1):
            tasks.append(asyncio.create_task(supervise_consumer(state, streams.EMBED, slot, stop, exit_on_kill)))
    if "recovery" in roles:
        tasks.append(asyncio.create_task(recovery.run(_ctx(state, f"{socket.gethostname()}-recovery"), stop)))
    return tasks


async def _gauges(state, stop: asyncio.Event) -> None:
    from common.metrics import refresh_gauges
    while not stop.is_set():
        with contextlib.suppress(Exception):
            await refresh_gauges(state)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=15)


async def main(role: str) -> None:
    import uvicorn

    from api.app import build_state, create_app
    configure(role)
    state = await build_state()
    stop = asyncio.Event()
    tasks: list[asyncio.Task] = []
    s = state.settings
    if role in ("all", "api"):
        tasks.append(asyncio.create_task(_gauges(state, stop)))
        roles = ("relay", "worker", "recovery") if role == "all" else ()
        tasks += await start_background(state, stop, embed_consumers=max(2, s.worker_concurrency), roles=roles)
        server = uvicorn.Server(uvicorn.Config(create_app(state=state), host="0.0.0.0",
                                               port=int(os.environ.get("PORT", "8000")), log_config=None,
                                               proxy_headers=True))
        await server.serve()
    else:
        import signal
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)
        tasks += await start_background(state, stop, embed_consumers=max(1, s.worker_concurrency), exit_on_kill=True,
                                        roles=(role,))
        await stop.wait()
    stop.set()
    await asyncio.gather(*tasks, return_exceptions=True)
    await state.pool.close()


if __name__ == "__main__":
    selected = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("ROLE", "all")
    if selected not in ("api", "relay", "worker", "recovery", "all"):
        sys.exit("usage: python -m run {api|relay|worker|recovery|all}")
    asyncio.run(main(selected))
