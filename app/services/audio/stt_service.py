"""Speech-to-text providers.

This module is designed to be *plug-and-play*:

- Whisper v3 Turbo (via ``faster-whisper``)   implemented
- Canary Qwen 2.5B (via NVIDIA NeMo SALM)     implemented (optional dep)

If optional dependencies are missing, the provider raises a clear error telling
you what to install.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from functools import lru_cache
from typing import Optional

from fastapi import HTTPException
import httpx

from app.core.config import get_settings
from app.core.logging import get_logger
from app.clients.voicebot_client import VoicebotClient, VoicebotClientError
from app.services.audio.codecs import PCM16Audio, pcm16_to_wav_bytes

logger = get_logger(__name__)


class STTError(RuntimeError):
    pass


@lru_cache(maxsize=4)
def _load_faster_whisper(model_name: str, device: str, compute_type: str):
    """
    Load and return a configured WhisperModel from the faster-whisper package.
    
    Parameters:
        model_name (str): Identifier or path of the Whisper model to load.
        device (str): Target device for the model (e.g., "cpu" or "cuda").
        compute_type (str): Compute/precision type to use for the model.
    
    Returns:
        WhisperModel: An instance of faster_whisper.WhisperModel configured with the given model, device, and compute_type.
    
    Raises:
        STTError: If the faster-whisper package cannot be imported.
    """
    try:
        from faster_whisper import WhisperModel
    except Exception as e:
        raise STTError(
            "faster-whisper is not installed. Install requirements.models.txt (Whisper STT)."
        ) from e

    return WhisperModel(model_name, device=device, compute_type=compute_type)


@lru_cache(maxsize=2)
def _load_canary_salm(model_name: str):
    """
    Load a pretrained NVIDIA NeMo SALM (Canary) model by name.
    
    This function imports the optional NeMo dependency on demand and returns a SALM model instance.
    
    Parameters:
        model_name (str): Name or identifier of the pretrained SALM model to load.
    
    Returns:
        SALM: An instance of the loaded SALM model.
    
    Raises:
        STTError: If the NeMo toolkit is not installed.
    """
    try:
        from nemo.collections.speechlm2 import SALM  # type: ignore
    except Exception as e:
        raise STTError(
            "NeMo (nemo_toolkit) is not installed. Install requirements.canary.txt (Canary STT)."
        ) from e

    return SALM.from_pretrained(model_name)


def _device_from_env() -> str:
    # Respect CUDA_VISIBLE_DEVICES; default to CPU.
    """
    Determine whether to use "cuda" or "cpu" based on the CUDA_VISIBLE_DEVICES environment variable.
    
    Returns:
        device (str): "cuda" if CUDA_VISIBLE_DEVICES is set to a non-empty value other than "-1", otherwise "cpu".
    """
    if os.environ.get("CUDA_VISIBLE_DEVICES") not in (None, "", "-1"):
        return "cuda"
    return "cpu"


async def transcribe_pcm16(
    audio: PCM16Audio,
    provider: str,
    language: Optional[str] = None,
    stack_id: Optional[str] = None,
) -> str:
    """
    Transcribe PCM16 audio using the configured speech-to-text provider.
    
    Parameters:
        audio (PCM16Audio): Audio container with `pcm16` bytes and `sample_rate`.
        provider (str): Provider name (e.g., "whisper", "canary", "voicebot", "openai"); if falsy, resolved from settings (default "whisper").
        language (Optional[str]): Optional language hint for the transcription.
        stack_id (Optional[str]): Optional Voicebot stack identifier; used only when `provider` is "voicebot".
    
    Returns:
        str: The transcribed text (trimmed). Returns an empty string when `audio.pcm16` is falsy or no text is produced.
    
    Raises:
        STTError: For provider-specific errors, missing configuration (e.g., API keys), dependency import failures, or provider API issues.
        HTTPException: With status 400 when the specified provider is unknown.
    """
    s = get_settings()
    provider = (provider or s.STT_PROVIDER or "whisper").lower().strip()

    if not audio.pcm16:
        return ""

    if provider == "whisper":
        model_name = s.WHISPER_MODEL_NAME
        device = s.WHISPER_DEVICE or _device_from_env()
        compute_type = s.WHISPER_COMPUTE_TYPE or ("int8" if device == "cpu" else "float16")

        def _run() -> str:
            """
            Produce a single trimmed transcription string from the loaded Whisper model's segment outputs.
            
            Returns:
                str: Concatenated, trimmed text from all non-empty transcription segments; empty string if no segments were produced.
            """
            model = _load_faster_whisper(model_name, device=device, compute_type=compute_type)
            # faster-whisper works best with a WAV container.
            wav = pcm16_to_wav_bytes(audio.pcm16, sample_rate=audio.sample_rate)
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
                tmp.write(wav)
                tmp.flush()
                segments, _info = model.transcribe(tmp.name, language=language or None)
                texts = [seg.text.strip() for seg in segments if seg.text]
                return " ".join([t for t in texts if t]).strip()

        return await asyncio.to_thread(_run)

    if provider == "canary":
        model_name = s.CANARY_MODEL_NAME

        def _run_canary() -> str:
            """
            Run transcription using a loaded NeMo SALM model and return the resulting text.
            
            Returns:
                str: Transcribed text from the provided audio, trimmed.
            
            Raises:
                STTError: If the SALM instance does not expose a supported transcription API.
            """
            salm = _load_canary_salm(model_name)
            # SALM accepts WAV paths in many examples; keep it simple.
            wav = pcm16_to_wav_bytes(audio.pcm16, sample_rate=audio.sample_rate)
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
                tmp.write(wav)
                tmp.flush()
                # NeMo SALM exposes a generate/transcribe API depending on version.
                # We try a couple patterns to be robust.
                if hasattr(salm, "transcribe"):
                    out = salm.transcribe([tmp.name])  # type: ignore
                    if isinstance(out, list) and out:
                        return str(out[0]).strip()
                if hasattr(salm, "generate"):
                    out = salm.generate([tmp.name])  # type: ignore
                    if isinstance(out, list) and out:
                        return str(out[0]).strip()
                raise STTError("Canary SALM API not found. Check NeMo version / provider adapter.")

        return await asyncio.to_thread(_run_canary)
    
    if provider == "voicebot":
        try:
            client = VoicebotClient.from_settings()
        except Exception as e:
            raise STTError(str(e)) from e

        wav = pcm16_to_wav_bytes(audio.pcm16, sample_rate=audio.sample_rate)
        sid = (stack_id or s.VOICEBOT_REMOTE_DEFAULT_STACK or "").strip()
        if not sid:
            raise STTError("VOICEBOT_REMOTE_DEFAULT_STACK is not set and stack_id was not provided")

        try:
            data = await client.transcribe_wav(stack_id=sid, wav_bytes=wav, language=language)
        except VoicebotClientError as e:
            raise STTError(str(e)) from e

        return str(data.get("text") or "").strip()


    if provider == "openai":
        base = (s.OPENAI_BASE_URL or "https://api.openai.com/v1").rstrip("/")
        api_key = s.OPENAI_API_KEY
        if not api_key:
            raise STTError("OPENAI_API_KEY is not set")

        model = s.OPENAI_WHISPER_MODEL or "gpt-4o-mini-transcribe"
        wav = pcm16_to_wav_bytes(audio.pcm16, sample_rate=audio.sample_rate)

        headers = {"Authorization": f"Bearer {api_key}"}
        data = {"model": model}
        if language:
            data["language"] = language

        files = {"file": ("audio.wav", wav, "audio/wav")}
        url = base + "/audio/transcriptions"

        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(url, headers=headers, data=data, files=files)
            if r.status_code >= 400:
                raise STTError(f"OpenAI STT error: {r.status_code}: {r.text[:500]}")
            return (r.json().get("text") or "").strip()

    raise HTTPException(status_code=400, detail=f"Unknown STT provider: {provider}")
