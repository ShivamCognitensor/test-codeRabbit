"""High-level audio helpers for the local realtime gateway."""

from __future__ import annotations

from typing import Optional

from app.services.audio.codecs import PCM16Audio, ulaw8k_to_pcm16_16k, alaw8k_to_pcm16_16k
from app.services.audio.stt_service import transcribe_pcm16
from app.services.audio.tts_service import synthesize


async def transcribe_stream_chunk(
    audio_bytes: bytes,
    input_audio_format: str,
    stt_provider: str,
    language: Optional[str] = None,
) -> str:
    """Convenience wrapper for u-law/A-law streaming inputs."""
    fmt = (input_audio_format or "g711_ulaw").lower().strip()
    if fmt in ("g711_ulaw", "ulaw", "mulaw"):
        pcm = ulaw8k_to_pcm16_16k(audio_bytes)
    elif fmt in ("g711_alaw", "alaw"):
        pcm = alaw8k_to_pcm16_16k(audio_bytes)
    elif fmt in ("pcm16_16k", "pcm16"):
        pcm = PCM16Audio(pcm16=audio_bytes, sample_rate=16000)
    else:
        # assume input is already PCM16 16k
        pcm = PCM16Audio(pcm16=audio_bytes, sample_rate=16000)
    return await transcribe_pcm16(pcm, provider=stt_provider, language=language)


async def tts_to_stream_format(
    text: str,
    output_audio_format: str,
    tts_provider: str,
    voice: Optional[str] = None,
    language: Optional[str] = None,
) -> bytes:
    return await synthesize(
        text,
        provider=tts_provider,
        voice=voice,
        language=language,
        output_format=output_audio_format,
    )
