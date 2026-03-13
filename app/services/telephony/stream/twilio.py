from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class TwilioStartInfo:
    call_sid: Optional[str]
    stream_sid: Optional[str]
    custom_parameters: Dict[str, Any]


def parse_twilio_message(msg: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
    """
    Extract the event type from a Twilio message and return it with the original message.
    
    Parameters:
        msg (Dict[str, Any]): The Twilio message dictionary.
    
    Returns:
        tuple: A pair where the first element is the lowercased value of the message's "event" key (empty string if missing) and the second element is the original message dictionary.
    """
    et = (msg.get("event") or "").lower()
    return et, msg


def parse_twilio_start(msg: Dict[str, Any]) -> TwilioStartInfo:
    """
    Extract Twilio "start" payload and normalize it into a TwilioStartInfo.
    
    Parameters:
        msg (Dict[str, Any]): Twilio event message that may contain a "start" mapping.
    
    Returns:
        TwilioStartInfo: Dataclass with:
            - call_sid: value from `start["callSid"]` or `start["call_sid"]`, or `None` if absent.
            - stream_sid: value from `start["streamSid"]` or `start["stream_sid"]`, or `None` if absent.
            - custom_parameters: value from `start["customParameters"]` or `start["custom_parameters"]`, or an empty dict if absent.
    """
    start = msg.get("start") or {}
    return TwilioStartInfo(
        call_sid=start.get("callSid") or start.get("call_sid"),
        stream_sid=start.get("streamSid") or start.get("stream_sid"),
        custom_parameters=start.get("customParameters") or start.get("custom_parameters") or {},
    )


def parse_twilio_media(msg: Dict[str, Any]) -> bytes:
    """
    Decode the base64-encoded media payload from a Twilio stream message.
    
    Parameters:
        msg (Dict[str, Any]): Twilio message dictionary expected to contain a "media" mapping with an optional "payload" string.
    
    Returns:
        bytes: The decoded bytes of the "payload" field, or b"" if the payload is missing or empty.
    """
    media = msg.get("media") or {}
    payload = media.get("payload") or ""
    if not payload:
        return b""
    return base64.b64decode(payload)


def build_twilio_outgoing_media(stream_sid: str, audio_bytes: bytes) -> str:
    """
    Constructs a Twilio "media" event JSON message containing the given audio.
    
    Parameters:
        stream_sid (str): Twilio stream identifier to include as `streamSid`.
        audio_bytes (bytes): Raw audio bytes to be base64-encoded as the media payload.
    
    Returns:
        json_message (str): JSON-formatted string with keys `event` ("media"), `streamSid`, and `media.payload` containing the base64-encoded audio.
    """
    payload = base64.b64encode(audio_bytes).decode("ascii")
    out = {"event": "media", "streamSid": stream_sid, "media": {"payload": payload}}
    import json
    return json.dumps(out)
