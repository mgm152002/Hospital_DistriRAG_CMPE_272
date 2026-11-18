"""Fault-injection helpers: subprocess workers that can be SIGKILLed, in-process stacks, and waiters."""
import asyncio
import os
import signal
import subprocess
import sys

from pipeline import streams
from pipeline.outbox import enqueue
from tests.integration.factories import scalar


def start_worker(blob_root: str, name: str, **env: str) -> subprocess.Popen:
    environment = {**os.environ, "BLOB_ROOT": blob_root, "DEPLOYMENT_PROFILE": "lite", "RECLAIM_BASE_IDLE_MS": "1000",
                   "STUCK_AFTER_SECONDS": "3", "HOSTNAME": name, **env}
    return subprocess.Popen([sys.executable, "-m", "run", "worker"], env=environment,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def kill(process: subprocess.Popen) -> None:
    process.send_signal(signal.SIGKILL)
    process.wait(timeout=10)


async def wait_for(predicate, timeout: float = 30, every: float = 0.2) -> bool:
    for _ in range(int(timeout / every)):
        if await predicate():
            return True
        await asyncio.sleep(every)
    return False


async def status(pool, vid: str) -> str:
    return await scalar(pool, "SELECT status FROM document_versions WHERE version_id = %s", (vid,))


async def wait_status(pool, vid: str, wanted: str, timeout: float = 30) -> bool:
    async def check():
        return await status(pool, vid) == wanted
    return await wait_for(check, timeout)


async def approve(pool, vid: str) -> None:
    async with pool.connection() as conn:
        await conn.execute("UPDATE document_versions SET status = 'QUEUED' WHERE version_id = %s", (vid,))
        await enqueue(conn, streams.EXTRACT, "version.approved", f"extract:{vid}", {"version_id": vid})


async def assert_no_duplicates(pool, vid: str) -> int:
    total = await scalar(pool, "SELECT chunks_total FROM document_versions WHERE version_id = %s", (vid,))
    chunks = await scalar(pool, "SELECT count(*) FROM document_chunks WHERE version_id = %s", (vid,))
    vectors = await scalar(pool, "SELECT count(*) FROM document_embeddings e JOIN document_chunks c "
                                 "ON c.chunk_id = e.chunk_id WHERE c.version_id = %s", (vid,))
    distinct = await scalar(pool, "SELECT count(DISTINCT chunk_index) FROM document_chunks WHERE version_id = %s",
                            (vid,))
    assert total > 0 and chunks == total == vectors == distinct, (total, chunks, vectors, distinct)
    return total
