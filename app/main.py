"""LMS FinAI Service - Main application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.db import create_tables
from app.routers.health import router as health_router
from app.routers.chatbot import router as chatbot_router
from app.routers.voicebot import router as voicebot_router
from app.routers.dashboard import router as dashboard_router
from app.routers.internal.callback import router as internal_callback_router
from app.routers.openai_compat import router as openai_compat_router
from app.routers.kb import router as kb_router
from app.routers.webhook import router as webhook_router
from app.routers.agents import router as agents_router
from app.routers.telephony import router as telephony_router
from app.routers.realtime_local import router as realtime_local_router
from app.routers.audio import router as audio_router
from app.routers.ui_catalog import router as ui_catalog_router
from app.services.bolna.campaign_runner import campaign_runner
from app.routers.voicebot_realtime_proxy import router as voicebot_realtime_proxy_router


# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    logger.info("Starting LMS FinAI Service...")
    try:
        await create_tables()
        logger.info("Database tables created/verified")

        # START campaign runner
        campaign_runner.start()
        
        yield

        # STOP campaign runner
        campaign_runner.shutdown()
        logger.info("Shutting down LMS FinAI Service...")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
    
    yield
    
    # Shutdown
    logger.info("Shutting down LMS FinAI Service...")


# Create FastAPI application
app = FastAPI(
    title="LMS FinAI Service",
    description="Chatbot and Voice Bot for lead generation",
    version="2.0.0",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health_router)
app.include_router(chatbot_router)
app.include_router(voicebot_router)
app.include_router(dashboard_router)
app.include_router(internal_callback_router)

# Dynamic agent profiles + multi-provider telephony gateway
app.include_router(agents_router)
app.include_router(telephony_router)

# Local realtime gateway + STT/TTS utilities (optional)
app.include_router(realtime_local_router)
app.include_router(audio_router)

# Bolna / audio-bot helpers (OpenAI-compatible surface + optional KB admin)
app.include_router(openai_compat_router)
app.include_router(kb_router)
app.include_router(webhook_router)
app.include_router(ui_catalog_router)
app.include_router(voicebot_realtime_proxy_router)

# Note: legacy v17 router package removed for a cleaner, single routing surface.
# All supported endpoints are exposed via app/routers/*


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )