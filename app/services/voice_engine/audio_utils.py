from __future__ import annotations

import audioop
from typing import Tuple


def ulaw_to_pcm16(ulaw: bytes) -> bytes:
    """
    Convert G.711 u-law (8-bit) audio bytes to little-endian 16-bit PCM.
    
    Parameters:
    	ulaw (bytes): Input bytes containing 8-bit G.711 u-law samples.
    
    Returns:
    	pcm16 (bytes): Little-endian 16-bit PCM bytes corresponding to the input samples.
    """
    if not ulaw:
        return b""
    return audioop.ulaw2lin(ulaw, 2)


def pcm16_to_ulaw(pcm16: bytes) -> bytes:
    """
    Convert PCM16 little-endian audio to G.711 u-law encoded bytes.
    
    Returns:
    	G.711 u-law encoded `bytes` corresponding to the input PCM16 data. If `pcm16` is empty, returns empty `bytes`.
    """
    if not pcm16:
        return b""
    return audioop.lin2ulaw(pcm16, 2)


def resample_pcm16(pcm16: bytes, src_rate: int, dst_rate: int) -> bytes:
    """
    Resample mono PCM16 (little-endian) audio from one sample rate to another.
    
    Parameters:
        pcm16 (bytes): Mono PCM16 little-endian audio data.
        src_rate (int): Source sample rate in Hz.
        dst_rate (int): Destination sample rate in Hz.
    
    Returns:
        bytes: Resampled mono PCM16 little-endian audio data.
    
    Notes:
        This function does not preserve internal resampling state across calls; for multi-chunk streaming, callers should manage state externally to avoid quality artifacts.
    """
    if not pcm16 or src_rate == dst_rate:
        return pcm16
    # state must be preserved across chunks for best quality; caller should manage state.
    converted, _state = audioop.ratecv(pcm16, 2, 1, src_rate, dst_rate, None)
    return converted
