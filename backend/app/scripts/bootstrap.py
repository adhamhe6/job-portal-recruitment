"""One-shot deployment bootstrap (run after ``alembic upgrade head``): skills taxonomy, first admin, optional demo data.

Idempotent — safe to run on every container start.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.security import Role, hash_password
from app.db.database import dispose_engine, get_sessionmaker
from app.db.models import User
from app.services.skills import seed_ontology

logger = logging.getLogger("bootstrap")


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    async with get_sessionmaker()() as session:
        created = await seed_ontology(session)
        logger.info("skill taxonomy ready", extra={"new_skills": created})
        email = settings.first_admin_email.lower()
        exists = await session.scalar(select(User.id).where(func.lower(User.email) == email))
        if not exists:
            session.add(
                User(
                    email=email,
                    password_hash=hash_password(settings.first_admin_password.get_secret_value()),
                    first_name="Platform",
                    last_name="Admin",
                    role=Role.ADMIN,
                )
            )
            await session.commit()
            logger.info("first admin created", extra={"email_domain": email.split("@")[-1]})
    if settings.seed_demo_data:
        from app.scripts.seed import run

        done = await run(reset=False)
        logger.info("demo data %s", "created" if done else "already present")
    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
