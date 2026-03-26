"""Audio codec helpers.

This repo needs to handle PSTN-friendly streaming codecs while keeping
dependencies light. We use Python's built-in ``audioop`` for:

- G.711 u-law <-> PCM16
- Sample-rate conversion (8kHz <-> 16kHz)

All conversions are mono.
"""

from __future__ import annotations

import audioop
import io
import wave
from dataclasses import dataclass
from typing import Tuple


@dataclass
class PCM16Audio:
    """A PCM16 mono audio blob."""

    pcm16: bytes
    sample_rate: int


def ulaw8k_to_pcm16_16k(ulaw_bytes: bytes) -> PCM16Audio:
    """Convert G.711 u-law 8kHz mono to PCM16 16kHz mono."""
    if not ulaw_bytes:
        return PCM16Audio(pcm16=b"", sample_rate=16000)
    # u-law -> linear PCM16 @8k
    pcm8k = audioop.ulaw2lin(ulaw_bytes, 2)
    # resample 8k -> 16k
    pcm16k, _ = audioop.ratecv(pcm8k, 2, 1, 8000, 16000, None)
    return PCM16Audio(pcm16=pcm16k, sample_rate=16000)


def alaw8k_to_pcm16_16k(alaw_bytes: bytes) -> PCM16Audio:
    """Convert G.711 A-law 8kHz mono to PCM16 16kHz mono."""
    if not alaw_bytes:
        return PCM16Audio(pcm16=b"", sample_rate=16000)
    pcm8k = audioop.alaw2lin(alaw_bytes, 2)
    pcm16k, _ = audioop.ratecv(pcm8k, 2, 1, 8000, 16000, None)
    return PCM16Audio(pcm16=pcm16k, sample_rate=16000)


def pcm16_16k_to_ulaw8k(pcm16_16k: bytes) -> bytes:
    """Convert PCM16 16kHz mono to G.711 u-law 8kHz mono."""
    if not pcm16_16k:
        return b""
    # resample 16k -> 8k
    pcm8k, _ = audioop.ratecv(pcm16_16k, 2, 1, 16000, 8000, None)
    return audioop.lin2ulaw(pcm8k, 2)


def pcm16_16k_to_alaw8k(pcm16_16k: bytes) -> bytes:
    """Convert PCM16 16kHz mono to G.711 A-law 8kHz mono."""
    if not pcm16_16k:
        return b""
    pcm8k, _ = audioop.ratecv(pcm16_16k, 2, 1, 16000, 8000, None)
    return audioop.lin2alaw(pcm8k, 2)


def pcm16_to_wav_bytes(pcm16: bytes, sample_rate: int) -> bytes:
    """Wrap raw PCM16 mono data in a WAV container."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm16)
    return buf.getvalue()


def wav_bytes_to_pcm16(wav_bytes: bytes) -> PCM16Audio:
    """Extract PCM16 mono data from WAV bytes."""
    buf = io.BytesIO(wav_bytes)
    with wave.open(buf, "rb") as wf:
        ch = wf.getnchannels()
        sw = wf.getsampwidth()
        sr = wf.getframerate()
        frames = wf.readframes(wf.getnframes())
    if ch != 1:
        # downmix by taking left channel
        frames = audioop.tomono(frames, sw, 1.0, 0.0)
    if sw != 2:
        frames = audioop.lin2lin(frames, sw, 2)
    return PCM16Audio(pcm16=frames, sample_rate=sr)


def pcm16_resample(pcm16: bytes, src_rate: int, dst_rate: int) -> bytes:
    """Resample PCM16 mono audio using audioop."""
    if not pcm16 or src_rate == dst_rate:
        return pcm16
    out, _ = audioop.ratecv(pcm16, 2, 1, int(src_rate), int(dst_rate), None)
    return out


def chunk_bytes(data: bytes, chunk_size: int) -> Tuple[bytes, ...]:
    if not data:
        return tuple()
    return tuple(data[i : i + chunk_size] for i in range(0, len(data), chunk_size))
