"""Knowledge Base admin endpoints (optional).

These endpoints are useful when the Audio Bot / LLM server is configured to use
local RAG (`KB_ENABLED=true`).

They are intentionally small:
- GET  /v1/kb/status
- POST /v1/kb/reindex
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.core.config import settings
from app.services.kb.kb_service import KnowledgeBase


router = APIRouter(prefix="/v1/kb", tags=["KnowledgeBase"])


@router.get("/status")
async def kb_status():
    kb = KnowledgeBase()
    await kb.ensure_loaded()
    return {
        "enabled": settings.KB_ENABLED,
        "docs_path": settings.KB_DOCS_PATH,
        "index_dir": settings.KB_INDEX_DIR,
        "embed_model": settings.KB_EMBED_MODEL,
        "top_k": settings.KB_TOP_K,
        "min_score": settings.KB_MIN_SCORE,
    }


@router.post("/reindex")
async def kb_reindex():
    if not settings.KB_ENABLED:
        raise HTTPException(status_code=400, detail="KB is disabled. Set KB_ENABLED=true")

    kb = KnowledgeBase()
    stats = await kb.reindex()
    return {"ok": True, **stats}
