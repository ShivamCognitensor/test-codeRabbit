import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat_models import ChatMessage
from app.models.enums import ChatRole


async def save_message(
    db: AsyncSession,
    session_id: uuid.UUID,
    role: ChatRole,
    message: str,
) -> ChatMessage:
    if not isinstance(message, str):
        raise TypeError("message must be a string")

    chat_message = ChatMessage(
        id=uuid.uuid4(),
        session_id=session_id,
        role=role,
        message=message,
    )

    db.add(chat_message)
    return chat_message


async def get_messages_by_session(
    db: AsyncSession,
    session_id: uuid.UUID,
):
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc())
    )
    return result.scalars().all()
