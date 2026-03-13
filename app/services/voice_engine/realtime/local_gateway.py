from __future__ import annotations

import asyncio
import base64
import json
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.audio.codecs import PCM16Audio, chunk_bytes
from app.services.audio.tts_service import synthesize
from app.services.audio.stt_service import transcribe_pcm16
from app.clients.voicebot_client import VoicebotClient, VoicebotClientError

logger = get_logger(__name__)


@dataclass
class LocalSessionConfig:
    instructions: str = "You are a helpful voice assistant."
    input_audio_format: str = "g711_ulaw"
    output_audio_format: str = "g711_ulaw"
    voice: Optional[str] = None
    language: Optional[str] = None
    # Provider selection
    stt_provider: Optional[str] = None
    tts_provider: Optional[str] = None
    llm_provider: Optional[str] = None
    voicebot_stack_id: Optional[str] = None


class LocalRealtimeSession:
    """Implements a minimal subset of the OpenAI Realtime protocol.

    Compatible with ``OpenAIRealtimeBridge`` in this repo:
    - accepts ``session.update``
    - accepts ``input_audio_buffer.append``
    - optionally accepts ``response.create``
    - emits ``response.output_audio.delta``
    - emits transcript events for post-call analytics

    Under the hood, it can run:
    - native audio-to-audio models (when added later)
    - OR fallback STT -> LLM -> TTS (default, production-friendly)
    """

    def __init__(self) -> None:
        self.s = get_settings()
        self.cfg = LocalSessionConfig(
            stt_provider=self.s.STT_PROVIDER,
            tts_provider=self.s.TTS_PROVIDER,
            llm_provider=("openai_compat"),
            voicebot_stack_id=self.s.VOICEBOT_REMOTE_DEFAULT_STACK,
        )
        self._pcm_buf = bytearray()  # PCM16 @16kHz
        self._last_audio_ts: float = 0.0
        self._processing = False
        self._force_response = asyncio.Event()

    def update_from_session(self, session: Dict[str, Any]) -> None:
        self.cfg.instructions = str(session.get("instructions") or self.cfg.instructions)
        self.cfg.input_audio_format = str(session.get("input_audio_format") or self.cfg.input_audio_format)
        self.cfg.output_audio_format = str(session.get("output_audio_format") or self.cfg.output_audio_format)
        self.cfg.voice = session.get("voice") or self.cfg.voice
        # Some clients send language in input_audio_transcription
        iat = session.get("input_audio_transcription") or {}
        if isinstance(iat, dict):
            self.cfg.language = iat.get("language") or self.cfg.language

        # Non-standard metadata: used by our telephony gateway to pass per-agent model selection.
        meta = session.get("metadata") or {}
        if isinstance(meta, dict):
            self.cfg.stt_provider = meta.get("stt_provider") or self.cfg.stt_provider
            self.cfg.tts_provider = meta.get("tts_provider") or self.cfg.tts_provider
            self.cfg.llm_provider = meta.get("llm_provider") or self.cfg.llm_provider
            self.cfg.voicebot_stack_id = meta.get("voicebot_stack_id") or self.cfg.voicebot_stack_id

    def append_audio_pcm16_16k(self, pcm16_16k: bytes) -> None:
        if not pcm16_16k:
            return
        self._pcm_buf.extend(pcm16_16k)
        self._last_audio_ts = time.time()

    def force_response(self) -> None:
        self._force_response.set()

    def take_buffer(self) -> PCM16Audio:
        data = bytes(self._pcm_buf)
        self._pcm_buf.clear()
        return PCM16Audio(pcm16=data, sample_rate=16000)

    async def _llm_reply(self, user_text: str) -> str:
        """Generate assistant reply.

        Supported modes:
          - llm_provider='openai_compat': call OpenAI-compatible /chat/completions (OpenAI, vLLM, etc.)
          - llm_provider='voicebot': call FinAI Voicebot Service /v1/llm/generate using voicebot_stack_id
        """
        if not user_text:
            return ""

        lp = (self.cfg.llm_provider or "openai_compat").lower().strip()

        if lp == "voicebot":
            try:
                client = VoicebotClient.from_settings()
            except Exception as e:
                logger.error("voicebot_llm_not_configured", error=str(e))
                return "Sorry, LLM is not configured."

            sid = (self.cfg.voicebot_stack_id or self.s.VOICEBOT_REMOTE_DEFAULT_STACK or "").strip()
            if not sid:
                logger.error("voicebot_llm_stack_missing")
                return "Sorry, LLM is not configured."

            try:
                return await client.generate(stack_id=sid, system=self.cfg.instructions, user=user_text)
            except VoicebotClientError as e:
                logger.error("voicebot_llm_failed", error=str(e))
                return "Sorry, I had trouble generating a reply."

        # Default: OpenAI-compatible /chat/completions
        model = self.s.LOCAL_LLM_MODEL or self.s.OPENAI_CHAT_MODEL
        base = (self.s.LOCAL_LLM_BASE_URL or self.s.OPENAI_BASE_URL or "https://api.openai.com/v1").rstrip("/")
        api_key = self.s.LOCAL_LLM_API_KEY or self.s.OPENAI_API_KEY
        if not api_key:
            return "Sorry, LLM is not configured."

        url = base + "/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        messages = [
            {"role": "system", "content": self.cfg.instructions},
            {"role": "user", "content": user_text},
        ]
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 400,
        }
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(url, headers=headers, json=payload)
            if r.status_code >= 400:
                logger.error("local_llm_failed", status=r.status_code, body=r.text[:800])
                return "Sorry, I had trouble generating a reply."
            data = r.json()
        try:
            return str(data["choices"][0]["message"]["content"]).strip()
        except Exception:
            return "Sorry, I had trouble generating a reply."
            data = r.json()
        try:
            return str(data["choices"][0]["message"]["content"]).strip()
        except Exception:
            return "Sorry, I had trouble generating a reply."

    async def process_turn(self) -> tuple[str, str, bytes]:
        """Run STT -> LLM -> TTS and return (user_text, assistant_text, audio_bytes)."""
        audio = self.take_buffer()
        if not audio.pcm16:
            return "", "", b""

        sid = (self.cfg.voicebot_stack_id or self.s.VOICEBOT_REMOTE_DEFAULT_STACK or "").strip()

        stt_t0 = time.perf_counter()
        user_text = await transcribe_pcm16(
            audio,
            provider=self.cfg.stt_provider or self.s.STT_PROVIDER,
            language=self.cfg.language,
            stack_id=sid if (self.cfg.stt_provider or "").lower().strip() == "voicebot" else None,
        )
        stt_ms = int((time.perf_counter() - stt_t0) * 1000)

        llm_t0 = time.perf_counter()
        assistant_text = await self._llm_reply(user_text)
        llm_ms = int((time.perf_counter() - llm_t0) * 1000)

        tts_t0 = time.perf_counter()
        audio_out = await synthesize(
            assistant_text,
            provider=self.cfg.tts_provider or self.s.TTS_PROVIDER,
            voice=self.cfg.voice,
            language=self.cfg.language,
            output_format=self.cfg.output_audio_format,
            stack_id=sid if (self.cfg.tts_provider or "").lower().strip() == "voicebot" else None,
        )
        tts_ms = int((time.perf_counter() - tts_t0) * 1000)

        logger.info(
            "local_gateway_turn",
            stt_ms=stt_ms,
            llm_ms=llm_ms,
            tts_ms=tts_ms,
            stt_provider=self.cfg.stt_provider,
            llm_provider=self.cfg.llm_provider,
            tts_provider=self.cfg.tts_provider,
            voicebot_stack_id=sid,
        )

        return user_text, assistant_text, audio_out

    async def run_loop(self, send_json) -> None:
        """Background loop: detect end-of-turn and emit audio deltas."""
        silence_s = 0.65
        min_audio_ms = 450

        while True:
            await asyncio.sleep(0.05)
            if self._processing:
                continue

            # forced response (client requested)
            if self._force_response.is_set():
                self._force_response.clear()
                if len(self._pcm_buf) >= int(16000 * 2 * (min_audio_ms / 1000.0)):
                    self._processing = True
                    try:
                        await _emit_response(self, send_json)
                    finally:
                        self._processing = False
                continue

            if not self._pcm_buf:
                continue
            if self._last_audio_ts and (time.time() - self._last_audio_ts) < silence_s:
                continue
            # enough audio?
            if len(self._pcm_buf) < int(16000 * 2 * (min_audio_ms / 1000.0)):
                # too short, drop
                self._pcm_buf.clear()
                continue

            self._processing = True
            try:
                await _emit_response(self, send_json)
            finally:
                self._processing = False


async def _emit_response(sess: LocalRealtimeSession, send_json) -> None:
    user_text, assistant_text, audio_out = await sess.process_turn()
    if user_text:
        await send_json({"type": "conversation.item.input_audio_transcription.completed", "text": user_text})
    if assistant_text:
        await send_json({"type": "response.output_audio_transcript.done", "transcript": assistant_text})

    # chunk audio into ~40ms frames (320 bytes for 8k u-law)
    for chunk in chunk_bytes(audio_out, 320):
        if not chunk:
            continue
        await send_json({"type": "response.output_audio.delta", "delta": base64.b64encode(chunk).decode("ascii")})
