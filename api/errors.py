"""One JSON error shape everywhere: {"error_code": ..., "detail": ...}. Outages become 503, never stack traces."""
import logging

import psycopg
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from psycopg_pool import PoolTimeout
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from documents.service import Conflict, Forbidden, Invalid, NotFound
from documents.validation import UploadError

log = logging.getLogger("distrirag.api")


class ApiError(Exception):
    def __init__(self, status: int, code: str, detail: str, headers: dict[str, str] | None = None) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail
        self.headers = headers


def error(status: int, code: str, detail: str, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse({"error_code": code, "detail": detail}, status_code=status, headers=headers)


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api(_: Request, e: ApiError):
        return error(e.status, e.code, e.detail, e.headers)

    @app.exception_handler(UploadError)
    async def _upload(_: Request, e: UploadError):
        return error(e.status, e.code, e.detail)

    @app.exception_handler(Forbidden)
    async def _forbidden(_: Request, e: Forbidden):
        return error(403, e.code, str(e))

    @app.exception_handler(Conflict)
    async def _conflict(_: Request, e: Conflict):
        return error(409, e.code, str(e))

    @app.exception_handler(NotFound)
    async def _missing(_: Request, e: NotFound):
        return error(404, "not_found", "Not found.")

    @app.exception_handler(Invalid)
    async def _invalid(_: Request, e: Invalid):
        return error(422, e.code, str(e))

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, e: RequestValidationError):
        first = e.errors()[0] if e.errors() else {}
        where = ".".join(str(p) for p in first.get("loc", []))
        return error(422, "invalid_request", f"{where}: {first.get('msg', 'invalid')}")

    @app.exception_handler(psycopg.OperationalError)
    @app.exception_handler(PoolTimeout)
    async def _db(_: Request, e: Exception):
        log.warning("database unavailable: %r", e)
        return error(503, "db_unavailable", "The database is unavailable. Try again shortly.", {"Retry-After": "5"})

    @app.exception_handler(RedisConnectionError)
    @app.exception_handler(RedisTimeoutError)
    async def _redis(_: Request, e: Exception):
        log.warning("redis unavailable: %r", e)
        return error(503, "queue_unavailable", "The work queue is unavailable. Try again shortly.",
                     {"Retry-After": "5"})
