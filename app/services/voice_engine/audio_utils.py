from __future__ import annotations

import audioop
from typing import Tuple


def ulaw_to_pcm16(ulaw: bytes) -> bytes:
    """G.711 u-law (8-bit) to PCM16 little-endian."""
    if not ulaw:
        return b""
    return audioop.ulaw2lin(ulaw, 2)


def pcm16_to_ulaw(pcm16: bytes) -> bytes:
    """PCM16 little-endian to G.711 u-law."""
    if not pcm16:
        return b""
    return audioop.lin2ulaw(pcm16, 2)


def resample_pcm16(pcm16: bytes, src_rate: int, dst_rate: int) -> bytes:
    """Resample PCM16 mono using audioop.ratecv."""
    if not pcm16 or src_rate == dst_rate:
        return pcm16
    # state must be preserved across chunks for best quality; caller should manage state.
    converted, _state = audioop.ratecv(pcm16, 2, 1, src_rate, dst_rate, None)
    return converted
