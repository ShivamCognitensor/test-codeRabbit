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
    """
    Transcribes a chunk of audio from common streaming encodings into text.
    
    Converts input bytes from common streaming formats (G.711 μ-law/ A-law or PCM16) to PCM16@16kHz as needed, then transcribes using the specified STT provider.
    
    Parameters:
        audio_bytes (bytes): Raw audio data in the encoding specified by `input_audio_format`.
        input_audio_format (str): Encoding of `audio_bytes`. Accepts "g711_ulaw", "ulaw", "mulaw", "g711_alaw", "alaw", "pcm16_16k", "pcm16", or other values (unknown values are treated as PCM16@16k). If falsy, defaults to "g711_ulaw".
        stt_provider (str): Identifier for the speech-to-text provider to use for transcription.
        language (Optional[str]): Optional language code to guide transcription (e.g., "en-US").
    
    Returns:
        str: The transcribed text.
    """
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
    """
    Synthesize the given text into audio bytes using the specified TTS provider and output format.
    
    Parameters:
        text (str): The text to synthesize.
        output_audio_format (str): Desired audio encoding/format for the output (e.g., PCM or compressed formats).
        tts_provider (str): Identifier of the text-to-speech provider to use.
        voice (Optional[str]): Optional voice identifier or name to use for synthesis.
        language (Optional[str]): Optional language/locale hint for the synthesis.
    
    Returns:
        bytes: Synthesized audio bytes encoded in the requested output_audio_format.
    """
    return await synthesize(
        text,
        provider=tts_provider,
        voice=voice,
        language=language,
        output_format=output_audio_format,
    )
