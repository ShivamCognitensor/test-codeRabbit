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
    """Transcribe a WAV file.

    Notes:
    - For PSTN streaming, use /v1/realtime and stream G.711.
    - This endpoint is for quick STT testing from the dashboard.
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
    """Generate speech.

    output_format:
      - wav (16kHz PCM)
      - g711_ulaw
      - g711_alaw
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
    """Return the currently configured audio providers."""
    s = get_settings()
    return {
        "stt_provider": s.STT_PROVIDER,
        "whisper_model": s.WHISPER_MODEL_NAME,
        "canary_model": s.CANARY_MODEL_NAME,
        "tts_provider": s.TTS_PROVIDER,
        "tts_default_voice": s.TTS_DEFAULT_VOICE,
        "fish_tts_base_url": s.FISH_TTS_BASE_URL,
    }
