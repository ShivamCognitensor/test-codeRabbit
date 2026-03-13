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
    """
    Generate a new session identifier as a UUID4 string.
    
    Returns:
        str: A UUID4-formatted string suitable for use as a session identifier.
    """
    return str(uuid4())


def _sanitize_public_message(message: str) -> str:
    """
    Sanitize a public chat message by collapsing whitespace and removing non-printable characters except newline and tab.
    
    Parameters:
        message (str): Raw user-provided message.
    
    Returns:
        str: Message with consecutive whitespace collapsed to single spaces and with all non-printable characters removed except `\n` and `\t`.
    """
    message = " ".join(message.split())
    message = "".join(ch for ch in message if ch.isprintable() or ch in "\n\t")
    return message


def _parse_session_uuid(session_id: str) -> UUID:
    """
    Parse and validate session_id as a UUID and return the parsed UUID.
    
    Parameters:
        session_id (str): Session identifier string to validate.
    
    Returns:
        UUID: Parsed UUID object.
    
    Raises:
        HTTPException: with status 422 if `session_id` is not a valid UUID.
    """
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
    """
    Send a chat message and return the processed conversation response.
    
    Parameters:
        request (ChatMessageRequest): Payload containing `message`, optional `session_id`, optional `is_login`, and optional `context_type` / `context_id`.
        http_request (Request): Incoming HTTP request (used for public rate-limiting checks).
        db (AsyncSession): Database session dependency.
        current_user (Optional[Dict]): Optional authenticated user info dependency.
    
    Returns:
        dict: A success response payload containing:
            - conversation_id (str): Conversation identifier.
            - session_id (str): Canonical UUID session identifier.
            - is_public (bool): True for unauthenticated/public chats.
            - user_message (dict): {
                id (str|None), content (str), intent (str|None)
              }
            - response (str): Generated chatbot response.
            - usage (dict, optional): Session usage info when available.
    
    Raises:
        HTTPException: 401 if `is_login` is requested but no authenticated user is present (in non-DEBUG mode).
        HTTPException: 422 if the provided `session_id` is not a valid UUID.
    """
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
    """
    Retrieve conversation metadata and an ordered list of messages for a session.
    
    If no active conversation exists for the given session_id, the response contains an empty `messages` list and `conversation_id` set to None.
    
    Parameters:
        limit (int): Maximum number of messages to return (1-100).
    
    Returns:
        dict: Payload with the following keys:
            - conversation_id (str or None): UUID string of the conversation or None if not found.
            - status (str): Conversation status.
            - context_type (str or None): Conversation context type.
            - is_public (bool): Whether the conversation is public.
            - messages (list): Ordered list of messages, each a dict with:
                - id (str): Message UUID.
                - role (str): Message role (e.g., "user", "assistant").
                - content (str): Message content.
                - intent (str or None): Detected intent for the message.
                - created_at (str): ISO 8601 timestamp of message creation.
    """
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
    """
    End the active conversation identified by the given session_id.
    
    Parameters:
        session_id (str): The conversation session identifier (UUID string).
    
    Returns:
        dict: Success response containing the ended `session_id`.
    
    Raises:
        HTTPException: 404 Not Found with detail "No active conversation found" if there is no active conversation for the provided session_id.
    """
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
    Handle a public, rate-limited chat message and return the chatbot's reply.
    
    Enforces the per-session message quota and IP rate limit (via dependencies). Processes the provided message as a public chat, increments session usage on success, and logs public activity.
    
    Parameters:
        request (PublicChatRequest): Must include `session_id` (string) and `message` (string).
        http_request (Request): The incoming HTTP request (used for request context; not required to document further).
    
    Returns:
        A success_response payload containing:
          - `conversation_id` (str or None): ID of the conversation.
          - `response` (str): Chatbot-generated reply.
          - `intent` (str or None): Detected intent for the user message, if available.
          - `usage` (dict): Session usage info with keys such as `messages_used`, `messages_remaining`, and `is_limit_reached`.
    
    Behavior notes:
        - If the session's message limit is reached, returns a success_response with `intent` set to `"limit_reached"` and `usage` reflecting the exhausted quota and an upgrade CTA.
        - On internal processing errors, raises HTTPException with status 500.
    """
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
    Retrieve usage and quota for a public chat session.
    
    Returns a payload containing the session_id, usage metrics from the rate limiter (such as messages sent and remaining quota), and the configured `max_messages` for public sessions.
    
    Parameters:
        session_id (str): Public session identifier.
    
    Returns:
        dict: Response data including `session_id`, usage fields provided by the rate limiter, and `max_messages`.
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
    """
    Generate lender-specific advice for a lead based on the provided question.
    
    Processes the question in the context of the given lead and returns a structured response containing the generated advice and detected intent.
    
    Parameters:
        request (LenderAdviceRequest): Request payload containing `lead_id` (the lead identifier) and `question` (the user's question about lender selection).
    
    Returns:
        dict: A success response payload with `data` containing:
            - `lead_id` (str): The lead identifier.
            - `question` (str): The original question.
            - `advice` (str): Generated advice text for the lead.
            - `intent` (str): Detected intent for the user message (falls back to `"lender_selection"` if not available).
    """
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
