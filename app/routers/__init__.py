"""API routers for FinAI Service."""
from .health import router as health_router
from .chatbot import router as chatbot_router
from .voicebot import router as voicebot_router
from .internal import callback as internal_callback_router

__all__ = [
    "health_router",
    "chatbot_router",
    "voicebot_router",
    "internal_callback_router",
]
