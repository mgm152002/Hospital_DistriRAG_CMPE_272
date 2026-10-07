"""Sign-in. Header mode (demo) maps X-User-Id to a persona from config/personas.yaml; OIDC mode reads a signed
token's groups. The rest of the code only sees common.models.User."""
import asyncio
from functools import lru_cache
from typing import Any

import yaml
from fastapi import Depends, Header, Request

from api.deps import AppState, get_state
from api.errors import ApiError
from common.models import User

PERSONAS_FILE = "config/personas.yaml"
ROLE_GROUPS = ("doc-admins", "compliance", "operators")


@lru_cache(maxsize=1)
def personas() -> dict[str, Any]:
    with open(PERSONAS_FILE, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def known_groups() -> set[str]:
    return set(personas()["known_groups"])


def persona_user(user_id: str) -> User | None:
    p = personas()["personas"].get(user_id)
    if p is None:
        return None
    groups = frozenset(p["groups"])
    return User(user_id=user_id, groups=groups, display_name=p["name"],
                roles=tuple(g for g in ROLE_GROUPS if g in groups))


def _oidc_user(token: str, state: AppState) -> User:
    import jwt
    from jwt import PyJWKClient
    s = state.settings
    try:
        key = PyJWKClient(f"{s.oidc_issuer}/protocol/openid-connect/certs").get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=["RS256"], issuer=s.oidc_issuer, options={"verify_aud": False})
    except Exception as error:
        raise ApiError(401, "invalid_token", f"Invalid token: {error}") from error
    groups = frozenset(g.strip("/").split("/")[-1] for g in claims.get("groups", []) if g.strip("/"))
    return User(user_id=claims.get("preferred_username") or claims["sub"], groups=groups,
                display_name=claims.get("name", ""), roles=tuple(g for g in ROLE_GROUPS if g in groups))


async def current_user(request: Request, state: AppState = Depends(get_state), x_user_id: str = Header(""),
                       authorization: str = Header("")) -> User:
    if state.settings.auth_mode == "local":
        from api.local_auth import COOKIE, session_user, validate_origin
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            validate_origin(request)
        return await session_user(state, request.cookies.get(COOKIE, ""))
    if state.settings.auth_mode == "header":
        user = persona_user(x_user_id.strip())
        if user is None:
            raise ApiError(401, "unauthenticated", "Sign in as one of the demo personas.")
        return user
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise ApiError(401, "unauthenticated", "Missing bearer token.")
    return await asyncio.to_thread(_oidc_user, token, state)


def require_group(*groups: str):
    def check(user: User = Depends(current_user)) -> User:
        if not user.groups & set(groups):
            raise ApiError(403, "forbidden", f"This needs one of: {', '.join(groups)}.")
        return user
    return check
