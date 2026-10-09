"""Postgres-backed accounts and revocable cookie sessions for local authentication."""

import asyncio
import hashlib
import secrets
from urllib.parse import urlparse

from api.errors import ApiError
from common.models import User
from common.passwords import hash_password

COOKIE = "distrirag_session"
ROLE_GROUPS = ("doc-admins", "compliance", "operators")


def validate_origin(request) -> None:
    origin = request.headers.get("origin")
    if origin:
        parsed = urlparse(origin)
        if (parsed.scheme, parsed.netloc) != (request.url.scheme, request.headers.get("host")):
            raise ApiError(403, "origin_blocked", "The request must come from this application.")


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def seed_demo_accounts(state) -> None:
    if not (state.settings.auth_mode == "local" and state.settings.demo_accounts_enabled):
        return
    if not state.settings.synthetic_data_only:
        raise RuntimeError("Demo accounts require synthetic data")
    from api.auth import personas

    async with state.pool.connection() as conn, conn.transaction():
        for uid, persona in personas()["personas"].items():
            exists = await (await conn.execute("SELECT 1 FROM user_accounts WHERE user_id=%s", (uid,))).fetchone()
            if exists:
                continue
            password_hash = await asyncio.to_thread(
                hash_password, state.settings.demo_account_password.get_secret_value()
            )
            await conn.execute(
                "INSERT INTO user_accounts(user_id,email,display_name,role_name,groups,password_hash,is_demo) "
                "VALUES (%s,%s,%s,%s,%s,%s,true) ON CONFLICT DO NOTHING",
                (uid, f"{uid}@distrirag.demo", persona["name"], persona["role"], persona["groups"], password_hash),
            )


async def session_user(state, token: str) -> User:
    if not token or len(token) > 128:
        raise ApiError(401, "unauthenticated", "Sign in to continue.")
    async with state.pool.connection() as conn:
        row = await (
            await conn.execute(
                "SELECT u.user_id,u.display_name,u.groups FROM auth_sessions s JOIN user_accounts u USING(user_id) "
                "WHERE s.token_hash=%s AND s.expires_at>now() AND u.disabled_at IS NULL "
                "AND (NOT u.is_demo OR %s)",
                (token_hash(token), state.settings.demo_accounts_enabled),
            )
        ).fetchone()
    if row is None:
        raise ApiError(401, "session_expired", "Your session has expired. Sign in again.")
    groups = frozenset(row[2])
    return User(row[0], groups, row[1], tuple(group for group in ROLE_GROUPS if group in groups))


async def create_session(conn, state, uid: str, previous: str = "") -> str:
    token = secrets.token_urlsafe(48)
    if previous:
        await conn.execute("DELETE FROM auth_sessions WHERE token_hash=%s", (token_hash(previous),))
    await conn.execute(
        "INSERT INTO auth_sessions(token_hash,user_id,expires_at) VALUES (%s,%s,now()+make_interval(hours=>%s))",
        (token_hash(token), uid, state.settings.auth_session_hours),
    )
    return token


def set_cookie(response, state, token: str) -> None:
    response.set_cookie(
        COOKIE,
        token,
        httponly=True,
        secure=state.settings.auth_cookie_secure,
        samesite="lax",
        max_age=state.settings.auth_session_hours * 3600,
        path="/",
    )


async def check_attempts(conn, email: str, address: str) -> tuple[str, str]:
    identifiers = (token_hash("email:" + email), token_hash("ip:" + address))
    rows = await (
        await conn.execute(
            "SELECT identifier_hash,count(*) FROM auth_attempts WHERE identifier_hash=ANY(%s) "
            "AND created_at>now()-interval '15 minutes' GROUP BY identifier_hash",
            (list(identifiers),),
        )
    ).fetchall()
    limits = {identifiers[0]: 8, identifiers[1]: 40}
    if any(count >= limits[identifier] for identifier, count in rows):
        raise ApiError(
            429, "login_rate_limited", "Too many sign-in attempts. Try again in 15 minutes.", {"Retry-After": "900"}
        )
    return identifiers


async def failed_attempt(conn, identifiers: tuple[str, str]) -> None:
    for identifier in identifiers:
        await conn.execute("INSERT INTO auth_attempts(identifier_hash) VALUES (%s)", (identifier,))


async def account_profile(state, user: User) -> dict:
    async with state.pool.connection() as conn:
        row = await (
            await conn.execute("SELECT email,role_name,is_demo,created_at FROM user_accounts WHERE user_id=%s",
                               (user.user_id,))
        ).fetchone()
    if not row:
        return {}
    return {"email": row[0], "role": row[1], "is_demo": row[2], "member_since": row[3].isoformat()}
