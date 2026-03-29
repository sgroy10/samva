from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from .config import settings
import os


class Base(DeclarativeBase):
    pass


def get_engine():
    url = settings.database_url
    # Convert postgresql:// to postgresql+asyncpg:// if needed
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)

    if "postgresql" in url:
        return create_async_engine(
            url,
            pool_size=20,
            max_overflow=10,
            echo=settings.debug,
        )
    else:
        # SQLite
        if "sqlite" in url and "aiosqlite" not in url:
            url = url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
        return create_async_engine(url, echo=settings.debug)


engine = get_engine()
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """Create all tables + run migrations for new columns."""
    os.makedirs("data/db", exist_ok=True)
    async with engine.begin() as conn:
        from . import models  # noqa
        await conn.run_sync(Base.metadata.create_all)

    # Run column migrations (safe to re-run — uses IF NOT EXISTS / catches errors)
    await _run_migrations()


async def _run_migrations():
    """Add new columns to existing tables. Idempotent."""
    migrations = [
        "ALTER TABLE agent_souls ADD COLUMN IF NOT EXISTS last_gold_brief_date DATE",
        "ALTER TABLE agent_souls ADD COLUMN IF NOT EXISTS network_permission BOOLEAN DEFAULT FALSE",
        "ALTER TABLE reminders ADD COLUMN IF NOT EXISTS is_urgent BOOLEAN DEFAULT FALSE",
        "ALTER TABLE reminders ADD COLUMN IF NOT EXISTS call_attempted BOOLEAN DEFAULT FALSE",
        "ALTER TABLE email_configs ADD COLUMN IF NOT EXISTS account_type VARCHAR(50) DEFAULT 'personal'",
        "ALTER TABLE email_configs ADD COLUMN IF NOT EXISTS is_primary BOOLEAN DEFAULT FALSE",
        "ALTER TABLE agent_souls ADD COLUMN IF NOT EXISTS voice_language VARCHAR(50) DEFAULT 'auto'",
    ]
    async with engine.begin() as conn:
        for sql in migrations:
            try:
                from sqlalchemy import text
                await conn.execute(text(sql))
            except Exception as e:
                # Column might already exist or table might not exist yet
                pass
