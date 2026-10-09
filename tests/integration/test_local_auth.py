import pytest

from api.local_auth import seed_demo_accounts
from tests.integration.api_client import build_state, client
from tests.integration.factories import scalar


@pytest.fixture
async def local(pool, tmp_path):
    state = build_state(pool, None, tmp_path, auth_mode="local", demo_accounts_enabled=True)
    await seed_demo_accounts(state)
    async with client(state) as api:
        yield api, state


async def test_registration_creates_only_general_staff_and_cookie_session(local, pool):
    api, _ = local
    response = await api.post(
        "/api/auth/register",
        json={
            "name": "New Staff",
            "email": "staff@example.test",
            "password": "strong test password",
            "groups": ["compliance"],
        },
    )
    assert response.status_code == 201
    assert "HttpOnly" in response.headers["set-cookie"]
    me = (await api.get("/api/me")).json()
    assert me["groups"] == ["all-staff"]
    assert me["hospital"]["name"] and me["member_since"]
    assert (await api.get("/api/admin/analytics")).status_code == 403
    stored = await scalar(pool, "SELECT password_hash FROM user_accounts WHERE email='staff@example.test'")
    assert "strong test password" not in stored


async def test_login_logout_and_header_impersonation_protection(local):
    api, _ = local
    assert (await api.get("/api/me", headers={"X-User-Id": "taylor"})).status_code == 401
    body = {"email": "alex@distrirag.demo", "password": "DemoAccess!2026"}
    assert (await api.post("/api/auth/login", json=body)).status_code == 200
    assert (await api.get("/api/me")).json()["user_id"] == "alex"
    assert (await api.get("/api/me", headers={"X-User-Id": "taylor"})).json()["user_id"] == "alex"
    assert (await api.post("/api/auth/logout")).status_code == 204
    assert (await api.get("/api/me")).status_code == 401


async def test_duplicate_registration_and_bad_credentials(local):
    api, _ = local
    assert (
        await api.post(
            "/api/auth/register",
            json={"name": "Duplicate", "email": "ALEX@distrirag.demo", "password": "strong test password"},
        )
    ).status_code == 409
    response = await api.post(
        "/api/auth/login", json={"email": "alex@distrirag.demo", "password": "wrong-secret-value"}
    )
    assert response.status_code == 401 and "wrong-secret-value" not in response.text


async def test_expired_session_is_refused(local, pool):
    api, _ = local
    await api.post("/api/auth/login", json={"email": "sam@distrirag.demo", "password": "DemoAccess!2026"})
    async with pool.connection() as conn:
        await conn.execute("UPDATE auth_sessions SET expires_at=now()-interval '1 second'")
    assert (await api.get("/api/me")).status_code == 401


async def test_login_attempts_are_rate_limited(local):
    api, _ = local
    for _ in range(8):
        result = await api.post("/api/auth/login", json={"email": "sam@distrirag.demo", "password": "wrong"})
        assert result.status_code == 401
    assert (
        await api.post("/api/auth/login", json={"email": "sam@distrirag.demo", "password": "wrong"})
    ).status_code == 429


async def test_disabling_demo_accounts_invalidates_existing_demo_sessions(local):
    api, state = local
    await api.post("/api/auth/demo/alex")
    assert (await api.get("/api/me")).status_code == 200
    state.settings = state.settings.model_copy(update={"demo_accounts_enabled": False})
    assert (await api.get("/api/me")).status_code == 401
    assert (await api.post("/api/auth/demo/alex")).status_code == 404


async def test_cookie_authenticated_mutations_reject_other_origins(local):
    api, _ = local
    await api.post("/api/auth/demo/alex")
    path = "/api/documents/00000000-0000-4000-8000-000000000001/retire"
    for origin in ("http://other.test", "http://test:8081", "https://test", "null"):
        result = await api.post(path, headers={"Origin": origin})
        assert result.status_code == 403 and result.json()["error_code"] == "origin_blocked"
    assert (await api.post(path, headers={"Origin": "http://test"})).status_code == 404
