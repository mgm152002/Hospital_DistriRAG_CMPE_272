from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, Response

from api.auth import current_user, personas, require_group
from api.demo_questions import demo_enabled, groups_for, load_corpus
from api.deps import AppState, get_state
from common.models import User

router = APIRouter()


@router.get("/metrics", include_in_schema=False)
async def metrics_endpoint():
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.get("/healthz")
async def healthz():
    return {"ok": True}


@router.get("/readyz")
async def readyz(state: AppState = Depends(get_state)):
    checks = {}
    try:
        async with state.pool.connection() as conn:
            await conn.execute("SELECT 1")
        checks["postgres"] = True
    except Exception:
        checks["postgres"] = False
    try:
        checks["redis"] = bool(await state.redis.ping())
    except Exception:
        checks["redis"] = False
    return JSONResponse({"ready": all(checks.values()), **checks}, status_code=200 if all(checks.values()) else 503)


@router.get("/api/personas")
async def list_personas(state: AppState = Depends(get_state)):
    if state.settings.auth_mode != "header":
        return []
    return [{"user_id": uid, **p} for uid, p in personas()["personas"].items()]


@router.get("/api/demo/questions")
async def demo_questions(user: User = Depends(current_user), state: AppState = Depends(get_state)):
    """The corpus questions for the signed-in persona, for one-click testing in a demo. Empty outside demo setups."""
    if not demo_enabled(state.settings):
        return {"enabled": False, "groups": []}
    return {"enabled": True, "groups": groups_for(user.user_id, user.groups, load_corpus())}


@router.get("/api/me")
async def me(user: User = Depends(current_user), state: AppState = Depends(get_state)):
    from common.llm.runtime import resolve_llm
    p = personas()["personas"].get(user.user_id, {})
    info = (await resolve_llm(state)).info
    profile = {}
    if state.settings.auth_mode == "local":
        from api.local_auth import account_profile
        profile = await account_profile(state, user)
    return {"user_id": user.user_id, "name": user.display_name, "role": profile.get("role", p.get("role", "")),
            "groups": sorted(user.groups), "roles": list(user.roles), "samples": p.get("samples", []),
            "department": p.get("department"), "hospital": state.settings.hospital(),
            "profile": state.settings.deployment_profile, "llm_provider": info.name,
            "llm_external": info.external, "llm_model": info.model, **profile}


@router.get("/api/system/config")
async def system_config(user: User = Depends(require_group("compliance", "operators")),
                        state: AppState = Depends(get_state)):
    providers = {name: vars(info) for name, info in state.providers.items()}
    return {"settings": state.settings.public_view(), "providers": providers,
            "egress_blocked": list(state.guard.blocked[-20:]) if state.guard else []}
