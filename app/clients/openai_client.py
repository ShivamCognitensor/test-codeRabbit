"""OpenAI client for chat and embeddings."""

import logging
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)


class OpenAIClient:
    """Client for OpenAI API."""
    
    def __init__(self):
        self._client: Optional[AsyncOpenAI] = None
        self._enabled = bool(settings.OPENAI_API_KEY)
    
    @property
    def client(self) -> Optional[AsyncOpenAI]:
        """Lazy initialization of OpenAI client."""
        if not self._enabled:
            return None
        
        if self._client is None:
            kwargs = {
                "api_key": settings.OPENAI_API_KEY,
            }
            if settings.OPENAI_BASE_URL:
                kwargs["base_url"] = settings.OPENAI_BASE_URL
            if settings.OPENAI_ORG_ID:
                kwargs["organization"] = settings.OPENAI_ORG_ID
            
            self._client = AsyncOpenAI(**kwargs)
        
        return self._client
    
    @property
    def is_enabled(self) -> bool:
        """Check if OpenAI is configured."""
        return self._enabled
    
    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs
    ) -> str:
        """
        Generate a chat completion.
        
        Returns the assistant's response text.
        """
        if not self.is_enabled:
            raise RuntimeError("OpenAI is not configured. Set OPENAI_API_KEY.")
        
        model = model or settings.OPENAI_CHAT_MODEL
        
        try:
            response = await self.client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs
            )
            
            return response.choices[0].message.content
        
        except Exception as e:
            # logger.error(f"OpenAI chat completion failed: {e}")
            logger.exception("OpenAI chat completion failed (%s): %s", type(e).__name__, e)
            raise
    
    async def create_embeddings(
        self,
        texts: List[str],
        model: Optional[str] = None,
    ) -> List[List[float]]:
        """
        Create embeddings for given texts.
        
        Returns list of embedding vectors.
        """
        if not self.is_enabled:
            raise RuntimeError("OpenAI is not configured. Set OPENAI_API_KEY.")
        
        model = model or settings.KB_EMBED_MODEL
        
        try:
            response = await self.client.embeddings.create(
                model=model,
                input=texts,
            )
            
            return [item.embedding for item in response.data]
        
        except Exception as e:
            logger.error(f"OpenAI embeddings failed: {e}")
            raise


# Singleton instance
openai_client = OpenAIClient()


# ---------------------------------------------------------------------------
# Legacy compatibility: v17 code expects `get_openai_client()`
# ---------------------------------------------------------------------------

from openai import AsyncOpenAI  # type: ignore


def get_openai_client() -> AsyncOpenAI:
    """Return an OpenAI Async client configured from settings (legacy helper)."""
    s = settings
    kwargs = {"api_key": s.OPENAI_API_KEY}
    if s.OPENAI_BASE_URL:
        kwargs["base_url"] = s.OPENAI_BASE_URL

    client = AsyncOpenAI(**kwargs)

    # Org/Project routing when provided (optional)
    if s.OPENAI_ORG_ID:
        try:
            client.organization = s.OPENAI_ORG_ID
        except Exception:
            pass
    if s.OPENAI_PROJECT_ID:
        try:
            client.project = s.OPENAI_PROJECT_ID
        except Exception:
            pass

    return client
