"""Tiny migration runner: applies deploy/sql/*.sql in name order, once each, under an advisory lock."""
import asyncio
import pathlib
import sys

import psycopg

SQL_DIR = pathlib.Path(__file__).resolve().parents[1] / "deploy" / "sql"
LOCK_ID = 4242


async def migrate(url: str, sql_dir: pathlib.Path = SQL_DIR) -> list[str]:
    applied: list[str] = []
    async with await psycopg.AsyncConnection.connect(url, autocommit=True) as conn:
        await conn.execute("SELECT pg_advisory_lock(%s)", (LOCK_ID,))
        try:
            await conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations "
                               "(name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
            done = {row[0] for row in await (await conn.execute("SELECT name FROM schema_migrations")).fetchall()}
            for path in sorted(sql_dir.glob("*.sql")):
                if path.name in done:
                    continue
                async with conn.transaction():
                    await conn.execute(path.read_text())  # type: ignore[arg-type]
                    await conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (path.name,))
                applied.append(path.name)
        finally:
            await conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_ID,))
    return applied


if __name__ == "__main__":
    from common.config import get_settings
    print(asyncio.run(migrate(sys.argv[1] if len(sys.argv) > 1 else get_settings().database_url)))
