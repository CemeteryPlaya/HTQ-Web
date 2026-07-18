/**
 * WebTransportSignalingClient
 *
 * Drop-in replacement for SignalingClient that uses WebTransport (QUIC / HTTP3)
 * instead of WebSocket for the SFU signaling channel.
 *
 * PROTOCOL
 * ─────────
 * Same JSON envelope as the WebSocket client:
 *   Request   → {"id":1, "method":"joinRoom", "data":{...}}\n
 *   Response  → {"id":1, "response":true, "ok":true, "data":{...}}\n
 *   Server push → {"type":"newConsumer", "data":{...}}\n
 *
 * Messages are newline-delimited (NDJSON) over a single QUIC bidirectional stream.
 * QUIC handles framing, ordering, and encryption — no need for SDP/ICE/DTLS.
 *
 * RECONNECTION
 * ─────────────
 * WebTransport supports QUIC connection migration (IP change → session survives).
 * If the session closes unexpectedly, we retry with exponential back-off,
 * mirroring the WebSocket client's behaviour.
 *
 * USAGE
 * ──────
 *   const client = new WebTransportSignalingClient('https://sfu.example.com:4433/sfu');
 *   await client.connect({ roomId: 'room-123' });
 *   await client.request('joinRoom', { roomId, displayName });
 */

import type { ISignalingClient, SignalingEventHandler } from './ISignalingClient';
import type { Result } from './result';
import { ok, err } from './result';
import type { WebRTCError } from './WebRTCError';
import { createWebRTCError, signalingErrorFromMessage } from './WebRTCError';

// ─── Types ────────────────────────────────────────────────────────────────────

interface PendingRequest {
  method: string;
  resolve: (result: Result<unknown, WebRTCError>) => void;
  timer: ReturnType<typeof setTimeout>;
}

interface SignalingEnvelope {
  id?: number;
  type?: string;
  method?: string;
  roomId?: string;
  data?: unknown;
  response?: boolean;
  ok?: boolean;
  error?: string;
}

// ─── Constants ────────────────────────────────────────────────────────────────

const WELCOME_TIMEOUT_MS    = 30_000;
const DEFAULT_REQUEST_TIMEOUT_MS = 10_000;
const HEARTBEAT_INTERVAL_MS = 15_000;
const RECONNECT_BASE_MS     = 1_500;
const RECONNECT_MAX_MS      = 30_000;
const RECONNECT_JITTER_MS   = 1_000;
const MAX_RECONNECT_ATTEMPTS = 10;

// ─── WebTransport Signaling Client ───────────────────────────────────────────

export class WebTransportSignalingClient implements ISignalingClient {

  // Public state (ISignalingClient interface)
  private _peerId: string | null = null;
  private _connected = false;

  get peerId(): string | null  { return this._peerId; }
  get connected(): boolean     { return this._connected; }

  // Internal state
  private wt: WebTransport | null = null;
  private writer: WritableStreamDefaultWriter<Uint8Array> | null = null;
  private requestCounter = 0;
  private pendingRequests = new Map<number, PendingRequest>();
  private eventHandlers   = new Map<string, Set<SignalingEventHandler>>();
  private notifyChain: Promise<void> = Promise.resolve();

  private isClosing        = false;
  private reconnectAttempts = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval>  | null = null;

  private bootstrapRoomId: string | null = null;

  private readonly encoder = new TextEncoder();
  private readonly decoder = new TextDecoder();
  private readonly url: string;

  constructor(url: string) {
    this.url = url;
    console.info('[WT Signaling] Using WebTransport endpoint:', url);
  }

  // ─── ISignalingClient: connect ────────────────────────────────────────────

  connect(options: { roomId?: string } = {}): Promise<Result<void, WebRTCError>> {
    if (options.roomId) {
      this.bootstrapRoomId = options.roomId;
    }

    this.isClosing = false;
    this.notifyChain = Promise.resolve();

    return new Promise((resolve) => {
      let settled = false;

      const finish = (result: Result<void, WebRTCError>) => {
        if (settled) return;
        settled = true;
        clearTimeout(welcomeTimer);
        resolve(result);
      };

      const welcomeTimer = setTimeout(() => {
        this.off('welcome', onWelcome);
        finish(err(createWebRTCError(
          'SIGNALING_TIMEOUT',
          `WebTransport: server did not send welcome within ${WELCOME_TIMEOUT_MS / 1000}s`,
          { retriable: true, details: { url: this.url } }
        )));
      }, WELCOME_TIMEOUT_MS);

      const onWelcome = (data: unknown) => {
        const payload = data as { peerId?: string };
        this._peerId = payload?.peerId ?? null;
        this.off('welcome', onWelcome);
        finish(ok(undefined));
      };

      this.on('welcome', onWelcome);

      this.doConnect().catch((cause) => {
        this.off('welcome', onWelcome);
        finish(err(createWebRTCError(
          'SIGNALING_CONNECTION_FAILED',
          `WebTransport connection failed: ${cause instanceof Error ? cause.message : String(cause)}`,
          { retriable: true, cause }
        )));
      });
    });
  }

  // ─── ISignalingClient: disconnect ─────────────────────────────────────────

  disconnect(): Result<void, WebRTCError> {
    this.isClosing = true;
    this.clearReconnectTimer();
    this.stopHeartbeat();
    this.rejectAllPending(createWebRTCError(
      'SIGNALING_CONNECTION_FAILED', 'Client disconnecting', { retriable: false }
    ));
    this.closeSession('Client closing');
    this._connected = false;
    this._peerId    = null;
    return ok(undefined);
  }

  // ─── ISignalingClient: request ────────────────────────────────────────────

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  request<TResponse = any>(
    method: string,
    data: Record<string, unknown> = {},
    timeoutMs = DEFAULT_REQUEST_TIMEOUT_MS
  ): Promise<Result<TResponse, WebRTCError>> {
    if (!this._connected || !this.writer) {
      return Promise.resolve(err(createWebRTCError(
        'SIGNALING_CONNECTION_FAILED', 'Not connected (WebTransport)', { retriable: true }
      )));
    }

    const id = ++this.requestCounter;

    return new Promise((resolve) => {
      const timer = setTimeout(() => {
        this.pendingRequests.delete(id);
        resolve(err(createWebRTCError(
          'SIGNALING_TIMEOUT',
          `Request timeout: ${method} (id=${id})`,
          { retriable: true, details: { method, id } }
        )));
      }, timeoutMs);

      this.pendingRequests.set(id, { method, resolve: resolve as PendingRequest['resolve'], timer });

      this.sendRaw({ id, method, data }).catch((cause) => {
        clearTimeout(timer);
        this.pendingRequests.delete(id);
        resolve(err(createWebRTCError(
          'SIGNALING_CONNECTION_FAILED',
          `Failed to send request: ${method}`,
          { retriable: true, cause, details: { method, id } }
        )));
      });
    });
  }

  // ─── ISignalingClient: notify ─────────────────────────────────────────────

  notify(
    method: string,
    data: Record<string, unknown> = {}
  ): Result<void, WebRTCError> {
    if (!this._connected || !this.writer) {
      return err(createWebRTCError(
        'SIGNALING_CONNECTION_FAILED',
        `Failed to send notify(${method}): not connected`,
        { retriable: true }
      ));
    }
    // Fire-and-forget: enqueue but do not await
    this.sendRaw({ id: 0, method, data }).catch((e) => {
      console.warn(`[WT Signaling] notify(${method}) send failed:`, e);
    });
    return ok(undefined);
  }

  // ─── ISignalingClient: on / off ───────────────────────────────────────────

  on(event: string, handler: SignalingEventHandler): void {
    if (!this.eventHandlers.has(event)) {
      this.eventHandlers.set(event, new Set());
    }
    this.eventHandlers.get(event)!.add(handler);
  }

  off(event: string, handler: SignalingEventHandler): void {
    this.eventHandlers.get(event)?.delete(handler);
  }

  // ─── Private: connection lifecycle ────────────────────────────────────────

  private async doConnect(): Promise<void> {
    const wt = new WebTransport(this.url);
    this.wt = wt;

    // Wait for QUIC handshake to complete
    await wt.ready;

    this._connected = true;
    this.reconnectAttempts = 0;
    console.info('[WT Signaling] QUIC session established to', this.url);

    // Open a single bidirectional stream for all signaling traffic
    const bidi = await wt.createBidirectionalStream();
    this.writer = bidi.writable.getWriter();

    // Send bootstrap join_room if we have one (mirrors WebSocket onopen logic)
    if (this.bootstrapRoomId) {
      await this.sendRaw({ type: 'join_room', roomId: this.bootstrapRoomId });
    }

    this.startHeartbeat();

    // Read loop runs until stream closes
    this.runReadLoop(bidi.readable).catch((e) => {
      if (!this.isClosing) {
        console.warn('[WT Signaling] Read loop error:', e);
        this.handleDisconnect(`read error: ${e}`);
      }
    });

    // Handle session-level close (connection migration failure, server close, etc.)
    wt.closed.then(() => {
      if (!this.isClosing) this.handleDisconnect('session closed');
    }).catch((e) => {
      if (!this.isClosing) this.handleDisconnect(`session error: ${e}`);
    });
  }

  private async runReadLoop(readable: ReadableStream<Uint8Array>): Promise<void> {
    const reader = readable.getReader();
    let lineBuffer = '';

    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        lineBuffer += this.decoder.decode(value, { stream: true });

        // Split on newline — each complete line is one JSON message
        const lines = lineBuffer.split('\n');
        lineBuffer = lines.pop() ?? ''; // keep partial trailing line

        for (const line of lines) {
          const trimmed = line.trim();
          if (trimmed) this.handleRawMessage(trimmed);
        }
      }
    } finally {
      reader.releaseLock();
    }
  }

  private async sendRaw(payload: object): Promise<void> {
    if (!this.writer) throw new Error('writer not initialised');
    const line = JSON.stringify(payload) + '\n';
    await this.writer.write(this.encoder.encode(line));
  }

  private closeSession(reason: string): void {
    if (this.wt) {
      try { this.wt.close(); } catch { /* ignore */ }
      this.wt = null;
    }
    if (this.writer) {
      try { this.writer.releaseLock(); } catch { /* ignore */ }
      this.writer = null;
    }
    console.info('[WT Signaling] Session closed:', reason);
  }

  // ─── Private: message handling ────────────────────────────────────────────

  private handleRawMessage(raw: string): void {
    let envelope: SignalingEnvelope;
    try {
      envelope = JSON.parse(raw) as SignalingEnvelope;
    } catch {
      console.warn('[WT Signaling] Failed to parse message:', raw.slice(0, 200));
      return;
    }

    // Response to a pending request
    if (envelope.response && typeof envelope.id === 'number' && envelope.id !== 0) {
      const pending = this.pendingRequests.get(envelope.id);
      if (pending) {
        clearTimeout(pending.timer);
        this.pendingRequests.delete(envelope.id);
        if (envelope.ok) {
          pending.resolve(ok(envelope.data));
        } else {
          pending.resolve(err(signalingErrorFromMessage(
            envelope.error ?? 'Request failed',
            { method: pending.method, id: envelope.id }
          )));
        }
      }
      return;
    }

    // Server-push event
    const eventType = envelope.type ?? envelope.method;
    if (eventType) {
      this.enqueueEvent(eventType, envelope.data);
    }
  }

  private enqueueEvent(event: string, data: unknown): void {
    this.notifyChain = this.notifyChain
      .then(() => this.emitEvent(event, data))
      .catch((e) => console.error(`[WT Signaling] Event dispatch error (${event}):`, e));
  }

  private async emitEvent(event: string, data: unknown): Promise<void> {
    const handlers = this.eventHandlers.get(event);
    if (!handlers) return;
    for (const handler of handlers) {
      try {
        await Promise.resolve(handler(data));
      } catch (e) {
        console.error(`[WT Signaling] Handler error (${event}):`, e);
      }
    }
  }

  // ─── Private: reconnection ────────────────────────────────────────────────

  private handleDisconnect(reason: string): void {
    console.warn('[WT Signaling] Disconnected:', reason);
    this._connected = false;
    this.stopHeartbeat();
    this.rejectAllPending(createWebRTCError(
      'SIGNALING_CONNECTION_FAILED', reason, { retriable: true }
    ));
    this.closeSession(reason);

    if (!this.isClosing) {
      this.scheduleReconnect();
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
      console.error('[WT Signaling] Max reconnect attempts reached. Giving up.');
      this.enqueueEvent('reconnectFailed', null);
      return;
    }

    const delay = Math.min(
      RECONNECT_BASE_MS * Math.pow(2, this.reconnectAttempts),
      RECONNECT_MAX_MS
    ) + Math.floor(Math.random() * RECONNECT_JITTER_MS);

    this.reconnectAttempts++;
    console.info(
      `[WT Signaling] Reconnect attempt ${this.reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS} in ${delay}ms`
    );

    this.reconnectTimer = setTimeout(async () => {
      if (this.isClosing) return;
      try {
        await this.doConnect();
      } catch (e) {
        console.warn('[WT Signaling] Reconnect failed:', e);
        if (!this.isClosing) this.scheduleReconnect();
      }
    }, delay);
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  // ─── Private: heartbeat ───────────────────────────────────────────────────

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.heartbeatTimer = setInterval(() => {
      if (this._connected) {
        this.notify('ping');
      }
    }, HEARTBEAT_INTERVAL_MS);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer !== null) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  // ─── Private: pending requests cleanup ───────────────────────────────────

  private rejectAllPending(error: WebRTCError): void {
    for (const [, pending] of this.pendingRequests) {
      clearTimeout(pending.timer);
      pending.resolve(err(error));
    }
    this.pendingRequests.clear();
  }
}
