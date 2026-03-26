"""Database configuration and session management for FinAI Service."""

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import Column, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from typing import AsyncGenerator

from .config import settings


engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """Base class for all database models."""
    pass


class AuditMixin:
    """Mixin providing standard audit columns for all models."""
    
    created_at = Column(DateTime, nullable=False, default=func.now())
    created_by = Column(UUID(as_uuid=True), nullable=True)
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())
    updated_by = Column(UUID(as_uuid=True), nullable=True)
    deleted_at = Column(DateTime, nullable=True)
    deleted_by = Column(UUID(as_uuid=True), nullable=True)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Get database session dependency."""
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()


async def create_tables():
    """Create all database tables.

    Important: SQLAlchemy registers tables on model import. The new service previously
    created tables without importing legacy modules, which caused legacy tables to
    be missing.

    We import both new and legacy model modules here so *all* tables are registered
    on the shared Base metadata, then run create_all.
    """
    # Import new + legacy models to register all tables
    try:
        import app.models  # noqa: F401
        # Legacy model modules (kept for backward-compatible /v1 APIs)
        import app.models.analytics_models  # noqa: F401
        import app.models.auth_models  # noqa: F401
        import app.models.chat_models  # noqa: F401
        import app.models.crm_models  # noqa: F401
        import app.models.session_models  # noqa: F401
        import app.models.voicefin_models  # noqa: F401
    except Exception as e:
        # Don't crash startup if optional legacy modules have issues; they'll surface on use.
        import logging
        logging.getLogger(__name__).warning(f"Model import warning during create_tables: {e}")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
