"""
Chatbot endpoints.

Provides both authenticated and public (rate-limited) chat endpoints.
"""

import logging
from typing import Dict, Optional
from uuid import UUID, uuid4
import re
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.db import get_db
from app.core.auth import get_current_user, get_optional_user
from app.core.rate_limiter import rate_limiter, check_public_chat_rate_limit, get_client_ip
from app.schemas.chatbot import ChatMessageRequest, PublicChatRequest, PublicChatResponse, LenderAdviceRequest
from app.services.chatbot_service import ChatbotService
from app.models.conversation import ChatMessage
from app.core.config import settings
from shared.responses import success_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/chat", tags=["Chatbot"])



def _generate_session_id() -> str:
    return str(uuid4())


def _sanitize_public_message(message: str) -> str:
    """Basic public-input sanitization (keep behavior consistent with legacy PublicChatRequest)."""
    message = " ".join(message.split())
    message = "".join(ch for ch in message if ch.isprintable() or ch in "\n\t")
    return message


def _parse_session_uuid(session_id: str) -> UUID:
    """Parse and validate a UUID session_id (DB column is UUID)."""
    try:
        sid = UUID(session_id)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="session_id must be a valid UUID",
        )

    # Optional: enforce only UUIDv4
    # if sid.version != 4:
    #     raise HTTPException(
    #         status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    #         detail="session_id must be a UUIDv4",
    #     )

    return sid

# =====================
# Authenticated Endpoints
# =====================

@router.post("/message")
async def send_message(
    request: ChatMessageRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[Dict] = Depends(get_optional_user),
):
    # Decide flow
    is_login = request.is_login if request.is_login is not None else (current_user is not None)

    if is_login and current_user is None:
        if settings.DEBUG:
            current_user = {
                "user_id": "00000000-0000-0000-0000-000000000001",
                "user_type": "INTERNAL",
                "role_code": "SUPER_ADMIN",
                "permissions": ["*"],
                "token": None,
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required (is_login=true)",
            )

    is_public = not is_login

    # Session id generation / validation (UUID only)
    raw_session_id = request.session_id or _generate_session_id()
    session_uuid = _parse_session_uuid(str(raw_session_id))
    sid = str(session_uuid)  # canonical session id string to use everywhere

    # Public flow protections
    client_ip: Optional[str] = None
    usage: Optional[dict] = None
    user_message = request.message

    if is_public:
        client_ip = await check_public_chat_rate_limit(http_request)

        # IMPORTANT: use canonical sid for limiter keys
        is_allowed, messages_used, _messages_remaining = rate_limiter.check_session_limit(sid)
        if not is_allowed:
            return success_response(
                message="Session limit reached",
                data={
                    "session_id": sid,
                    "response": (
                        "You've reached the message limit for public chat. "
                        "Please register for a free account to continue our conversation "
                        "and get personalized loan recommendations!"
                    ),
                    "intent": "limit_reached",
                    "usage": {
                        "messages_used": messages_used,
                        "messages_remaining": 0,
                        "is_limit_reached": True,
                        "upgrade_cta": "Register now for unlimited chat and personalized loan matching!",
                    },
                },
            )

        user_message = _sanitize_public_message(user_message)
        user_message = user_message[: settings.PUBLIC_CHAT_MAX_MESSAGE_LENGTH]

    # Auth context
    user_id = UUID(current_user["user_id"]) if (is_login and current_user and current_user.get("user_id")) else None
    user_token = current_user.get("token") if (is_login and current_user) else None

    service = ChatbotService(db)
    conversation, user_msg, response = await service.process_message(
        session_id=sid,  # DB stores UUID -> pass canonical UUID string or UUID object depending on service
        user_message=user_message,
        user_id=user_id,
        user_token=user_token,
        context_type=request.context_type,
        context_id=request.context_id,
        is_public=is_public,
    )

    if is_public:
        rate_limiter.increment_session_count(sid)
        usage = rate_limiter.get_session_info(sid)
        logger.info(
            "Public chat: IP=%s, session=%s..., messages=%s",
            client_ip,
            sid[:12],
            usage.get("messages_used") if usage else None,
        )

    payload = {
        "conversation_id": str(conversation.id),
        "session_id": sid,   # IMPORTANT: return canonical UUID
        "is_public": is_public,
        "user_message": {
            "id": str(user_msg.id) if user_msg else None,
            "content": user_msg.content if user_msg else user_message,
            "intent": user_msg.detected_intent if user_msg else None,
        },
        "response": response,
    }
    if usage is not None:
        payload["usage"] = usage

    return success_response(message="Message processed", data=payload)


@router.get("/conversation/{session_id}")
async def get_conversation(
    session_id: str,
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: Dict = Depends(get_current_user),
):
    """Get conversation history for a session."""
    service = ChatbotService(db)
    
    conversation = await service.get_conversation_history(session_id, limit)
    
    if not conversation:
        return success_response(
            message="No active conversation found",
            data={"messages": [], "conversation_id": None}
        )
    
    # Get messages
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation.id)
        .order_by(ChatMessage.created_at)
        .limit(limit)
    )
    messages = list(result.scalars().all())
    
    return success_response(
        message="Conversation retrieved",
        data={
            "conversation_id": str(conversation.id),
            "status": conversation.status,
            "context_type": conversation.context_type,
            "is_public": conversation.is_public,
            "messages": [
                {
                    "id": str(m.id),
                    "role": m.role,
                    "content": m.content,
                    "intent": m.detected_intent,
                    "created_at": m.created_at.isoformat(),
                }
                for m in messages
            ],
        }
    )


@router.post("/conversation/{session_id}/end")
async def end_conversation(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Dict = Depends(get_current_user),
):
    """End an active conversation."""
    service = ChatbotService(db)
    
    ended = await service.end_conversation(session_id)
    
    if not ended:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active conversation found",
        )
    
    return success_response(
        message="Conversation ended",
        data={"session_id": session_id}
    )


# =====================
# Public Chat Endpoint (Rate Limited)
# =====================

@router.post("/public", response_model=None)
async def public_chat(
    request: PublicChatRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    client_ip: str = Depends(check_public_chat_rate_limit),
):
    """
    Public chat endpoint for unauthenticated users.
    
    **Rate Limits:**
    - {max_messages} messages per session
    - {rate_limit} requests per minute per IP
    
    **Security:**
    - Input validation and sanitization
    - No personal data collection
    - Session-based message limits
    
    Recommended for:
    - Landing page FAQ bots
    - Pre-registration assistance
    - General loan information
    
    To unlock full features (personalized recommendations, lead tracking),
    users should register and use the authenticated endpoint.
    """.format(
        max_messages=settings.PUBLIC_CHAT_MAX_MESSAGES,
        rate_limit=settings.PUBLIC_CHAT_RATE_LIMIT
    )
    
    # Check session message limit
    is_allowed, messages_used, messages_remaining = rate_limiter.check_session_limit(
        request.session_id
    )
    
    if not is_allowed:
        return success_response(
            message="Session limit reached",
            data={
                "conversation_id": request.session_id,
                "response": (
                    "You've reached the message limit for public chat. "
                    "Please register for a free account to continue our conversation "
                    "and get personalized loan recommendations!"
                ),
                "intent": "limit_reached",
                "usage": {
                    "messages_used": messages_used,
                    "messages_remaining": 0,
                    "is_limit_reached": True,
                    "upgrade_cta": "Register now for unlimited chat and personalized loan matching!",
                },
            }
        )
    
    service = ChatbotService(db)
    
    try:
        conversation, user_msg, response = await service.process_message(
            session_id=request.session_id,
            user_message=request.message,
            user_id=None,
            user_token=None,
            context_type=None,
            context_id=None,
            is_public=True,
        )
        
        # Increment session counter
        rate_limiter.increment_session_count(request.session_id)
        
        # Get updated usage
        usage = rate_limiter.get_session_info(request.session_id)
        
        # Log for security monitoring
        logger.info(f"Public chat: IP={client_ip}, session={request.session_id[:12]}..., messages={usage['messages_used']}")
        
        return success_response(
            message="Message processed",
            data={
                "conversation_id": str(conversation.id),
                "response": response,
                "intent": user_msg.detected_intent if user_msg else None,
                "usage": usage,
            }
        )
    
    except Exception as e:
        logger.error(f"Public chat error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred processing your message. Please try again.",
        )


@router.get("/public/session/{session_id}")
async def get_public_session_info(
    session_id: str,
    http_request: Request,
    client_ip: str = Depends(check_public_chat_rate_limit),
):
    """
    Get usage info for a public chat session.
    
    Returns message usage and remaining quota.
    """
    usage = rate_limiter.get_session_info(session_id)
    
    return success_response(
        message="Session info retrieved",
        data={
            "session_id": session_id,
            **usage,
            "max_messages": settings.PUBLIC_CHAT_MAX_MESSAGES,
        }
    )


# =====================
# Lender Selection Helper
# =====================

@router.post("/lender-advice")
async def get_lender_advice(
    request: LenderAdviceRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Dict = Depends(get_current_user),
):
    service = ChatbotService(db)

    user_id = UUID(current_user["user_id"]) if current_user.get("user_id") else None
    user_token = current_user.get("token")

    lead_id = request.lead_id
    question = request.question

    session_id = f"lender-advice-{lead_id}"

    conversation, user_msg, response = await service.process_message(
        session_id=session_id,
        user_message=question,
        user_id=user_id,
        user_token=user_token,
        context_type="lender_selection",
        context_id=lead_id,
        is_public=False,
    )

    return success_response(
        message="Advice generated",
        data={
            "lead_id": str(lead_id),
            "question": question,
            "advice": response,
            "intent": user_msg.detected_intent if user_msg else "lender_selection",
        },
    )
