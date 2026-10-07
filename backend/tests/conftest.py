"""Test harness.

Integration and e2e tests run against a real PostgreSQL (migrated with Alembic from an empty database, so the
migrations themselves are under test) and a real Redis. Background tasks run inline (JOB_BACKEND=inline) so API
workflows are deterministic; the ARQ worker path is exercised separately (tests/integration/test_worker.py and the
Docker stack validation).

Configure with TEST_DATABASE_URL / TEST_REDIS_URL.
"""

from __future__ import annotations

import os
import tempfile

os.environ["ENVIRONMENT"] = "test"
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/talentlens_test"
)
os.environ["REDIS_URL"] = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/15")
os.environ["JOB_BACKEND"] = "inline"
os.environ["LOG_JSON"] = "false"
os.environ["LOG_LEVEL"] = "WARNING"
os.environ["STORAGE_DIR"] = tempfile.mkdtemp(prefix="tl-resumes-")
os.environ["DATABASE_POOL_SIZE"] = "5"
os.environ["LOGIN_RATE_LIMIT_ATTEMPTS"] = "1000"
os.environ["REGISTER_RATE_LIMIT_ATTEMPTS"] = "1000"
os.environ["UPLOAD_RATE_LIMIT_ATTEMPTS"] = "1000"
os.environ["EXPENSIVE_RATE_LIMIT_ATTEMPTS"] = "1000"
os.environ["SEARCH_RATE_LIMIT_ATTEMPTS"] = "100000"

from collections.abc import AsyncIterator  # noqa: E402

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.cache.redis_cache import get_cache, get_redis  # noqa: E402
from app.db.database import Base, get_engine, get_sessionmaker  # noqa: E402


def _run_migrations() -> None:
    from alembic.config import Config

    from alembic import command

    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
def migrated_db() -> None:
    """Apply migrations once per session (also proves downgrade/upgrade works from an empty database)."""
    import concurrent.futures

    # Alembic's env.py uses asyncio.run(), which cannot nest inside the test loop.
    with concurrent.futures.ThreadPoolExecutor(1) as pool:
        pool.submit(_run_migrations).result()


@pytest.fixture(scope="session")
async def seeded_ontology(migrated_db: None) -> None:
    from app.services.skills import seed_ontology

    async with get_sessionmaker()() as s:
        await seed_ontology(s)


@pytest.fixture
async def db(migrated_db: None, seeded_ontology: None) -> AsyncIterator[None]:
    """Clean database + Redis for every test that touches infrastructure."""
    keep = {"skills", "skill_aliases"}  # the built-in ontology is seeded once per session
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables if t.name not in keep)
    async with get_engine().begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
        await conn.execute(text("DELETE FROM skills WHERE NOT is_verified"))  # user-created skills from a previous test
    await get_redis().flushdb()
    get_cache()._down_until = 0.0  # reset circuit breaker between tests
    yield


@pytest.fixture
async def session(db: None):  # type: ignore[no-untyped-def]
    async with get_sessionmaker()() as s:
        yield s


@pytest.fixture
async def client(db: None) -> AsyncIterator[AsyncClient]:
    from app.main import app
    from app.workers.dispatch import InlineDispatcher

    app.state.dispatcher = InlineDispatcher()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
