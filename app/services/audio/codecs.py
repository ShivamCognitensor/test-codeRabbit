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
    """
    Convert G.711 μ-law audio sampled at 8000 Hz (mono) to 16-bit PCM mono resampled to 16000 Hz.
    
    If `ulaw_bytes` is empty, returns an empty PCM16Audio with sample_rate set to 16000.
    
    Returns:
        PCM16Audio: PCM16 mono audio bytes resampled to 16000 Hz.
    """
    if not ulaw_bytes:
        return PCM16Audio(pcm16=b"", sample_rate=16000)
    # u-law -> linear PCM16 @8k
    pcm8k = audioop.ulaw2lin(ulaw_bytes, 2)
    # resample 8k -> 16k
    pcm16k, _ = audioop.ratecv(pcm8k, 2, 1, 8000, 16000, None)
    return PCM16Audio(pcm16=pcm16k, sample_rate=16000)


def alaw8k_to_pcm16_16k(alaw_bytes: bytes) -> PCM16Audio:
    """
    Convert G.711 A-law 8 kHz mono audio to PCM16 mono resampled to 16 kHz.
    
    If `alaw_bytes` is empty, returns an empty PCM16Audio with sample_rate set to 16000.
    
    Returns:
        PCM16Audio: Mono PCM16 bytes resampled to 16000 Hz; empty PCM16Audio when input is empty.
    """
    if not alaw_bytes:
        return PCM16Audio(pcm16=b"", sample_rate=16000)
    pcm8k = audioop.alaw2lin(alaw_bytes, 2)
    pcm16k, _ = audioop.ratecv(pcm8k, 2, 1, 8000, 16000, None)
    return PCM16Audio(pcm16=pcm16k, sample_rate=16000)


def pcm16_16k_to_ulaw8k(pcm16_16k: bytes) -> bytes:
    """
    Convert PCM16 audio at 16 kHz (mono) to G.711 u-law audio at 8 kHz (mono).
    
    Returns:
        bytes: G.711 u-law 8 kHz mono bytes; empty bytes if input is empty.
    """
    if not pcm16_16k:
        return b""
    # resample 16k -> 8k
    pcm8k, _ = audioop.ratecv(pcm16_16k, 2, 1, 16000, 8000, None)
    return audioop.lin2ulaw(pcm8k, 2)


def pcm16_16k_to_alaw8k(pcm16_16k: bytes) -> bytes:
    """
    Convert PCM16 mono audio at 16 kHz to G.711 A-law mono at 8 kHz.
    
    If `pcm16_16k` is empty, returns empty bytes.
    
    Returns:
        alaw_bytes (bytes): G.711 A-law encoded mono audio sampled at 8000 Hz.
    """
    if not pcm16_16k:
        return b""
    pcm8k, _ = audioop.ratecv(pcm16_16k, 2, 1, 16000, 8000, None)
    return audioop.lin2alaw(pcm8k, 2)


def pcm16_to_wav_bytes(pcm16: bytes, sample_rate: int) -> bytes:
    """
    Wrap raw PCM16 mono audio in a WAV container.
    
    Parameters:
        pcm16 (bytes): Raw PCM16 little-endian mono audio frames.
        sample_rate (int): Sample rate (Hz) to store in the WAV header.
    
    Returns:
        wav_bytes (bytes): Bytes of a valid WAV file containing the provided audio.
    """
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm16)
    return buf.getvalue()


def wav_bytes_to_pcm16(wav_bytes: bytes) -> PCM16Audio:
    """
    Convert WAV-formatted bytes into mono 16-bit PCM while preserving the WAV sample rate.
    
    Parameters:
        wav_bytes (bytes): Bytes of a WAV file.
    
    Returns:
        PCM16Audio: Mono PCM16 bytes and the WAV file's sample rate. Multi-channel input is downmixed by taking the left channel; non-16-bit sample widths are converted to 16-bit.
    """
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
    """
    Resample mono PCM16 audio from src_rate to dst_rate.
    
    Parameters:
        pcm16 (bytes): Raw PCM16 mono audio bytes.
        src_rate (int): Source sample rate in Hz.
        dst_rate (int): Destination sample rate in Hz.
    
    Returns:
        bytes: PCM16 mono audio resampled to dst_rate. If input is empty or src_rate equals dst_rate, returns the original bytes unchanged.
    """
    if not pcm16 or src_rate == dst_rate:
        return pcm16
    out, _ = audioop.ratecv(pcm16, 2, 1, int(src_rate), int(dst_rate), None)
    return out


def chunk_bytes(data: bytes, chunk_size: int) -> Tuple[bytes, ...]:
    """
    Split a bytes sequence into consecutive chunks of the specified size.
    
    Parameters:
    	data (bytes): Input bytes to split.
    	chunk_size (int): Maximum size in bytes for each chunk; the final chunk may be smaller.
    
    Returns:
    	tuple_of_chunks (Tuple[bytes, ...]): Tuple containing consecutive byte chunks; empty tuple if `data` is empty.
    """
    if not data:
        return tuple()
    return tuple(data[i : i + chunk_size] for i in range(0, len(data), chunk_size))
