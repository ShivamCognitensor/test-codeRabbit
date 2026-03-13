"""OpenAI client for chat and embeddings."""

import logging
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)


class OpenAIClient:
    """Client for OpenAI API."""
    
    def __init__(self):
        """
        Initialize the OpenAIClient, preparing lazy client creation and enabled state.
        
        Sets up internal attributes:
        - _client: initially None; will hold the lazily-initialized AsyncOpenAI client.
        - _enabled: True if settings.OPENAI_API_KEY is set, False otherwise.
        """
        self._client: Optional[AsyncOpenAI] = None
        self._enabled = bool(settings.OPENAI_API_KEY)
    
    @property
    def client(self) -> Optional[AsyncOpenAI]:
        """
        Return a lazily initialized AsyncOpenAI client configured from settings, or `None` if OpenAI is not enabled.
        
        Returns:
            AsyncOpenAI | None: An `AsyncOpenAI` instance created using API key and optional base URL and organization from settings, or `None` when OpenAI integration is disabled.
        """
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
        Generate a chat completion from the configured OpenAI chat model and return the assistant's message text.
        
        Parameters:
            messages (List[Dict[str, str]]): A sequence of message objects in chat format (each dict typically contains keys like 'role' and 'content').
            model (Optional[str]): Model name to use; falls back to settings.OPENAI_CHAT_MODEL when omitted.
            temperature (float): Sampling temperature controlling response randomness.
            max_tokens (int): Maximum number of tokens for the generated response.
            **kwargs: Additional parameters forwarded to the underlying OpenAI chat completion call.
        
        Returns:
            str: The content text of the assistant's first returned message.
        
        Raises:
            RuntimeError: If the OpenAI client is not configured (OPENAI_API_KEY not set).
            Exception: Re-raises any exception raised by the OpenAI client call after logging.
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
        Generate embedding vectors for a list of texts.
        
        Parameters:
            texts (List[str]): Text strings to convert into embeddings.
            model (Optional[str]): Optional embedding model name; defaults to settings.KB_EMBED_MODEL.
        
        Returns:
            List[List[float]]: A list of embedding vectors, one per input text.
        
        Raises:
            RuntimeError: If OpenAI is not configured (OPENAI_API_KEY not set).
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
