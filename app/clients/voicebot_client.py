from __future__ import annotations

from typing import Any, Dict, Optional

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class VoicebotClientError(RuntimeError):
    pass


class VoicebotClient:
    """HTTP client for FinAI Voicebot Service (remote local models).

    Endpoints used:
      - POST /v1/stt/transcribe?stack_id=...
      - POST /v1/llm/generate
      - POST /v1/tts/synthesize
      - GET  /v1/stacks
      - GET  /v1/catalog
      - POST /v1/stacks
    """

    def __init__(self, base_url: str, api_key: Optional[str], timeout_s: int) -> None:
        """
        Initialize the VoicebotClient with connection settings.
        
        Parameters:
            base_url (str): Base URL of the Voicebot service; trailing slashes are removed.
            api_key (Optional[str]): API key for authenticated requests; empty or whitespace-only values are normalized to None.
            timeout_s (int): Request timeout in seconds.
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = (api_key or "").strip() or None
        self.timeout_s = timeout_s

    @classmethod
    def from_settings(cls) -> "VoicebotClient":
        """
        Create a VoicebotClient configured from application settings.
        
        Reads VOICEBOT_REMOTE_BASE_URL, VOICEBOT_REMOTE_API_KEY, and VOICEBOT_REMOTE_TIMEOUT_S from the application's settings and returns a VoicebotClient initialized with those values.
        
        Returns:
            VoicebotClient: Configured client instance.
        
        Raises:
            VoicebotClientError: If VOICEBOT_REMOTE_BASE_URL is not set.
        """
        s = get_settings()
        if not s.VOICEBOT_REMOTE_BASE_URL:
            raise VoicebotClientError("VOICEBOT_REMOTE_BASE_URL is not set")
        return cls(base_url=s.VOICEBOT_REMOTE_BASE_URL, api_key=s.VOICEBOT_REMOTE_API_KEY, timeout_s=s.VOICEBOT_REMOTE_TIMEOUT_S)

    def _headers(self) -> Dict[str, str]:
        """
        Constructs the HTTP headers for requests to the Voicebot service.
        
        Returns:
            A dictionary of HTTP headers to include on requests; includes the `X-API-Key` header when an API key is configured on the client.
        """
        headers: Dict[str, str] = {}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    async def transcribe_wav(self, *, stack_id: str, wav_bytes: bytes, language: Optional[str] = None) -> Dict[str, Any]:
        """
        Transcribe WAV audio using the configured voicebot stack.
        
        Parameters:
            stack_id (str): Identifier of the voicebot stack to use for transcription.
            wav_bytes (bytes): Raw WAV audio bytes to transcribe.
            language (Optional[str]): Preferred language for transcription (currently ignored by the service; reserved for future use).
        
        Returns:
            dict: Parsed JSON response from the voicebot STT endpoint containing transcription results.
        
        Raises:
            VoicebotClientError: If the request fails (HTTP error status) or the response is not a valid JSON object.
        """
        url = f"{self.base_url}/v1/stt/transcribe"
        params = {"stack_id": stack_id}
        files = {"audio": ("audio.wav", wav_bytes, "audio/wav")}
        # Voicebot STT ignores language today; keep param for future extension.
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            r = await client.post(url, params=params, headers=self._headers(), files=files)
        if r.status_code >= 400:
            raise VoicebotClientError(f"voicebot stt failed: {r.status_code}: {r.text[:600]}")
        data = r.json()
        if not isinstance(data, dict):
            raise VoicebotClientError("voicebot stt invalid response")
        return data

    async def generate(self, *, stack_id: str, system: str, user: str) -> str:
        """
        Generate a text response from the voicebot LLM for the specified stack and inputs.
        
        Parameters:
            stack_id (str): Identifier of the voicebot stack to use.
            system (str): System/instruction prompt provided to the LLM (may be empty).
            user (str): User prompt or message to generate a response for.
        
        Returns:
            str: The trimmed text produced by the LLM.
        
        Raises:
            VoicebotClientError: If the HTTP request fails or the response is missing or malformed.
        """
        url = f"{self.base_url}/v1/llm/generate"
        payload = {"stack_id": stack_id, "system": system or "", "user": user}
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            r = await client.post(url, headers={**self._headers(), "Content-Type": "application/json"}, json=payload)
        if r.status_code >= 400:
            raise VoicebotClientError(f"voicebot llm failed: {r.status_code}: {r.text[:600]}")
        data = r.json()
        if not isinstance(data, dict) or "text" not in data:
            raise VoicebotClientError("voicebot llm invalid response")
        return str(data["text"]).strip()

    async def synthesize(self, *, stack_id: str, text: str, lang: str) -> bytes:
        """
        Synthesize speech from text using a specified voicebot stack.
        
        Parameters:
            stack_id (str): Identifier of the voicebot stack to use.
            text (str): Text to be converted to speech.
            lang (str): Language code for synthesis (e.g., "en-US").
        
        Returns:
            bytes: Audio bytes containing the synthesized speech.
        
        Raises:
            VoicebotClientError: If the voicebot service responds with an error status.
        """
        url = f"{self.base_url}/v1/tts/synthesize"
        payload = {"stack_id": stack_id, "text": text, "lang": lang}
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            r = await client.post(url, headers={**self._headers(), "Content-Type": "application/json"}, json=payload)
        if r.status_code >= 400:
            raise VoicebotClientError(f"voicebot tts failed: {r.status_code}: {r.text[:600]}")
        return r.content

    async def list_stacks(self) -> list[str]:
        """
        Get available voicebot stack identifiers from the remote service.
        
        Queries the /v1/stacks endpoint and returns the list of stack IDs as strings; if the response JSON does not contain a list under the "stacks" key, returns an empty list.
        
        Returns:
            list[str]: Stack identifier strings, or an empty list if the response is missing or malformed.
        
        Raises:
            VoicebotClientError: If the HTTP request returns an error status.
        """
        url = f"{self.base_url}/v1/stacks"
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            r = await client.get(url, headers=self._headers())
        if r.status_code >= 400:
            raise VoicebotClientError(f"voicebot stacks failed: {r.status_code}: {r.text[:600]}")
        data = r.json()
        stacks = data.get("stacks") if isinstance(data, dict) else None
        if not isinstance(stacks, list):
            return []
        return [str(x) for x in stacks]

    async def get_catalog(self) -> Dict[str, Any]:
        """
        Fetches the voicebot catalog from the configured service.
        
        Returns:
            dict: Parsed JSON catalog data.
        
        Raises:
            VoicebotClientError: If the HTTP request fails (status >= 400) or the response is not a JSON object.
        """
        url = f"{self.base_url}/v1/catalog"
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            r = await client.get(url, headers=self._headers())
        if r.status_code >= 400:
            raise VoicebotClientError(f"voicebot catalog failed: {r.status_code}: {r.text[:600]}")
        data = r.json()
        if not isinstance(data, dict):
            raise VoicebotClientError("voicebot catalog invalid response")
        return data

    async def create_stack(self, *, stt_id: str, llm_id: Optional[str], tts_id: str, stack_id: Optional[str] = None, label: Optional[str] = None) -> str:
        """
        Create a new voicebot stack on the remote service.
        
        Parameters:
            stt_id (str): Identifier of the speech-to-text component to include in the stack.
            llm_id (Optional[str]): Identifier of the language model component, or `None` if not applicable.
            tts_id (str): Identifier of the text-to-speech component to include in the stack.
            stack_id (Optional[str]): Optional explicit stack identifier to request; if omitted the service will assign one.
            label (Optional[str]): Optional human-readable label for the new stack.
        
        Returns:
            str: The created stack's identifier returned by the service.
        
        Raises:
            VoicebotClientError: If the HTTP request fails or the service response does not contain a valid `stack_id`.
        """
        url = f"{self.base_url}/v1/stacks"
        payload: Dict[str, Any] = {"stt_id": stt_id, "llm_id": llm_id, "tts_id": tts_id}
        if stack_id:
            payload["stack_id"] = stack_id
        if label:
            payload["label"] = label
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            r = await client.post(url, headers={**self._headers(), "Content-Type": "application/json"}, json=payload)
        if r.status_code >= 400:
            raise VoicebotClientError(f"voicebot create stack failed: {r.status_code}: {r.text[:600]}")
        data = r.json()
        sid = data.get("stack_id") if isinstance(data, dict) else None
        if not sid:
            raise VoicebotClientError("voicebot create stack invalid response")
        return str(sid)
