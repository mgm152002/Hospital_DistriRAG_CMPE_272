from tests.integration.api_client import as_user, build_state, client
from tests.integration.factories import create_version, make_ctx, run_pipeline


async def test_analytics_reports_real_counts_and_enforces_roles(pool, tmp_path):
    ctx = make_ctx(pool, tmp_path)
    _, v1 = await create_version(ctx, b"# Published\nA current policy passage.")
    await run_pipeline(ctx, v1)
    await create_version(ctx, b"# Draft\nA secret draft passage.", status="PENDING_APPROVAL")
    async with client(build_state(pool, None, tmp_path)) as api:
        result = await api.get("/api/admin/analytics", headers=as_user("alex"))
        assert result.status_code == 200
        counts = result.json()["counts"]
        assert counts["documents"] == 2 and counts["published"] == 1 and counts["pending_approval"] == 1
        assert len(result.json()["usage"]) == 14
        assert "secret draft passage" not in result.text
        assert (await api.get("/api/admin/analytics", headers=as_user("sam"))).status_code == 403


async def test_version_comparison_includes_pending_version_and_its_changes(pool, tmp_path):
    ctx = make_ctx(pool, tmp_path)
    did, v1 = await create_version(ctx, b"# Visitor Policy\nHours are 09:00 to 17:00.")
    await run_pipeline(ctx, v1)
    _, v2 = await create_version(
        ctx,
        b"# Visitor Policy\nHours are 10:00 to 18:00.",
        document_id=did,
        version_number=2,
        status="PENDING_APPROVAL",
    )
    async with client(build_state(pool, None, tmp_path)) as api:
        response = await api.get(
            f"/api/admin/documents/{did}/compare",
            headers=as_user("taylor"),
            params={"from_version": v1, "to_version": v2},
        )
        assert response.status_code == 200
        lines = response.json()["lines"]
        assert any(line["kind"] == "removed" and "09:00" in line["text"] for line in lines)
        assert any(line["kind"] == "added" and "18:00" in line["text"] for line in lines)
