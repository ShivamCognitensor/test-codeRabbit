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
    """
    Create and stage a new ChatMessage associated with a session.
    
    Parameters:
        db (AsyncSession): Asynchronous database session used to add the message.
        session_id (uuid.UUID): Identifier of the chat session to associate the message with.
        role (ChatRole): Role of the message sender (e.g., user, assistant, system).
        message (str): Text content of the message.
    
    Returns:
        ChatMessage: The newly created ChatMessage instance that has been added to the provided session (not committed).
    
    Raises:
        TypeError: If `message` is not a string.
    """
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
    """
    Retrieve chat messages for a session ordered by creation time.
    
    Returns:
        list[ChatMessage]: ChatMessage instances for the given session ordered by creation time (oldest first).
    """
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc())
    )
    return result.scalars().all()
