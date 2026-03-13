"""STT/TTS utility endpoints.

These endpoints are helpful for validating and demoing open-source voice stacks.
They are separate from the telephony gateway.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from app.core.config import get_settings
from app.services.audio.codecs import wav_bytes_to_pcm16
from app.services.audio.stt_service import transcribe_pcm16
from app.services.audio.tts_service import synthesize


router = APIRouter(prefix="/api/v1/audio", tags=["audio"])


@router.post("/transcribe")
async def transcribe_audio(
    file: UploadFile = File(...),
    provider: Optional[str] = Form(default=None),
    language: Optional[str] = Form(default=None),
):
    """
    Transcribe an uploaded WAV audio file to text.
    
    Optional `provider` overrides the configured STT provider. `language` is an optional language hint (e.g., "en", "es"). 
    
    Returns:
        dict: A dictionary with key "text" containing the transcribed text.
    """
    if not file.filename or not file.filename.lower().endswith(".wav"):
        raise HTTPException(status_code=400, detail="Only .wav is supported")
    data = await file.read()
    pcm = wav_bytes_to_pcm16(data)
    text = await transcribe_pcm16(pcm, provider=provider or get_settings().STT_PROVIDER, language=language)
    return {"text": text}


@router.post("/speak")
async def speak(
    text: str = Form(...),
    provider: Optional[str] = Form(default=None),
    voice: Optional[str] = Form(default=None),
    language: Optional[str] = Form(default=None),
    output_format: str = Form(default="wav"),
):
    """
    Synthesize speech from the provided text and return an HTTP response containing the resulting audio.
    
    Parameters:
        text (str): Text to synthesize; must be non-empty.
        provider (Optional[str]): Optional override for the TTS provider; when omitted the default provider from settings is used.
        voice (Optional[str]): Optional voice identifier to use for synthesis.
        language (Optional[str]): Optional language or locale hint for synthesis.
        output_format (str): Desired output format. Supported values:
            - "wav": 16 kHz PCM input converted to a WAV file (returned with media_type "audio/wav").
            - other values (e.g., "g711_ulaw", "g711_alaw"): returned as raw audio bytes with media_type "application/octet-stream".
    
    Returns:
        Response: An HTTP response whose body is the synthesized audio bytes. For "wav", the response contains WAV data sampled at 16 kHz; for other formats, the response contains the raw audio bytes.
    
    Raises:
        HTTPException: If `text` is empty (HTTP 400).
    """
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    s = get_settings()
    out_fmt = output_format.lower().strip()
    if out_fmt == "wav":
        pcm16_16k = await synthesize(
            text,
            provider=provider or s.TTS_PROVIDER,
            voice=voice,
            language=language,
            output_format="pcm16_16k",
        )
        from app.services.audio.codecs import pcm16_to_wav_bytes

        wav = pcm16_to_wav_bytes(pcm16_16k, sample_rate=16000)
        return Response(content=wav, media_type="audio/wav")

    audio_bytes = await synthesize(
        text,
        provider=provider or s.TTS_PROVIDER,
        voice=voice,
        language=language,
        output_format=out_fmt,
    )
    return Response(content=audio_bytes, media_type="application/octet-stream")


@router.get("/config")
async def audio_config():
    """
    Get the current audio STT/TTS configuration.
    
    Returns:
        dict: Mapping with keys:
            stt_provider (str): Configured speech-to-text provider name.
            whisper_model (str): Configured Whisper model name.
            canary_model (str): Configured canary model name.
            tts_provider (str): Configured text-to-speech provider name.
            tts_default_voice (str): Default voice identifier for TTS.
            fish_tts_base_url (str): Base URL for Fish TTS service (if configured).
    """
    s = get_settings()
    return {
        "stt_provider": s.STT_PROVIDER,
        "whisper_model": s.WHISPER_MODEL_NAME,
        "canary_model": s.CANARY_MODEL_NAME,
        "tts_provider": s.TTS_PROVIDER,
        "tts_default_voice": s.TTS_DEFAULT_VOICE,
        "fish_tts_base_url": s.FISH_TTS_BASE_URL,
    }
