"""
WebTransport → WebSocket Proxy Server
======================================

Architecture:
    Browser ──(QUIC/HTTP3)──► aioquic server :4433
                                    │
                            [StreamBridge per session]
                                    │
                         ──(WebSocket)──► SFU :4443

Purpose:
    Accept WebTransport sessions from browsers and transparently proxy
    the signaling JSON messages to the existing mediasoup SFU server
    over WebSocket. The SFU receives identical JSON it always received —
    nothing changes on that side.

Message framing:
    WebTransport streams are byte streams, not message streams.
    We use newline-delimited JSON (NDJSON): each JSON message ends with \\n.
    The aioquic side buffers incoming bytes, splits on \\n, and forwards
    each complete line to the SFU WebSocket (and vice-versa).

TLS:
    WebTransport requires HTTPS (TLS 1.3 minimum).
    For local dev: generate a self-signed cert with generate_cert.py.
    For production: use a cert signed by a trusted CA (e.g. Let's Encrypt).

Environment variables:
    SFU_WS_URL          WebSocket URL of the SFU  (default: ws://sfu:4443)
    WT_HOST             Listen host               (default: 0.0.0.0)
    WT_PORT             Listen UDP port           (default: 4433)
    CERT_FILE           TLS certificate path      (default: certs/cert.pem)
    KEY_FILE            TLS private key path      (default: certs/key.pem)
    LOG_LEVEL           Logging level             (default: INFO)
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import ssl
import sys
from collections import defaultdict

import websockets
from aioquic.asyncio import serve
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.h3.connection import H3Connection, H3_ALPN
from aioquic.h3.events import (
    H3Event,
    HeadersReceived,
    WebTransportStreamDataReceived,
)
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import QuicEvent

# ─── Configuration ────────────────────────────────────────────────────────────

SFU_WS_URL = os.environ.get("SFU_WS_URL", "ws://sfu:4443")
WT_HOST    = os.environ.get("WT_HOST",    "0.0.0.0")
WT_PORT    = int(os.environ.get("WT_PORT", "4433"))
CERT_FILE  = os.environ.get("CERT_FILE",  "certs/cert.pem")
KEY_FILE   = os.environ.get("KEY_FILE",   "certs/key.pem")
LOG_LEVEL  = os.environ.get("LOG_LEVEL",  "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("wt-proxy")


# ─── Stream Bridge ─────────────────────────────────────────────────────────────

class StreamBridge:
    """
    Bridges one WebTransport bidirectional stream ↔ one SFU WebSocket connection.

    Data flow:
        browser → [QUIC stream chunks] → receive_from_browser()
                                              │ line buffer + split on \\n
                                              ▼
                                        _to_sfu queue
                                              │ _browser_to_sfu coroutine
                                              ▼
                                      ws.send(json_line)

        sfu     → [WebSocket message] → _sfu_to_browser coroutine
                                              │ json_line + \\n
                                              ▼
                                     protocol.send_stream_data()
    """

    def __init__(
        self,
        session_id: int,
        stream_id: int,
        protocol: "SfuBridgeProtocol",
    ) -> None:
        self.session_id = session_id
        self.stream_id  = stream_id
        self.protocol   = protocol

        self._to_sfu: asyncio.Queue[str | None] = asyncio.Queue(maxsize=200)
        self._line_buf = b""

    async def run(self) -> None:
        """Connect to the SFU and bridge traffic until either side closes."""
        logger.info("[Session %s] Connecting to SFU at %s", self.session_id, SFU_WS_URL)
        try:
            async with websockets.connect(SFU_WS_URL, max_size=2**20) as ws:
                logger.info("[Session %s] SFU WebSocket connected", self.session_id)
                await asyncio.gather(
                    self._sfu_to_browser(ws),
                    self._browser_to_sfu(ws),
                )
        except websockets.exceptions.ConnectionClosedOK:
            logger.info("[Session %s] SFU closed cleanly", self.session_id)
        except Exception as exc:
            logger.warning("[Session %s] Bridge error: %s", self.session_id, exc)
        finally:
            # Signal the browser-to-SFU coroutine to stop
            self._to_sfu.put_nowait(None)
            logger.info("[Session %s] Bridge closed", self.session_id)

    async def _sfu_to_browser(self, ws: websockets.WebSocketClientProtocol) -> None:
        """Forward messages from the SFU WebSocket to the browser stream."""
        async for message in ws:
            raw: bytes = (
                message.encode("utf-8") if isinstance(message, str) else message
            )
            # Ensure the message is newline-terminated before sending downstream
            if not raw.endswith(b"\n"):
                raw = raw + b"\n"
            self.protocol.send_to_stream(self.session_id, self.stream_id, raw)

    async def _browser_to_sfu(self, ws: websockets.WebSocketClientProtocol) -> None:
        """Forward JSON lines from the browser queue to the SFU WebSocket."""
        while True:
            line = await self._to_sfu.get()
            if line is None:
                break
            try:
                await ws.send(line)
            except websockets.exceptions.ConnectionClosed:
                logger.info("[Session %s] SFU connection closed while sending", self.session_id)
                break

    def receive_from_browser(self, data: bytes, ended: bool) -> None:
        """
        Called by the QUIC protocol handler when stream data arrives.
        Accumulates bytes, splits on newline, enqueues complete JSON lines.
        """
        self._line_buf += data
        lines = self._line_buf.split(b"\n")
        self._line_buf = lines[-1]  # keep partial trailing line

        for raw_line in lines[:-1]:
            stripped = raw_line.strip()
            if not stripped:
                continue
            try:
                text = stripped.decode("utf-8")
                self._to_sfu.put_nowait(text)
            except (UnicodeDecodeError, asyncio.QueueFull) as exc:
                logger.warning(
                    "[Session %s] Dropped browser message: %s", self.session_id, exc
                )

        if ended:
            self._to_sfu.put_nowait(None)


# ─── QUIC Protocol ─────────────────────────────────────────────────────────────

class SfuBridgeProtocol(QuicConnectionProtocol):
    """
    Handles all QUIC/HTTP3 events for a single browser connection.

    - Accepts incoming WebTransport CONNECT requests.
    - Spawns a StreamBridge task for each accepted session.
    - Routes WebTransportStreamDataReceived events to the correct bridge.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._h3: H3Connection | None = None
        # session_id (CONNECT stream) → StreamBridge
        self._bridges: dict[int, StreamBridge] = {}
        # session_id → asyncio.Task running the bridge
        self._tasks: dict[int, asyncio.Task] = {}

    # ── QuicConnectionProtocol override ──────────────────────────────────────

    def quic_event_received(self, event: QuicEvent) -> None:
        if self._h3 is None:
            self._h3 = H3Connection(self._quic, enable_webtransport=True)

        for h3_event in self._h3.handle_event(event):
            self._dispatch_h3_event(h3_event)

    # ── H3 event dispatcher ───────────────────────────────────────────────────

    def _dispatch_h3_event(self, event: H3Event) -> None:
        if isinstance(event, HeadersReceived):
            self._handle_headers(event)

        elif isinstance(event, WebTransportStreamDataReceived):
            bridge = self._bridges.get(event.session_id)
            if bridge is not None:
                bridge.receive_from_browser(event.data, event.stream_ended)

    def _handle_headers(self, event: HeadersReceived) -> None:
        headers = dict(event.headers)
        method   = headers.get(b":method",   b"")
        protocol = headers.get(b":protocol", b"")
        path     = headers.get(b":path",     b"/").decode("utf-8", errors="replace")

        if method != b"CONNECT" or protocol != b"webtransport":
            return

        logger.info(
            "[QUIC] WebTransport CONNECT from %s (path=%s)",
            self._quic._network_paths[0].addr if self._quic._network_paths else "?",
            path,
        )

        # Accept the WebTransport session
        self._h3.send_headers(
            stream_id=event.stream_id,
            headers=[
                (b":status", b"200"),
                (b"sec-webtransport-http3-draft", b"draft02"),
            ],
        )
        self.transmit()

        session_id = event.stream_id

        # The browser will open a bidirectional stream immediately after.
        # We pre-create the bridge without a stream_id; the first
        # WebTransportStreamDataReceived will carry the real stream_id.
        # For simplicity we use the session_id as a placeholder stream_id
        # until the actual stream arrives. The bridge is keyed by session_id.
        bridge = StreamBridge(
            session_id=session_id,
            stream_id=session_id,   # updated on first stream data if needed
            protocol=self,
        )
        self._bridges[session_id] = bridge
        task = asyncio.ensure_future(bridge.run())
        self._tasks[session_id] = task
        task.add_done_callback(lambda _: self._cleanup_session(session_id))

    def _cleanup_session(self, session_id: int) -> None:
        self._bridges.pop(session_id, None)
        self._tasks.pop(session_id, None)
        logger.debug("[QUIC] Session %s cleaned up", session_id)

    # ── Outgoing data helper ──────────────────────────────────────────────────

    def send_to_stream(self, session_id: int, stream_id: int, data: bytes) -> None:
        """Send bytes to the browser over the given QUIC stream."""
        try:
            self._quic.send_stream_data(stream_id, data)
            self.transmit()
        except Exception as exc:
            logger.warning(
                "[QUIC] send_to_stream(%s) failed: %s", session_id, exc
            )


# ─── Entry point ──────────────────────────────────────────────────────────────

async def main() -> None:
    logger.info("Starting WebTransport ↔ WebSocket proxy")
    logger.info("  Listening  : UDP %s:%s", WT_HOST, WT_PORT)
    logger.info("  SFU target : %s", SFU_WS_URL)
    logger.info("  TLS cert   : %s", CERT_FILE)

    quic_config = QuicConfiguration(
        alpn_protocols=H3_ALPN,
        is_client=False,
        max_datagram_frame_size=65536,
    )
    quic_config.load_cert_chain(CERT_FILE, KEY_FILE)

    loop = asyncio.get_running_loop()

    # Graceful shutdown on SIGINT / SIGTERM
    # aioquic 1.x: serve() returns a QuicServer object, NOT an async context manager.
    stop = loop.create_future()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set_result, None)
        except NotImplementedError:
            # Windows does not support add_signal_handler for all signals
            pass

    server = await serve(
        WT_HOST,
        WT_PORT,
        configuration=quic_config,
        create_protocol=SfuBridgeProtocol,
    )

    logger.info("WebTransport proxy is ready. Press Ctrl+C to stop.")
    try:
        await stop
    except asyncio.CancelledError:
        pass
    finally:
        server.close()

    logger.info("WebTransport proxy shut down.")


if __name__ == "__main__":
    asyncio.run(main())
