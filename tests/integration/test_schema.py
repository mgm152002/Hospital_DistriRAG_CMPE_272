"""Covers: RL-1, CR-3, CR-4, FR-5, CP-5."""
import uuid

import psycopg
import pytest

from common.audit import record
from common.migrate import migrate


async def make_doc(conn, uploaded_by="alex", approved_by=None):
    did, vid = uuid.uuid4(), uuid.uuid4()
    await conn.execute(
        "INSERT INTO documents (document_id, title, category, department, classification, owner_id) "
        "VALUES (%s, 'T', 'Clinical Policy', 'Nursing', 'internal', 'alex')", (did,))
    await conn.execute(
        "INSERT INTO document_versions (version_id, document_id, version_number, status, object_key, "
        "content_type, content_sha256, uploaded_by, approved_by) "
        "VALUES (%s, %s, 1, 'PENDING_APPROVAL', 'k', 'text/plain', 'h', %s, %s)",
        (vid, did, uploaded_by, approved_by))
    return did, vid


async def test_migrate_is_idempotent(pool, migrated):
    assert await migrate(migrated) == []


async def test_self_approval_check_constraint(pool):
    async with pool.connection() as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            await make_doc(conn, uploaded_by="alex", approved_by="alex")


async def test_chunk_unique_per_version(pool):
    async with pool.connection() as conn:
        did, vid = await make_doc(conn)
        sql = ("INSERT INTO document_chunks (chunk_id, document_id, version_id, chunk_index, page_number, text) "
               "VALUES (%s, %s, %s, 0, 1, 'x')")
        await conn.execute(sql, (uuid.uuid4(), did, vid))
        with pytest.raises(psycopg.errors.UniqueViolation):
            await conn.execute(sql, (uuid.uuid4(), did, vid))


async def test_audit_log_is_append_only(pool):
    async with pool.connection() as conn:
        await record(conn, "alex", "document.uploaded", "doc-1", {"n": 1})
    async with pool.connection() as conn:
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            await conn.execute("UPDATE audit_log SET action = 'x'")
    async with pool.connection() as conn:
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            await conn.execute("DELETE FROM audit_log")
