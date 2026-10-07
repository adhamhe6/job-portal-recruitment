"""Alembic: the migrated schema matches the models, and the migration chain works from an empty database, down and up again."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import asyncpg
import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.db import models  # noqa: F401  (registers every model on the metadata)
from app.db.database import Base, get_engine

pytestmark = pytest.mark.integration

BACKEND = Path(__file__).resolve().parents[2]


def script_directory() -> ScriptDirectory:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    return ScriptDirectory.from_config(cfg)


def test_there_is_exactly_one_head_and_a_linear_history() -> None:
    scripts = script_directory()
    assert len(scripts.get_heads()) == 1
    revisions = list(scripts.walk_revisions())
    assert revisions and all(len(r.down_revision or ()) <= 1 if isinstance(r.down_revision, tuple) else True for r in revisions)
    assert revisions[-1].down_revision is None, "the chain starts at an initial revision"
    assert scripts.get_current_head() == revisions[0].revision


async def test_the_migrated_database_has_no_drift_from_the_models(migrated_db: None) -> None:
    def diff(sync_conn: object) -> list[object]:
        ctx = MigrationContext.configure(sync_conn, opts={"compare_type": True, "compare_server_default": False})  # type: ignore[arg-type]
        return compare_metadata(ctx, Base.metadata)

    async with get_engine().connect() as conn:
        drift = await conn.run_sync(diff)
    assert drift == [], f"models and migrations disagree: {drift}"


async def test_the_database_is_at_the_head_revision(migrated_db: None) -> None:
    async with get_engine().connect() as conn:
        current = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalars().all()
    assert current == [script_directory().get_current_head()]


async def test_every_model_table_exists_and_nothing_else_does(migrated_db: None) -> None:
    async with get_engine().connect() as conn:
        tables = {r[0] for r in (await conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))).all()}
    assert tables == {t.name for t in Base.metadata.sorted_tables} | {"alembic_version"}


def alembic(url: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "DATABASE_URL": url, "ENVIRONMENT": "test"}
    return subprocess.run(  # noqa: S603
        [sys.executable, "-m", "alembic", "-c", str(BACKEND / "alembic.ini"), *args], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=180, check=False,
    )


async def test_a_scratch_database_can_be_built_checked_torn_down_and_rebuilt(migrated_db: None) -> None:
    base = make_url(os.environ["DATABASE_URL"])
    scratch = f"{base.database}_scratch_{uuid.uuid4().hex[:8]}"
    admin_dsn = base.set(drivername="postgresql", database="postgres").render_as_string(hide_password=False)
    scratch_url = base.set(database=scratch).render_as_string(hide_password=False)
    admin = await asyncpg.connect(admin_dsn)
    try:
        await admin.execute(f'CREATE DATABASE "{scratch}"')
        up = alembic(scratch_url, "upgrade", "head")
        assert up.returncode == 0, up.stderr[-2000:]
        check = alembic(scratch_url, "check")
        assert check.returncode == 0 and "No new upgrade operations detected" in (check.stdout + check.stderr), check.stdout + check.stderr
        heads = alembic(scratch_url, "current")
        assert script_directory().get_current_head() in (heads.stdout + heads.stderr)
        conn = await asyncpg.connect(base.set(drivername="postgresql", database=scratch).render_as_string(hide_password=False))
        try:
            n_tables = await conn.fetchval("SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")
            ext = {r["extname"] for r in await conn.fetch("SELECT extname FROM pg_extension")}
            assert n_tables == len(Base.metadata.sorted_tables) + 1 and {"vector", "pg_trgm", "btree_gist"} <= ext
        finally:
            await conn.close()
        down = alembic(scratch_url, "downgrade", "base")
        assert down.returncode == 0, down.stderr[-2000:]
        conn = await asyncpg.connect(base.set(drivername="postgresql", database=scratch).render_as_string(hide_password=False))
        try:
            left = {r["tablename"] for r in await conn.fetch("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")}
            assert left <= {"alembic_version"}, left
        finally:
            await conn.close()
        again = alembic(scratch_url, "upgrade", "head")
        assert again.returncode == 0, again.stderr[-2000:]
    finally:
        await admin.execute(f'DROP DATABASE IF EXISTS "{scratch}" WITH (FORCE)')
        await admin.close()
