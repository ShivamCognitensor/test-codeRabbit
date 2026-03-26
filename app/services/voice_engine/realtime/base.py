from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, Optional


@dataclass
class RealtimeConfig:
    instructions: str
    input_audio_format: str  # 'g711_ulaw' | 'pcm16' | 'g711_alaw'
    output_audio_format: str
    voice: Optional[str] = None
    language: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class RealtimeBridge(ABC):
    """Bidirectional audio bridge to an audio-to-audio model."""

    @abstractmethod
    async def connect(self, config: RealtimeConfig) -> None:
        ...

    @abstractmethod
    async def send_audio(self, audio_bytes: bytes) -> None:
        ...

    @abstractmethod
    async def recv_audio(self) -> AsyncIterator[bytes]:
        ...

    @abstractmethod
    async def close(self) -> None:
        ...

    @property
    def transcript(self) -> list[dict[str, Any]]:
        return []
