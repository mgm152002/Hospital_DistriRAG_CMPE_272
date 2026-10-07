"""FastAPI application factory. `create_app(state=...)` is used by tests; without a state, the lifespan builds one
from the environment (validating compliance settings and migrating the database first)."""
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api import errors
from api.deps import AppState
from api.routes import documents, system
from common.static import cache_control, resolve_public_path

log = logging.getLogger("distrirag.api")


async def build_state() -> AppState:
    import redis.asyncio as aioredis

    from common.blob import make_blob_store
    from common.config import get_settings, validate_compliance
    from common.db import create_pool
    from common.egress import EgressGuard
    from common.embed import make_embedder
    from common.llm import load_providers, make_llm
    from common.migrate import migrate

    s = get_settings()
    providers = load_providers(s.providers_file)
    validate_compliance(s, providers)
    await migrate(s.database_url)
    guard = EgressGuard(s.allowed_hosts, s.egress_enforced)
    state = AppState(settings=s, pool=await create_pool(s.database_url, max_size=8),
                    redis=aioredis.from_url(s.redis_url, decode_responses=True), blobs=make_blob_store(s),
                    embedder=make_embedder(s), llm=make_llm(s.llm_provider, providers, guard, s.llm_max_concurrency),
                    providers=providers, guard=guard)
    from api.local_auth import seed_demo_accounts
    await seed_demo_accounts(state)
    return state


def create_app(state: AppState | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if state is None:
            app.state.distrirag = await build_state()
            yield
            await app.state.distrirag.pool.close()
            await app.state.distrirag.redis.aclose()
        else:
            yield

    app = FastAPI(title="DistriRAG API", version="0.2.0", lifespan=lifespan)
    if state is not None:
        app.state.distrirag = state
    errors.install(app)
    app.include_router(system.router)
    app.include_router(documents.router)
    for module in _optional_routers():
        app.include_router(module.router)
    _mount_frontend(app)
    return app


def _optional_routers():
    import importlib
    found = []
    for name in ("search", "chat", "compliance", "ops", "settings", "authentication", "admin"):
        try:
            found.append(importlib.import_module(f"api.routes.{name}"))
        except ModuleNotFoundError as error:
            if error.name != f"api.routes.{name}":
                raise
    return found


def _mount_frontend(app: FastAPI) -> None:
    dist = os.environ.get("STATIC_DIR", "web/dist")
    if not os.path.isdir(dist):
        return
    app.mount("/assets", StaticFiles(directory=os.path.join(dist, "assets")), name="assets")

    @app.middleware("http")
    async def cache_headers(request, call_next):
        response = await call_next(request)
        if not request.url.path.startswith(("/api", "/metrics", "/healthz", "/readyz")):
            response.headers.setdefault("Cache-Control", cache_control(request.url.path))
        return response

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        try:
            candidate = resolve_public_path(dist, path)
        except ValueError as error:
            raise HTTPException(404, "Not found") from error
        if path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(os.path.join(dist, "index.html"))
