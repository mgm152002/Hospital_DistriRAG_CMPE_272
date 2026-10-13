"""Redis Streams consumer: read one message, run its handler (which commits its own DB transaction),
and only then XACK (RL-4). Permanent errors are recorded and acked; anything else stays pending for retry."""
import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

log = logging.getLogger("distrirag.consumer")


class PermanentError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class TransientError(Exception):
    pass


@dataclass
class Ctx:
    pool: Any
    redis: Any
    blobs: Any
    embedder: Any
    settings: Any
    consumer_name: str


Handler = Callable[[Ctx, dict], Awaitable[None]]
OnPermanent = Callable[[Ctx, dict, PermanentError], Awaitable[None]]
Reclaimer = Callable[["Consumer"], Awaitable[list[tuple[str, dict]]]]


class Consumer:
    def __init__(self, ctx: Ctx, stream: str, group: str, handlers: dict[str, Handler],
                 on_permanent: OnPermanent | None = None, reclaimer: Reclaimer | None = None,
                 before_ack: Callable[["Consumer", str], Awaitable[None]] | None = None) -> None:
        self.ctx = ctx
        self.stream = stream
        self.group = group
        self.handlers = handlers
        self.on_permanent = on_permanent
        self.reclaimer = reclaimer
        self.before_ack = before_ack

    async def handle(self, message_id: str, fields: dict) -> str:
        handler = self.handlers.get(fields.get("type", ""))
        if handler is None:
            log.warning("dropping unknown event %s on %s", fields.get("type"), self.stream)
            await self.ctx.redis.xack(self.stream, self.group, message_id)
            return "dropped"
        from common.metrics import MESSAGES, STAGE_SECONDS
        payload = json.loads(fields.get("payload") or "{}")
        started = time.perf_counter()
        try:
            await handler(self.ctx, payload)
        except PermanentError as error:
            if self.on_permanent is not None:
                await self.on_permanent(self.ctx, payload, error)
            await self.ctx.redis.xack(self.stream, self.group, message_id)
            MESSAGES.labels(self.stream, "failed").inc()
            return "failed"
        except Exception as error:
            log.warning("transient failure on %s %s: %r (left pending)", self.stream, message_id, error)
            MESSAGES.labels(self.stream, "retry").inc()
            return "retry"
        finally:
            STAGE_SECONDS.labels(self.stream).observe(time.perf_counter() - started)
        if self.before_ack is not None:
            await self.before_ack(self, message_id)
        await self.ctx.redis.xack(self.stream, self.group, message_id)
        MESSAGES.labels(self.stream, "ok").inc()
        return "ok"

    async def step(self, block_ms: int = 5000) -> bool:
        """Handle at most one due reclaim or one new message. Returns True if something was handled."""
        if self.reclaimer is not None:
            for message_id, fields in await self.reclaimer(self):
                await self.handle(message_id, fields)
                return True
        response = await self.ctx.redis.xreadgroup(self.group, self.ctx.consumer_name, {self.stream: ">"},
                                                   count=1, block=block_ms)
        for _, messages in response or []:
            for message_id, fields in messages:
                await self.handle(message_id, fields)
                return True
        return False

    async def run(self, stop: asyncio.Event, block_ms: int = 2000) -> None:
        backoff = 0.5
        while not stop.is_set():
            try:
                await self.step(block_ms=block_ms)
                backoff = 0.5
            except Exception as error:  # Redis unavailable: wait and reconnect
                log.warning("consumer %s error: %r", self.stream, error)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 10.0)
