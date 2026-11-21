import os

import pytest
import pytest_asyncio

from common.db import create_pool
from common.migrate import migrate

DATABASE_URL = os.environ.get("DATABASE_URL", "")
TABLES = (
    "auth_sessions",
    "auth_attempts",
    "user_accounts",
    "audit_log",
    "ops_events",
    "answer_cache",
    "messages",
    "conversations",
    "dead_letters",
    "idempotency_keys",
    "embed_batches",
    "outbox",
    "document_embeddings",
    "document_chunks",
    "document_versions",
    "document_acl",
    "documents",
)


def pytest_collection_modifyitems(items):
    for item in items:
        item.add_marker(pytest.mark.integration)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def migrated():
    import psycopg

    async with await psycopg.AsyncConnection.connect(DATABASE_URL, autocommit=True) as conn:
        await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    await migrate(DATABASE_URL)
    return DATABASE_URL


@pytest_asyncio.fixture
async def pool(migrated):
    p = await create_pool(migrated, max_size=8)
    async with p.connection() as conn:
        await conn.execute(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE")
    yield p
    await p.close()
