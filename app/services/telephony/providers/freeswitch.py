from __future__ import annotations

"""FreeSWITCH telephony provider.

This provider uses the FreeSWITCH Event Socket (ESL, typically TCP/8021)
to originate outbound calls.

For real-time audio bridging, pair it with one of these FreeSWITCH modules:
 - **mod_audio_stream** (recommended): `uuid_audio_stream ... start wss://...`.
 - **mod_twilio_stream**: can stream Twilio-compatible WebSocket messages.

Notes:
 - FreeSWITCH-side dialplan and SIP gateway setup are required. See SPEC.md.
 - We keep the provider implementation deliberately small and dependency-free
   (no `python-ESL` binding required).
"""

import asyncio
import json
from dataclasses import dataclass
from typing import Optional
from uuid import uuid4

from app.core.config import settings
from app.services.telephony.base import TelephonyProvider
from app.services.telephony.types import OutboundCallRequest, ProviderCallInfo


@dataclass
class _ESLResponse:
    raw: str

    @property
    def ok(self) -> bool:
        """
        Indicates whether the ESL response signals success.
        
        Returns:
            bool: `True` if the raw response contains the substring "+OK", `False` otherwise.
        """
        return "+OK" in self.raw


class _ESLClient:
    """Minimal ESL client (inbound mode) using asyncio streams."""

    def __init__(self, host: str, port: int, password: str, timeout: float = 5.0):
        """
        Initialize the minimal ESL client with connection details for FreeSWITCH Event Socket.
        
        Parameters:
            host (str): ESL host address or IP.
            port (int): ESL TCP port.
            password (str): Password for authenticating to the ESL server.
            timeout (float): Connection and read timeout in seconds (default 5.0).
        """
        self.host = host
        self.port = port
        self.password = password
        self.timeout = timeout
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None

    async def __aenter__(self) -> "_ESLClient":
        """
        Establish a TCP connection to the configured ESL host/port and authenticate, returning the authenticated client.
        
        Returns:
            _ESLClient: The connected and authenticated client instance (`self`).
        
        Raises:
            RuntimeError: If FreeSWITCH ESL authentication fails.
        """
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port), timeout=self.timeout
        )

        # Read auth/request headers
        await self._read_until_blank_line()
        await self._send_cmd(f"auth {self.password}")
        resp = await self._read_reply()
        if not resp.ok:
            raise RuntimeError(f"FreeSWITCH ESL auth failed: {resp.raw.strip()}")
        return self

    async def __aexit__(self, exc_type, exc, tb):
        """
        Close the ESL asyncio streams and clear client resources when exiting the async context.
        
        Closes the writer stream if it exists and awaits its closure, then clears the reader and writer references regardless of errors. Any exception information provided by the async context manager is accepted but ignored by this method.
        
        Parameters:
            exc_type (type | None): Exception type forwarded by the async context manager; ignored.
            exc (Exception | None): Exception instance forwarded by the async context manager; ignored.
            tb (traceback | None): Traceback object forwarded by the async context manager; ignored.
        """
        try:
            if self._writer:
                self._writer.close()
                await self._writer.wait_closed()
        finally:
            self._reader = None
            self._writer = None

    async def api(self, command: str) -> _ESLResponse:
        """
        Send an ESL API command and return the parsed reply.
        
        Parameters:
            command (str): The ESL API command to execute (the text after the "api" keyword).
        
        Returns:
            _ESLResponse: Parsed ESL reply containing the response headers and body; use its `ok` property to check for a "+OK" result.
        """
        await self._send_cmd(f"api {command}")
        return await self._read_reply()

    async def _send_cmd(self, line: str) -> None:
        """
        Send a single ESL command line to the connected FreeSWITCH server.
        
        Parameters:
            line (str): Command text to send; may omit ESL line terminators — a terminating blank line is appended automatically.
        """
        assert self._writer is not None
        self._writer.write((line + "\n\n").encode("utf-8"))
        await self._writer.drain()

    async def _read_until_blank_line(self) -> str:
        """
        Read lines from the internal asyncio StreamReader until a blank line is encountered and return the concatenated text.
        
        Reads using self._reader with self.timeout for each readline call. If the stream ends before a blank line is seen, returns the text read so far; if a read times out, asyncio.TimeoutError is raised.
        
        Returns:
            str: Concatenation of all non-blank lines (including their original line endings) read before the first blank line or EOF.
        """
        assert self._reader is not None
        buf = []
        while True:
            line = await asyncio.wait_for(self._reader.readline(), timeout=self.timeout)
            if not line:
                break
            s = line.decode("utf-8", errors="ignore")
            if s in {"\n", "\r\n"}:
                break
            buf.append(s)
        return "".join(buf)

    async def _read_reply(self) -> _ESLResponse:
        """
        Read a full ESL reply by consuming headers and, if present, a body indicated by Content-Length.
        
        Reads lines until a blank line to form headers, extracts an integer Content-Length header if present (falls back to 0 on parse failure), then reads exactly that many bytes for the body and decodes it using UTF-8 (errors ignored). 
        
        Returns:
            _ESLResponse: An object whose `raw` attribute contains the headers, a single newline, and the decoded body (empty string if no body).
        """
        assert self._reader is not None

        headers = await self._read_until_blank_line()
        content_length = 0
        for h in headers.splitlines():
            if h.lower().startswith("content-length:"):
                try:
                    content_length = int(h.split(":", 1)[1].strip())
                except Exception:
                    content_length = 0
                break

        body = ""
        if content_length > 0:
            data = await asyncio.wait_for(self._reader.readexactly(content_length), timeout=self.timeout)
            body = data.decode("utf-8", errors="ignore")
        return _ESLResponse(raw=(headers + "\n" + body))


class FreeSwitchProvider(TelephonyProvider):
    name = "freeswitch"

    @property
    def is_enabled(self) -> bool:
        """
        Indicates whether the FreeSWITCH ESL provider is configured.
        
        Returns:
            bool: `True` if both `FREESWITCH_ESL_HOST` and `FREESWITCH_ESL_PASSWORD` are set in settings, `False` otherwise.
        """
        return bool(settings.FREESWITCH_ESL_HOST and settings.FREESWITCH_ESL_PASSWORD)

    async def start_outbound_call(self, req: OutboundCallRequest) -> ProviderCallInfo:
        """
        Initiates an outbound call through FreeSWITCH via ESL originate and returns provider call information.
        
        Builds a dial string (from req.variables["dial_string"] or by using FREESWITCH_SIP_GATEWAY / FREESWITCH_SOFIA_PROFILE), constructs a WebSocket URL for media streaming, assembles metadata (including a deterministic call_id), and issues an ESL "originate" command that starts an audio stream on answer. Raises RuntimeError if the provider is not configured, TELEPHONY_PUBLIC_WS_BASE is not set, or the originate command fails.
        
        Parameters:
            req (OutboundCallRequest): Outbound call request containing destination/source phone numbers and optional variables and identifiers.
        
        Returns:
            ProviderCallInfo: Information about the initiated call including:
                - provider: the provider name ("freeswitch")
                - provider_call_id: parsed FreeSWITCH call UUID if found, otherwise "unknown"
                - to_phone: destination phone number from the request
                - from_phone: caller ID phone number from the request
                - metadata: map of metadata sent with the call (includes call_id and any provided variables)
        """
        if not self.is_enabled:
            raise RuntimeError("FreeSWITCH provider is not configured (set FREESWITCH_ESL_HOST and FREESWITCH_ESL_PASSWORD)")

        # Determine dial string
        dial_string = None
        if req.variables and isinstance(req.variables, dict):
            dial_string = req.variables.get("dial_string")
        if not dial_string:
            gw = settings.FREESWITCH_SIP_GATEWAY
            profile = settings.FREESWITCH_SOFIA_PROFILE
            if gw:
                dial_string = f"sofia/gateway/{gw}/{req.to_phone}"
            else:
                # direct endpoint (e.g., a SIP extension or external number through profile)
                dial_string = f"sofia/{profile}/{req.to_phone}"

        # Where FreeSWITCH should stream media
        ws_base = settings.TELEPHONY_PUBLIC_WS_BASE or ""
        if not ws_base:
            raise RuntimeError("Set TELEPHONY_PUBLIC_WS_BASE so FreeSWITCH can reach your WebSocket endpoint")

        # WebSocket endpoint for mod_audio_stream (recommended)
        ws_url = f"{ws_base.rstrip('/')}/api/v1/telephony/freeswitch/ws"

        metadata = {
            "provider": "freeswitch",
            "call_id": None,
            "agent_profile_id": str(req.agent_profile_id) if req.agent_profile_id else None,
            "campaign_id": str(req.campaign_id) if req.campaign_id else None,
            "campaign_contact_id": str(req.campaign_contact_id) if req.campaign_contact_id else None,
            "variables": req.variables or {},
        }
        metadata = {k: v for k, v in metadata.items() if v is not None}
        meta_txt = json.dumps(metadata, ensure_ascii=False)

        # Create a deterministic call id for tracking across systems
        call_id = str(uuid4())
        metadata["call_id"] = call_id
        meta_txt = json.dumps(metadata, ensure_ascii=False)

        # Start WS stream on answer.
        # See mod_audio_stream API: uuid_audio_stream <uuid> start <wss-url> <mix-type> <sampling-rate> <metadata>
        mix = "mono"
        sr = "16k" if int(settings.FREESWITCH_STREAM_SAMPLE_RATE) >= 16000 else "8k"
        on_answer = f"uuid_audio_stream ${{uuid}} start {ws_url} {mix} {sr} {meta_txt}"

        # Some useful vars for commercial edition (ignored by community edition)
        vars_ = {
            "origination_uuid": call_id,
            "origination_caller_id_number": req.from_phone or "",
            "api_on_answer": on_answer,
            "STREAM_SAMPLE_RATE": str(int(settings.FREESWITCH_STREAM_SAMPLE_RATE)),
            "STREAM_PLAYBACK": "true",
        }
        # Build originate vars string: {k=v,k2=v2}
        var_str = "{" + ",".join(f"{k}={v}" for k, v in vars_.items() if v != "") + "}"
        command = f"originate {var_str}{dial_string} &park()"

        async with _ESLClient(
            host=str(settings.FREESWITCH_ESL_HOST),
            port=int(settings.FREESWITCH_ESL_PORT),
            password=str(settings.FREESWITCH_ESL_PASSWORD),
        ) as esl:
            resp = await esl.api(command)
            if not resp.ok:
                raise RuntimeError(f"FreeSWITCH originate failed: {resp.raw.strip()}")

        # FreeSWITCH API returns +OK <uuid> (usually). Parse best-effort.
        provider_call_id = "unknown"
        for token in resp.raw.split():
            if len(token) >= 20 and "-" in token:
                provider_call_id = token
                break

        return ProviderCallInfo(
            provider=self.name,
            provider_call_id=provider_call_id,
            to_phone=req.to_phone,
            from_phone=req.from_phone,
            metadata=metadata,
        )
