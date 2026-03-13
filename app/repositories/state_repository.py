from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID

from app.models.chat_models import ChatState


async def get_or_create_state(
    db: AsyncSession,
    session_id: UUID,
) -> ChatState:
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
    state = await get_or_create_state(db, session_id)

    state.current_step = step
    state.context = context

    return state


async def get_state_by_session(
    db: AsyncSession,
    session_id: UUID,
):
    result = await db.execute(
        select(ChatState)
        .where(ChatState.session_id == session_id)
    )
    return result.scalar_one_or_none()