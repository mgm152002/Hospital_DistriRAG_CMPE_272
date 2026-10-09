"""Public login/registration entrypoints and server-authenticated demo sessions."""

import asyncio
import re
import uuid

import psycopg
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, SecretStr

from api.auth import personas
from api.deps import AppState, get_state
from api.errors import ApiError
from api.local_auth import (
    COOKIE,
    check_attempts,
    create_session,
    failed_attempt,
    set_cookie,
    token_hash,
    validate_origin,
)
from common import audit
from common.passwords import hash_password, verify_password

router = APIRouter(prefix="/api/auth")
DUMMY_HASH = hash_password("authentication timing padding")


class LoginBody(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: SecretStr


class RegisterBody(LoginBody):
    name: str = Field(min_length=2, max_length=100)


def local_only(state: AppState, request: Request) -> None:
    if state.settings.auth_mode != "local":
        raise ApiError(400, "local_auth_disabled", "Local account sign-in is not enabled.")
    validate_origin(request)


def signed_in(state, token: str, uid: str, status: int = 200):
    response = JSONResponse({"user_id": uid}, status_code=status)
    set_cookie(response, state, token)
    return response


@router.get("/config")
async def config(state: AppState = Depends(get_state)):
    demo = state.settings.auth_mode == "local" and state.settings.demo_accounts_enabled
    return {
        "mode": state.settings.auth_mode,
        "registration_enabled": state.settings.registration_enabled,
        "hospital": state.settings.hospital(),
        "demo_accounts": [
            {"user_id": uid, "email": f"{uid}@distrirag.demo", **p} for uid, p in personas()["personas"].items()
        ]
        if demo
        else [],
    }


@router.post("/register", status_code=201)
async def register(body: RegisterBody, request: Request, state: AppState = Depends(get_state)):
    local_only(state, request)
    if not state.settings.registration_enabled:
        raise ApiError(403, "registration_disabled", "Registration is closed. Contact your administrator.")
    email = body.email.strip().lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) or not body.name.strip():
        raise ApiError(400, "invalid_account", "Enter your name and a valid email address.")
    address = request.client.host if request.client else "unknown"
    async with state.pool.connection() as conn:
        identifiers = await check_attempts(conn, "registration:" + address, "registration:" + address)
        await failed_attempt(conn, identifiers)
    try:
        encoded = await asyncio.to_thread(hash_password, body.password.get_secret_value())
    except ValueError as error:
        raise ApiError(400, "weak_password", str(error)) from error
    uid = str(uuid.uuid4())
    try:
        async with state.pool.connection() as conn, conn.transaction():
            await conn.execute(
                "INSERT INTO user_accounts(user_id,email,display_name,password_hash) VALUES (%s,%s,%s,%s)",
                (uid, email, body.name.strip(), encoded),
            )
            token = await create_session(conn, state, uid, request.cookies.get(COOKIE, ""))
            await audit.record(conn, uid, "auth.registered", uid)
    except psycopg.errors.UniqueViolation as error:
        raise ApiError(
            409, "email_registered", "An account with this email already exists. Sign in instead."
        ) from error
    return signed_in(state, token, uid, 201)


@router.post("/login")
async def login(body: LoginBody, request: Request, state: AppState = Depends(get_state)):
    local_only(state, request)
    email = body.email.strip().lower()
    async with state.pool.connection() as conn:
        identifiers = await check_attempts(conn, email, request.client.host if request.client else "unknown")
        row = await (
            await conn.execute(
                "SELECT user_id,password_hash,disabled_at,is_demo FROM user_accounts WHERE email=%s", (email,)
            )
        ).fetchone()
        valid = await asyncio.to_thread(
            verify_password, body.password.get_secret_value(), row[1] if row else DUMMY_HASH
        )
        if row is None or not valid or row[2] is not None or (row[3] and not state.settings.demo_accounts_enabled):
            await failed_attempt(conn, identifiers)
            raise ApiError(401, "invalid_credentials", "Email or password is incorrect.")
        async with conn.transaction():
            token = await create_session(conn, state, row[0], request.cookies.get(COOKIE, ""))
            await audit.record(conn, row[0], "auth.signin", row[0])
    return signed_in(state, token, row[0])


@router.post("/demo/{user_id}")
async def demo_login(user_id: str, request: Request, state: AppState = Depends(get_state)):
    local_only(state, request)
    if not state.settings.demo_accounts_enabled or user_id not in personas()["personas"]:
        raise ApiError(404, "demo_unavailable", "This demo account is not available.")
    async with state.pool.connection() as conn, conn.transaction():
        row = await (
            await conn.execute(
                "SELECT user_id FROM user_accounts WHERE user_id=%s AND is_demo=true AND disabled_at IS NULL",
                (user_id,),
            )
        ).fetchone()
        if not row:
            raise ApiError(404, "demo_unavailable", "This demo account is not available.")
        token = await create_session(conn, state, user_id, request.cookies.get(COOKIE, ""))
        await audit.record(conn, user_id, "auth.signin", user_id, {"demo": True})
    return signed_in(state, token, user_id)


@router.post("/logout", status_code=204)
async def logout(request: Request, state: AppState = Depends(get_state)):
    local_only(state, request)
    async with state.pool.connection() as conn:
        await conn.execute(
            "DELETE FROM auth_sessions WHERE token_hash=%s", (token_hash(request.cookies.get(COOKIE, "")),)
        )
    response = Response(status_code=204)
    response.delete_cookie(COOKIE, path="/", secure=state.settings.auth_cookie_secure, httponly=True, samesite="lax")
    return response
