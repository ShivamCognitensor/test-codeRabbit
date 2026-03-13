from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID

from app.models.chat_models import ChatState


async def get_or_create_state(
    db: AsyncSession,
    session_id: UUID,
) -> ChatState:
    """
    Retrieve the ChatState for a given session, creating and adding a new ChatState with an empty context if none exists.
    
    If no ChatState with the provided session_id is found, a new ChatState with an empty `context` is created and added to the provided database session.
    
    Returns:
        The existing or newly created ChatState.
    """
    result = await db.execute(
        select(ChatState).where(ChatState.session_id == session_id)
    )
    state = result.scalar_one_or_none()

    if state is None:
        state = ChatState(
            session_id=session_id,
            context={},
        )
        db.add(state)

    return state


async def update_state(
    db: AsyncSession,
    session_id: UUID,
    step: str,
    context: dict,
) -> ChatState:
    """
    Update the chat state for a given session, creating a new ChatState if one does not exist.
    
    Parameters:
        db (AsyncSession): Asynchronous database session used to fetch or create the state.
        session_id (UUID): Identifier of the chat session whose state will be updated.
        step (str): New value for the state's current step.
        context (dict): New context data to store on the state.
    
    Returns:
        ChatState: The updated (or newly created and updated) ChatState instance.
    """
    state = await get_or_create_state(db, session_id)

    state.current_step = step
    state.context = context

    return state


async def get_state_by_session(
    db: AsyncSession,
    session_id: UUID,
):
    """
    Fetches the ChatState for the given session identifier, or None if no matching state exists.
    
    Parameters:
        session_id (UUID): The session identifier to look up.
    
    Returns:
        ChatState | None: The matching ChatState instance if one exists, otherwise `None`.
    """
    result = await db.execute(
        select(ChatState)
        .where(ChatState.session_id == session_id)
    )
    return result.scalar_one_or_none()