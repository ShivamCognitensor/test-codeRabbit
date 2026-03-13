from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID

from app.models.session_models import ChatSession
from app.models.enums import SessionStatus, SessionChannel


async def get_or_create_session(
    db: AsyncSession,
    session_id: UUID,
    user_id: UUID | None,
    channel: SessionChannel,
) -> ChatSession:
    result = await db.execute(
        select(ChatSession).where(ChatSession.session_id == session_id)
    )
    session = result.scalar_one_or_none()

    if session is None:
        session = ChatSession(
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            status=SessionStatus.active,
        )
        db.add(session)

    return session


async def list_sessions_by_user(
    db: AsyncSession,
    user_id: UUID,
):
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.user_id == user_id)
        .order_by(ChatSession.created_at.desc())
    )
    return result.scalars().all()


async def get_session_by_id(
    db: AsyncSession,
    session_id: UUID,
):
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.session_id == session_id)
    )
    return result.scalar_one_or_none()