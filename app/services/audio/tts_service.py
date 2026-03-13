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
    """
    Map an optional language tag to Kokoro's single-letter language code.
    
    Parameters:
        language (Optional[str]): Language tag or code (for example "en", "hi", "es"). If provided, the function matches on the tag's initial characters to choose a Kokoro language code.
    
    Returns:
        str: A single-letter Kokoro language code: `'h'` for Hindi (tags starting with "hi"), `'a'` for English (tags starting with "en" or default), `'e'` for Spanish ("es"), `'f'` for French ("fr"), `'i'` for Italian ("it"), and `'p'` for Portuguese ("pt").
    """
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
    """
    Load and return a Kokoro KPipeline configured for the given language code.
    
    Parameters:
        lang_code (str): Single-letter language code understood by Kokoro (e.g., 'a' for English).
    
    Returns:
        KPipeline: An instance of Kokoro's KPipeline configured with `lang_code`.
    
    Raises:
        TTSError: If the Kokoro package cannot be imported (not installed).
    """
    try:
        from kokoro import KPipeline  # type: ignore
    except Exception as e:
        raise TTSError("kokoro is not installed. Install requirements.models.txt (Kokoro TTS).") from e
    return KPipeline(lang_code=lang_code)


def _float_to_pcm16(audio_f: np.ndarray) -> bytes:
    """
    Convert a NumPy floating-point audio waveform to 16-bit PCM bytes.
    
    Parameters:
        audio_f (np.ndarray): Array of audio samples (float values, typically in the range -1.0 to 1.0). Any dtype is accepted; values outside [-1.0, 1.0] will be clamped.
    
    Returns:
        bytes: Little-endian signed 16-bit PCM samples corresponding to the input waveform.
    """
    if audio_f.dtype != np.float32:
        audio_f = audio_f.astype(np.float32)
    audio_f = np.clip(audio_f, -1.0, 1.0)
    audio_i16 = (audio_f * 32767.0).astype(np.int16)
    return audio_i16.tobytes()


async def _kokoro_tts(text: str, voice: str, language: Optional[str]) -> PCM16Audio:
    # Kokoro commonly outputs 24kHz.
    """
    Synthesize speech with Kokoro and return PCM16 audio sampled at 24000 Hz.
    
    Parameters:
    	language (Optional[str]): Language hint used to select Kokoro's pipeline (may be None).
    
    Returns:
    	PCM16Audio: PCM16 audio bytes and sample rate (24000). If the synth produced no audio, `pcm16` will be empty.
    """
    lang_code = _lang_to_kokoro_code(language)

    def _run() -> PCM16Audio:
        """
        Synthesize speech with the loaded Kokoro pipeline, concatenate streamed float chunks, and convert the result to PCM16 at 24 kHz.
        
        If the pipeline yields no audio chunks, returns an empty PCM16 payload with a 24000 Hz sample rate.
        
        Returns:
            PCM16Audio: Object containing `pcm16` bytes of the synthesized audio and `sample_rate` (24000).
        """
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
    """
    Synthesize speech by calling an OpenAI-compatible Fish Speech HTTP server.
    
    Sends a JSON request to the server's /v1/audio/speech endpoint using the
    FISH_TTS_BASE_URL setting. Uses FISH_TTS_MODEL (default "fish-speech-1.5")
    and FISH_TTS_API_KEY (optional) from settings. Includes the provided text,
    optional voice, and optional language in the request and requests a WAV
    response, which is converted to PCM16 while preserving the server's sample
    rate.
    
    Parameters:
        text (str): The input text to synthesize.
        voice (Optional[str]): Optional voice identifier to request from the server.
        language (Optional[str]): Optional language code to include in the request.
    
    Returns:
        PCM16Audio: PCM16 audio bytes and the sample rate as reported by the server.
    
    Raises:
        TTSError: If FISH_TTS_BASE_URL is not configured or the Fish Speech server
            returns an HTTP error (status code >= 400).
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
    """
    Synthesize speech using OpenAI's TTS endpoint and return PCM16 audio.
    
    Parameters:
        text (str): Input text to synthesize.
        voice (Optional[str]): Voice identifier to use; if None, the default from settings is used.
    
    Returns:
        PCM16Audio: PCM16 bytes and the source sample rate extracted from the returned WAV.
    
    Raises:
        TTSError: If OPENAI_API_KEY is not set or if the OpenAI TTS request fails.
    """
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
    """
    Synthesize speech for the given text using the chosen provider and return the resulting audio as encoded bytes.
    
    Parameters:
        text (str): Text to synthesize.
        provider (Optional[str]): TTS backend to use; one of "kokoro", "fish", "voicebot", or "openai". Defaults to module/settings default ("kokoro" if unset).
        voice (Optional[str]): Voice identifier to request from the provider; falls back to the module/settings default.
        language (Optional[str]): Language hint for the provider (e.g., "en", "hi"); used by certain providers to select language or pipeline.
        output_format (str): Desired output encoding. Supported values:
            - "pcm16_16k": raw 16-bit PCM at 16 kHz
            - "g711_ulaw", "ulaw", "mulaw": G.711 mu-law (8 kHz)
            - "g711_alaw", "alaw": G.711 A-law (8 kHz)
          Defaults to "g711_ulaw".
        stack_id (Optional[str]): Remote stack identifier required when provider is "voicebot"; if omitted the VOICEBOT_REMOTE_DEFAULT_STACK setting is used.
    
    Returns:
        bytes: Audio data encoded according to `output_format` (PCM16 or G.711).
    
    Raises:
        HTTPException: On unknown provider or unknown output_format, or when a provider-specific error or misconfiguration occurs.
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
