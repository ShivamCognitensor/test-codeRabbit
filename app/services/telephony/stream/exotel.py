from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class ExotelStartInfo:
    call_sid: Optional[str]
    stream_sid: Optional[str]
    custom_parameters: Dict[str, Any]


def parse_exotel_message(msg: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
    """
    Extracts the event type from an Exotel message and returns it alongside the original message.
    
    Parameters:
        msg (Dict[str, Any]): Incoming Exotel message dictionary.
    
    Returns:
        tuple[event, msg]: `event` is the lowercased value from `msg["event"]` or `msg["type"]`, or an empty string if neither is present; `msg` is the original message dict.
    """
    et = (msg.get("event") or msg.get("type") or "").lower()
    return et, msg


def parse_exotel_start(msg: Dict[str, Any]) -> ExotelStartInfo:
    """
    Extracts Exotel start information from a message.
    
    Parameters:
        msg (Dict[str, Any]): Incoming Exotel event or payload; may be the whole message or contain a 'start' or 'data' subobject.
    
    Returns:
        ExotelStartInfo: Dataclass with:
            - call_sid: the call identifier if present (from 'callSid', 'call_sid', or 'CallSid'), otherwise None.
            - stream_sid: the stream identifier if present (from 'streamSid', 'stream_sid', or 'StreamSid'), otherwise None.
            - custom_parameters: a dictionary of custom parameters (from 'customParameters' or 'custom_parameters'), empty if none found.
    """
    start = msg.get("start") or msg.get("data") or msg
    return ExotelStartInfo(
        call_sid=start.get("callSid") or start.get("call_sid") or start.get("CallSid"),
        stream_sid=start.get("streamSid") or start.get("stream_sid") or start.get("StreamSid"),
        custom_parameters=start.get("customParameters") or start.get("custom_parameters") or {},
    )


def parse_exotel_media(msg: Dict[str, Any]) -> bytes:
    """
    Extracts and returns decoded audio bytes from an Exotel media message.
    
    Looks for a media envelope under the top-level "media" or "data" keys, then for a base64 payload under "payload" or "audio". If a payload is present it is base64-decoded and returned; if not, empty bytes are returned.
    
    Parameters:
        msg (Dict[str, Any]): Incoming Exotel message containing media/data.
    
    Returns:
        bytes: Decoded audio bytes from the message payload, or b"" if no payload is present.
    """
    media = msg.get("media") or msg.get("data") or {}
    payload = media.get("payload") or media.get("audio") or ""
    if not payload:
        return b""
    return base64.b64decode(payload)


def build_exotel_outgoing_audio(audio_bytes: bytes, encoding: str = "audio/x-mulaw", sample_rate: int = 8000) -> str:
    """
    Build a JSON string instructing Exotel to play the provided audio.
    
    Parameters:
        audio_bytes (bytes): Raw audio data to be sent.
        encoding (str): MIME encoding label included in the media envelope (e.g., "audio/x-mulaw").
        sample_rate (int): Sample rate included in the media envelope.
    
    Returns:
        str: JSON string with an "event" of "playAudio" and a "media" object containing `encoding`, `sampleRate`, and a base64-encoded `payload` of `audio_bytes`.
    """
    payload = base64.b64encode(audio_bytes).decode("ascii")
    out = {"event": "playAudio", "media": {"encoding": encoding, "sampleRate": sample_rate, "payload": payload}}
    import json
    return json.dumps(out)
