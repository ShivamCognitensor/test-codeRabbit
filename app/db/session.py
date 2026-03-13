"""Legacy DB session dependency.

The new service uses `app.core.db.get_db()` which yields an AsyncSession and
closes it. Legacy routers expect `app.db.session.get_db()` that also commits
on success and rolls back on error.

We implement legacy behavior while sharing the same engine/sessionmaker.
"""

from __future__ import annotations

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import async_session_maker


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Provide a transactional database session for legacy dependencies.
    
    Yields a session to the caller; commits the transaction if the caller completes normally, rolls back and re-raises if an exception occurs, and always closes the session when finished.
    
    Returns:
        An AsyncSession for performing database operations within the yielded transactional scope.
    """
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
