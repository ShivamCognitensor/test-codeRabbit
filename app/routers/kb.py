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
    """
    Provide current knowledge base configuration and ensure KB data is loaded.
    
    Returns:
        dict: Status and configuration of the knowledge base with keys:
            - enabled (bool): Whether the knowledge base feature is enabled.
            - docs_path (str): Filesystem path to the source documents.
            - index_dir (str): Directory path where the KB index is stored.
            - embed_model (str): Name of the embedding model used for vectors.
            - top_k (int): Default number of nearest neighbors to return.
            - min_score (float): Minimum similarity score threshold for results.
    """
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
    """
    Trigger a knowledge base reindex and return the resulting statistics.
    
    Returns:
        dict: A response payload containing `"ok": True` and the reindex statistics returned by the KnowledgeBase service.
    
    Raises:
        HTTPException: If the knowledge base feature is disabled (settings.KB_ENABLED is False). The exception has status code 400 and detail "KB is disabled. Set KB_ENABLED=true".
    """
    if not settings.KB_ENABLED:
        raise HTTPException(status_code=400, detail="KB is disabled. Set KB_ENABLED=true")

    kb = KnowledgeBase()
    stats = await kb.reindex()
    return {"ok": True, **stats}
