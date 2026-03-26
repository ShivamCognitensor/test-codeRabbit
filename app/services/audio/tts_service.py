"""Text-to-speech providers.

Providers supported:

- Kokoro-82M (Python, CPU-friendly)  implemented (optional dep)
- Fish Speech 1.5 (OpenAI-compatible HTTP server)  implemented
- OpenAI TTS (optional)  implemented

We output either:
- raw PCM16 @16kHz (for internal processing)
- or PSTN codecs (G.711 u-law / A-law) via conversions.
"""

from __future__ import annotations

import asyncio
import base64
from functools import lru_cache
from typing import Optional

import httpx
import numpy as np
from fastapi import HTTPException

from app.core.config import get_settings
from app.core.logging import get_logger
from app.clients.voicebot_client import VoicebotClient, VoicebotClientError
from app.services.audio.codecs import (
    PCM16Audio,
    pcm16_16k_to_alaw8k,
    pcm16_16k_to_ulaw8k,
)

logger = get_logger(__name__)


class TTSError(RuntimeError):
    pass


def _lang_to_kokoro_code(language: Optional[str]) -> str:
    # Kokoro uses 1-letter lang codes in many examples.
    # en -> a, hi -> h
    if not language:
        return "a"
    l = language.lower()
    if l.startswith("hi"):
        return "h"
    if l.startswith("en"):
        return "a"
    if l.startswith("es"):
        return "e"
    if l.startswith("fr"):
        return "f"
    if l.startswith("it"):
        return "i"
    if l.startswith("pt"):
        return "p"
    # default english
    return "a"


@lru_cache(maxsize=8)
def _load_kokoro_pipeline(lang_code: str):
    try:
        from kokoro import KPipeline  # type: ignore
    except Exception as e:
        raise TTSError("kokoro is not installed. Install requirements.models.txt (Kokoro TTS).") from e
    return KPipeline(lang_code=lang_code)


def _float_to_pcm16(audio_f: np.ndarray) -> bytes:
    if audio_f.dtype != np.float32:
        audio_f = audio_f.astype(np.float32)
    audio_f = np.clip(audio_f, -1.0, 1.0)
    audio_i16 = (audio_f * 32767.0).astype(np.int16)
    return audio_i16.tobytes()


async def _kokoro_tts(text: str, voice: str, language: Optional[str]) -> PCM16Audio:
    # Kokoro commonly outputs 24kHz.
    lang_code = _lang_to_kokoro_code(language)

    def _run() -> PCM16Audio:
        pipe = _load_kokoro_pipeline(lang_code)
        # Generator yields (gs, ps, audio_np)
        audio_parts: list[np.ndarray] = []
        sr = 24000
        gen = pipe(text, voice=voice)
        for _gs, _ps, audio in gen:
            if audio is None:
                continue
            a = np.asarray(audio)
            audio_parts.append(a)
        if not audio_parts:
            return PCM16Audio(pcm16=b"", sample_rate=24000)
        full = np.concatenate(audio_parts)
        pcm16 = _float_to_pcm16(full)
        return PCM16Audio(pcm16=pcm16, sample_rate=sr)

    return await asyncio.to_thread(_run)


async def _fish_tts_http(text: str, voice: Optional[str], language: Optional[str]) -> PCM16Audio:
    """Call an OpenAI-compatible Fish Speech server.

    We intentionally do not try to run Fish-Speech Python inference inside this
    repo (it has more moving parts). Instead, run a dedicated Fish Speech server
    (e.g., fish-speech.rs) and point FISH_TTS_BASE_URL to it.
    """

    s = get_settings()
    base = (s.FISH_TTS_BASE_URL or "").rstrip("/")
    if not base:
        raise TTSError("FISH_TTS_BASE_URL is not set")

    model = s.FISH_TTS_MODEL or "fish-speech-1.5"
    api_key = s.FISH_TTS_API_KEY or ""

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model,
        "input": text,
        "voice": voice,
        "response_format": "wav",
    }
    # Some servers accept 'language' and others ignore it.
    if language:
        payload["language"] = language

    url = base + "/v1/audio/speech"
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(url, headers=headers, json=payload)
        if r.status_code >= 400:
            raise TTSError(f"Fish TTS server error: {r.status_code}: {r.text[:500]}")
        wav = r.content

    # Convert WAV -> PCM16, keep server's sample rate.
    from app.services.audio.codecs import wav_bytes_to_pcm16

    return wav_bytes_to_pcm16(wav)


async def _openai_tts(text: str, voice: Optional[str]) -> PCM16Audio:
    s = get_settings()
    base = (s.OPENAI_BASE_URL or "https://api.openai.com/v1").rstrip("/")
    api_key = s.OPENAI_API_KEY
    if not api_key:
        raise TTSError("OPENAI_API_KEY is not set")
    model = s.OPENAI_TTS_MODEL
    voice = voice or s.OPENAI_TTS_VOICE

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "input": text,
        "voice": voice,
        "response_format": "wav",
    }
    url = base + "/audio/speech"
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(url, headers=headers, json=payload)
        if r.status_code >= 400:
            raise TTSError(f"OpenAI TTS error: {r.status_code}: {r.text[:500]}")
        wav = r.content

    from app.services.audio.codecs import wav_bytes_to_pcm16

    return wav_bytes_to_pcm16(wav)


async def synthesize(
    text: str,
    provider: Optional[str] = None,
    voice: Optional[str] = None,
    language: Optional[str] = None,
    output_format: str = "g711_ulaw",
    stack_id: Optional[str] = None,
) -> bytes:
    """Synthesize audio and return bytes in output_format.

    output_format:
      - g711_ulaw (Twilio/Plivo typical)
      - g711_alaw (some SIP trunks)
      - pcm16_16k (raw 16-bit PCM at 16kHz)
    """

    s = get_settings()
    provider = (provider or s.TTS_PROVIDER or "kokoro").lower().strip()
    voice = voice or s.TTS_DEFAULT_VOICE or "af_heart"
    if not text:
        return b""

    try:
        if provider == "kokoro":
            pcm = await _kokoro_tts(text, voice=voice, language=language)
        elif provider == "fish":
            pcm = await _fish_tts_http(text, voice=voice, language=language)
        elif provider == "voicebot":
            try:
                client = VoicebotClient.from_settings()
            except Exception as e:
                raise TTSError(str(e)) from e

            sid = (stack_id or s.VOICEBOT_REMOTE_DEFAULT_STACK or "").strip()
            if not sid:
                raise TTSError("VOICEBOT_REMOTE_DEFAULT_STACK is not set and stack_id was not provided")

            # Voicebot TTS expects lang (en|hi). Derive from language if present.
            lang = "hi" if (language or "").lower().startswith("hi") else "en"
            try:
                wav = await client.synthesize(stack_id=sid, text=text, lang=lang)
            except VoicebotClientError as e:
                raise TTSError(str(e)) from e

            from app.services.audio.codecs import wav_bytes_to_pcm16

            pcm = wav_bytes_to_pcm16(wav)
        elif provider == "openai":
            pcm = await _openai_tts(text, voice=voice)
        else:
            raise HTTPException(status_code=400, detail=f"Unknown TTS provider: {provider}")
    except TTSError as e:
        logger.warning("tts_provider_error", provider=provider, error=str(e))
        raise HTTPException(status_code=500, detail=str(e)) from e

    # Normalize to PCM16 16kHz
    from app.services.audio.codecs import pcm16_resample

    pcm16_16k = pcm16_resample(pcm.pcm16, pcm.sample_rate, 16000)

    fmt = (output_format or "g711_ulaw").lower().strip()
    if fmt == "pcm16_16k":
        return pcm16_16k
    if fmt in ("g711_ulaw", "ulaw", "mulaw"):
        return pcm16_16k_to_ulaw8k(pcm16_16k)
    if fmt in ("g711_alaw", "alaw"):
        return pcm16_16k_to_alaw8k(pcm16_16k)

    raise HTTPException(status_code=400, detail=f"Unknown output_format: {output_format}")
