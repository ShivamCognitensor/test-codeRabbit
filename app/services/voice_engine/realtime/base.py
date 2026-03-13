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
        """
        Establishes and initializes the realtime audio bridge using the provided configuration.
        
        Parameters:
            config (RealtimeConfig): Configuration for the realtime session including instructions, input/output audio formats, and optional voice, language, and metadata.
        """
        ...

    @abstractmethod
    async def send_audio(self, audio_bytes: bytes) -> None:
        """
        Send a chunk of audio data to the bridge for processing or transmission.
        
        Parameters:
            audio_bytes (bytes): Raw audio data encoded in the bridge's configured input_audio_format.
        """
        ...

    @abstractmethod
    async def recv_audio(self) -> AsyncIterator[bytes]:
        """
        Provide an asynchronous stream of received audio data from the bridge.
        
        Yields consecutive audio chunks encoded according to the bridge's configured output_audio_format; each yielded value is a bytes object representing a single audio frame or packet. The iterator completes when the bridge/connection is closed.
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """
        Close the realtime bridge and release any associated resources.
        
        This stops any further send or receive operations and finalizes the connection.
        """
        ...

    @property
    def transcript(self) -> list[dict[str, Any]]:
        """
        Return the transcript entries produced by the realtime bridge.
        
        Each entry is a dictionary containing transcript data (for example: text, timestamps, speaker, and optional metadata). The base implementation returns an empty list.
        
        Returns:
            list[dict[str, Any]]: A list of transcript entry dictionaries; empty if no transcript is available.
        """
        return []
