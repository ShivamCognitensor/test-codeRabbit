from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class PlivoStartInfo:
    call_uuid: Optional[str]
    stream_id: Optional[str]
    custom_parameters: Dict[str, Any]


def parse_plivo_message(msg: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
    """
    Extracts the event type from a Plivo message and returns it alongside the original message.
    
    Parameters:
        msg (Dict[str, Any]): Plivo webhook message dictionary.
    
    Returns:
        tuple[str, Dict[str, Any]]: A tuple where the first element is the lowercased event string (empty string if the message has no "event" key) and the second element is the original message dictionary.
    """
    et = (msg.get("event") or "").lower()
    return et, msg


def parse_plivo_start(msg: Dict[str, Any]) -> PlivoStartInfo:
    """
    Normalize a Plivo "start" message and extract start-related fields into a PlivoStartInfo.
    
    Parameters:
        msg (dict): Plivo message dictionary expected to contain an optional "start" mapping. The "start" mapping may include "callUuid" or "call_uuid", "streamId" or "stream_id", and "customParameters" or "custom_parameters".
    
    Returns:
        PlivoStartInfo: Dataclass with `call_uuid`, `stream_id`, and `custom_parameters` extracted from the message (missing values set to None or an empty dict).
    """
    start = msg.get("start") or {}
    return PlivoStartInfo(
        call_uuid=start.get("callUuid") or start.get("call_uuid"),
        stream_id=start.get("streamId") or start.get("stream_id"),
        custom_parameters=start.get("customParameters") or start.get("custom_parameters") or {},
    )


def parse_plivo_media(msg: Dict[str, Any]) -> bytes:
    """
    Decode and return the base64-encoded media payload from a Plivo message.
    
    Parameters:
        msg (Dict[str, Any]): Plivo message dictionary expected to contain a "media" mapping with a "payload" base64 string.
    
    Returns:
        bytes: The decoded media bytes. Returns empty bytes if the "payload" is missing or empty.
    """
    media = msg.get("media") or {}
    payload = media.get("payload") or ""
    if not payload:
        return b""
    return base64.b64decode(payload)


def build_plivo_outgoing_audio(audio_bytes: bytes, content_type: str = "audio/x-mulaw", sample_rate: int = 8000) -> str:
    """
    Builds a JSON string for a Plivo "playAudio" outgoing event containing base64-encoded audio.
    
    Parameters:
        audio_bytes (bytes): Raw audio bytes to be encoded into the event payload.
        content_type (str): MIME type to include as `contentType` for the media (e.g., "audio/x-mulaw").
        sample_rate (int): Sample rate in Hz to include as `sampleRate` for the media.
    
    Returns:
        json_str (str): JSON-formatted string representing a Plivo `playAudio` event with `media` containing `contentType`, `sampleRate`, and a base64 `payload`.
    """
    payload = base64.b64encode(audio_bytes).decode("ascii")
    out = {
        "event": "playAudio",
        "media": {
            "contentType": content_type,
            "sampleRate": sample_rate,
            "payload": payload,
        },
    }
    import json
    return json.dumps(out)
