from __future__ import annotations

import os
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

DATABASE_URL = os.getenv(
  "DATABASE_URL",
  "postgresql+asyncpg://postgres:postgres@localhost:5432/ev-sim-db",
)

engine = create_async_engine(DATABASE_URL, echo=False)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
  pass


async def get_session() -> AsyncGenerator[AsyncSession, None]:
  async with async_session_factory() as session:
    yield session


async def _run_migrations(conn) -> None:
  from sqlalchemy import text

  result = await conn.execute(
    text(
      "SELECT column_name FROM information_schema.columns "
      "WHERE table_name = 'sessions' AND column_name = 'ev_id'"
    )
  )
  if result.first() is None:
    await conn.execute(
      text(
        "ALTER TABLE sessions ADD COLUMN ev_id VARCHAR "
        "REFERENCES evs(id) ON DELETE SET NULL"
      )
    )
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_sessions_ev_id ON sessions (ev_id)"))


async def init_db() -> None:
  import app.db.models  # noqa: F401 — register ORM tables with Base.metadata

  async with engine.begin() as conn:
    await conn.run_sync(Base.metadata.create_all)
    await _run_migrations(conn)


async def close_db() -> None:
  await engine.dispose()
