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
    """
    Retrieve a ChatSession by session_id, creating and attaching a new active session if none exists.
    
    Parameters:
        session_id (UUID): Identifier of the session to retrieve.
        user_id (UUID | None): Optional owner user ID to set when creating a new session.
        channel (SessionChannel): Channel value to set when creating a new session.
    
    Returns:
        ChatSession: The existing or newly created ChatSession. If created, the session is added to the provided database session.
    """
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
    """
    Retrieve all ChatSession records for a user ordered by creation time descending.
    
    Returns:
        list[ChatSession]: ChatSession instances belonging to the specified user, newest first.
    """
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
    """
    Retrieve a ChatSession by its session_id.
    
    Returns:
        The ChatSession with the given session_id, or `None` if no matching session exists.
    """
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.session_id == session_id)
    )
    return result.scalar_one_or_none()