/**
 * WebSocket Signaling Client with Result-based error handling.
 *
 * This version never throws from request/response parsing code paths.
 * All caller-facing operations return Result<T, WebRTCError>.
 */

import { Result, err, ok } from './result';
import {
  WebRTCError,
  createWebRTCError,
  signalingErrorFromMessage,
} from './WebRTCError';

export type SignalingEventHandler<T = any> = (data: T) => void | Promise<void>;

interface PendingRequest {
  method: string;
  resolve: (result: Result<any, WebRTCError>) => void;
  timeout: ReturnType<typeof setTimeout>;
}

interface ConnectOptions {
  roomId?: string;
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

const DEFAULT_SIGNALING_PATH = '/ws/sfu/';
const CONNECT_WELCOME_TIMEOUT_MS = 30_000;

function canUseWindowLocation(): boolean {
  return typeof window !== 'undefined' && !!window.location;
}

function normalizeSignalingUrl(inputUrl: string): string {
  const rawUrl = String(inputUrl || '').trim();
  if (!canUseWindowLocation()) {
    return rawUrl;
  }

  const pageIsHttps = window.location.protocol === 'https:';
  const wsScheme = pageIsHttps ? 'wss:' : 'ws:';
  const wsOrigin = `${wsScheme}//${window.location.host}`;

  if (!rawUrl) {
    return `${wsOrigin}${DEFAULT_SIGNALING_PATH}`;
  }

  if (rawUrl.startsWith('/')) {
    return `${wsOrigin}${rawUrl}`;
  }

  const hasProtocol = /^[a-z][a-z\d+\-.]*:\/\//i.test(rawUrl);
  const candidateUrl = hasProtocol
    ? rawUrl
    : `${wsOrigin}/${rawUrl.replace(/^\/+/, '')}`;

  try {
    const parsed = new URL(candidateUrl);
    const protocol = parsed.protocol.toLowerCase();

    if (protocol === 'http:') {
      parsed.protocol = 'ws:';
    } else if (protocol === 'https:') {
      parsed.protocol = 'wss:';
    }

    // Browser page loaded via HTTPS must not downgrade signaling to ws://.
    if (pageIsHttps && parsed.protocol === 'ws:') {
      parsed.protocol = 'wss:';
    }

    if (parsed.protocol !== 'ws:' && parsed.protocol !== 'wss:') {
      return `${wsOrigin}/${rawUrl.replace(/^\/+/, '')}`;
    }

    return parsed.toString();
  } catch {
    return rawUrl;
  }
}

export class SignalingClient {
  private ws: WebSocket | null = null;
  private readonly url: string;
  private requestId = 0;
  private pendingRequests: Map<number, PendingRequest> = new Map();
  private eventHandlers: Map<string, Set<SignalingEventHandler>> = new Map();
  private reconnectAttempts = 0;
  private readonly maxReconnectAttempts = 10;
  private readonly reconnectBaseDelayMs = 1_500;
  private readonly reconnectMaxDelayMs = 30_000;
  private readonly reconnectJitterMs = 1_000;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeatInterval: ReturnType<typeof setInterval> | null = null;
  private notificationDispatchChain: Promise<void> = Promise.resolve();
  private isClosing = false;
  private bootstrapRoomId: string | null = null;

  public peerId: string | null = null;
  public connected = false;

  constructor(url: string) {
    const normalizedUrl = normalizeSignalingUrl(url);
    this.url = normalizedUrl;

    if (normalizedUrl !== url) {
      console.info(`[Signaling] URL normalized: ${url} -> ${normalizedUrl}`);
    }
  }

  // ─────────────────────────────────────────────────────
  // Connection
  // ─────────────────────────────────────────────────────

  connect(options: ConnectOptions = {}): Promise<Result<void, WebRTCError>> {
    if (options.roomId) {
      this.bootstrapRoomId = options.roomId;
    }

    return new Promise((resolve) => {
      this.isClosing = false;
      let settled = false;

      // Reset the dispatch chain so stale promise chains from a previous
      // session cannot block the incoming 'welcome' notification.
      this.notificationDispatchChain = Promise.resolve();

      const finish = (result: Result<void, WebRTCError>) => {
        if (settled) return;
        settled = true;
        clearTimeout(connectTimeout);
        resolve(result);
      };

      // Allow extra time for edge-tunnel handshake + proxy upgrade latency.
      const connectTimeout = setTimeout(() => {
        const activeSocket = this.ws;
        const readyState = activeSocket?.readyState;
        if (activeSocket) {
          if (this.ws === activeSocket) {
            this.ws = null;
          }
          this.detachSocketHandlers(activeSocket);
          this.closeSocketSafely(activeSocket, 'Connection timeout');
        }
        this.connected = false;
        this.off('welcome', onWelcome);
        finish(
          err(
            createWebRTCError(
              'SIGNALING_TIMEOUT',
              `Connection timeout: server did not send welcome within ${
                CONNECT_WELCOME_TIMEOUT_MS / 1000
              } s`,
              {
                retriable: true,
                details: {
                  url: this.url,
                  timeoutMs: CONNECT_WELCOME_TIMEOUT_MS,
                  readyState,
                  readyStateLabel: this.describeReadyState(readyState),
                  connected: this.connected,
                },
              }
            )
          )
        );
      }, CONNECT_WELCOME_TIMEOUT_MS);

      const onWelcome = (data: { peerId?: string }) => {
        this.peerId = data.peerId || null;
        this.off('welcome', onWelcome);
        finish(ok(undefined));
      };

      this.on('welcome', onWelcome);

      try {
        this.ws = new WebSocket(this.url);
        this.ws.binaryType = 'arraybuffer';
      } catch (cause) {
        this.off('welcome', onWelcome);
        finish(
          err(
            createWebRTCError(
              'SIGNALING_CONNECTION_FAILED',
              'WebSocket connection failed',
              { cause, retriable: true }
            )
          )
        );
        return;
      }

      // Capture local reference so callbacks always inspect the correct
      // WebSocket instance, even if `this.ws` is reassigned by a reconnect.
      const ws = this.ws;

      ws.onopen = () => {
        console.log('[Signaling] Connected to', this.url);
        this.connected = true;
        this.reconnectAttempts = 0;
        this.clearReconnectTimer();

        if (this.bootstrapRoomId) {
          ws.send(
            JSON.stringify({
              type: 'join_room',
              roomId: this.bootstrapRoomId,
            })
          );
        }

        this.startHeartbeat();
      };

      ws.onmessage = (event: MessageEvent) => {
        this.handleMessage(event.data);
      };

      ws.onclose = (event) => {
        // Ignore events from a stale WebSocket (reconnect already replaced it)
        if (this.ws !== ws) return;

        console.log(
          `[Signaling] Disconnected: code=${event.code} reason=${event.reason}`
        );
        this.connected = false;
        this.stopHeartbeat();
        this.resolveAllPendingWithError(
          createWebRTCError(
            'SIGNALING_CONNECTION_FAILED',
            event.reason || 'Connection closed',
            { retriable: true, details: { code: event.code } }
          )
        );

        if (!this.peerId && !settled) {
          this.off('welcome', onWelcome);
          finish(
            err(
              createWebRTCError(
                'SIGNALING_CONNECTION_FAILED',
                'Connection closed before welcome message',
                {
                  retriable: true,
                  details: {
                    code: event.code,
                    reason: event.reason,
                    readyState: ws.readyState,
                    readyStateLabel: this.describeReadyState(ws.readyState),
                    url: this.url,
                  },
                }
              )
            )
          );
        }

        if (!this.isClosing) {
          this.attemptReconnect();
        }
      };

      ws.onerror = (event) => {
        // Ignore events from a stale WebSocket (reconnect already replaced it)
        if (this.ws !== ws) return;

        console.error('[Signaling] WebSocket error:', event);
        if (!this.connected) {
          this.off('welcome', onWelcome);
          finish(
            err(
              createWebRTCError(
                'SIGNALING_CONNECTION_FAILED',
                'WebSocket connection failed',
                {
                  retriable: true,
                  details: {
                    url: this.url,
                    event: String(event),
                    readyState: ws.readyState,
                    readyStateLabel: this.describeReadyState(ws.readyState),
                  },
                }
              )
            )
          );
        }
      };
    });
  }

  disconnect(): Result<void, WebRTCError> {
    this.isClosing = true;
    this.clearReconnectTimer();
    this.stopHeartbeat();
    this.resolveAllPendingWithError(
      createWebRTCError('SIGNALING_CONNECTION_FAILED', 'Client disconnecting', {
        retriable: true,
      })
    );

    if (this.ws) {
      const socket = this.ws;
      this.ws = null;
      this.detachSocketHandlers(socket);
      this.closeSocketSafely(socket, 'Client closing');
    }

    this.connected = false;
    this.peerId = null;

    return ok(undefined);
  }

  // ─────────────────────────────────────────────────────
  // Request-Response Pattern
  // ─────────────────────────────────────────────────────

  request<TResponse = any>(
    method: string,
    data: Record<string, unknown> = {},
    timeoutMs = 10000
  ): Promise<Result<TResponse, WebRTCError>> {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      return Promise.resolve(
        err(
          createWebRTCError('SIGNALING_CONNECTION_FAILED', 'Not connected', {
            retriable: true,
          })
        )
      );
    }

    const id = ++this.requestId;

    return new Promise((resolve) => {
      const timeout = setTimeout(() => {
        this.pendingRequests.delete(id);
        resolve(
          err(
            createWebRTCError(
              'SIGNALING_TIMEOUT',
              `Request timeout: ${method} (id=${id})`,
              { retriable: true, details: { method, id } }
            )
          )
        );
      }, timeoutMs);

      this.pendingRequests.set(id, { method, resolve, timeout });

      try {
        const msg = JSON.stringify({ id, method, data });
        this.ws!.send(msg);
      } catch (cause) {
        clearTimeout(timeout);
        this.pendingRequests.delete(id);
        resolve(
          err(
            createWebRTCError(
              'SIGNALING_CONNECTION_FAILED',
              `Failed to send request: ${method}`,
              { retriable: true, cause, details: { method, id } }
            )
          )
        );
      }
    });
  }

  notify(
    method: string,
    data: Record<string, unknown> = {}
  ): Result<void, WebRTCError> {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      return err(
        createWebRTCError(
          'SIGNALING_CONNECTION_FAILED',
          `Failed to send notify(${method}): signaling socket is not open`,
          {
            retriable: true,
            details: {
              readyState: this.ws?.readyState,
              readyStateLabel: this.describeReadyState(this.ws?.readyState),
            },
          }
        )
      );
    }

    try {
      this.ws.send(JSON.stringify({ id: 0, method, data }));
      return ok(undefined);
    } catch (cause) {
      return err(
        createWebRTCError(
          'SIGNALING_CONNECTION_FAILED',
          `Failed to send notify(${method})`,
          { retriable: true, cause }
        )
      );
    }
  }

  // ─────────────────────────────────────────────────────
  // Event System
  // ─────────────────────────────────────────────────────

  on(event: string, handler: SignalingEventHandler): void {
    if (!this.eventHandlers.has(event)) {
      this.eventHandlers.set(event, new Set());
    }
    this.eventHandlers.get(event)!.add(handler);
  }

  off(event: string, handler: SignalingEventHandler): void {
    this.eventHandlers.get(event)?.delete(handler);
  }

  private async emit(event: string, data: unknown): Promise<void> {
    const handlers = this.eventHandlers.get(event);
    if (!handlers) return;

    for (const handler of handlers) {
      try {
        await Promise.resolve(handler(data));
      } catch (error) {
        console.error(`[Signaling] Event handler error (${event}):`, error);
      }
    }
  }

  private enqueueNotification(event: string, data: unknown): void {
    this.notificationDispatchChain = this.notificationDispatchChain
      .then(() => this.emit(event, data))
      .catch((error) => {
        console.error(`[Signaling] Notification dispatch error (${event}):`, error);
      });
  }

  // ─────────────────────────────────────────────────────
  // Message Handling
  // ─────────────────────────────────────────────────────

  private handleMessage(raw: string | ArrayBuffer): void {
    const parsed = this.parseIncomingMessage(raw);
    if (!parsed.ok) {
      // parsed.error is available because !parsed.ok narrows the type
      this.enqueueNotification('signalingError', (parsed as { ok: false; error: WebRTCError }).error);
      return;
    }

    const msg = parsed.value;

    if (msg.response) {
      const pending = this.pendingRequests.get(msg.id || -1);
      if (!pending) return;

      clearTimeout(pending.timeout);
      this.pendingRequests.delete(msg.id || -1);

      if (msg.ok) {
        pending.resolve(ok(msg.data as any));
      } else {
        const serverMessage = typeof msg.error === 'string' ? msg.error : 'Request failed';
        pending.resolve(
          err(
            signalingErrorFromMessage(serverMessage, {
              method: pending.method,
              requestId: msg.id,
            })
          )
        );
      }
      return;
    }

    if (msg.method) {
      this.enqueueNotification(msg.method, msg.data);
      return;
    }

    if (msg.type) {
      this.enqueueNotification(msg.type, msg.data);
      return;
    }

    this.enqueueNotification(
      'signalingError',
      createWebRTCError(
        'SIGNALING_PROTOCOL_ERROR',
        'Invalid signaling message: missing method/type/response',
        { retriable: false, details: { rawMessage: msg } }
      )
    );
  }

  private parseIncomingMessage(
    raw: string | ArrayBuffer
  ): Result<SignalingEnvelope, WebRTCError> {
    try {
      const text =
        typeof raw === 'string'
          ? raw
          : new TextDecoder().decode(raw as ArrayBuffer);
      const parsed = JSON.parse(text);

      if (!parsed || typeof parsed !== 'object') {
        return err(
          createWebRTCError(
            'SIGNALING_PROTOCOL_ERROR',
            'Decoded signaling message is not an object',
            { retriable: false }
          )
        );
      }

      return ok(parsed as SignalingEnvelope);
    } catch (cause) {
      return err(
        createWebRTCError('SIGNALING_PROTOCOL_ERROR', 'Failed to decode message', {
          retriable: false,
          cause,
        })
      );
    }
  }

  // ─────────────────────────────────────────────────────
  // Heartbeat & Reconnect
  // ─────────────────────────────────────────────────────

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.heartbeatInterval = setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.notify('ping');
      }
    }, 15000);
  }

  private stopHeartbeat(): void {
    if (!this.heartbeatInterval) return;
    clearInterval(this.heartbeatInterval);
    this.heartbeatInterval = null;
  }

  private attemptReconnect(): void {
    if (this.isClosing) {
      this.clearReconnectTimer();
      return;
    }

    if (this.reconnectTimer) {
      return;
    }

    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error('[Signaling] Max reconnect attempts reached');
      this.enqueueNotification('reconnectFailed', {});
      return;
    }

    this.reconnectAttempts++;
    const exponentialDelay = Math.min(
      this.reconnectBaseDelayMs * Math.pow(2, this.reconnectAttempts - 1),
      this.reconnectMaxDelayMs
    );
    const jitter = Math.floor(Math.random() * this.reconnectJitterMs);
    const totalDelay = exponentialDelay + jitter;

    console.log(
      `[Signaling] Reconnecting in ${totalDelay}ms ` +
        `(attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})`
    );

    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      if (this.isClosing) return;

      this.connect({ roomId: this.bootstrapRoomId || undefined }).then((result) => {
        if (!result.ok && !this.isClosing) {
          this.attemptReconnect();
        }
      });
    }, totalDelay);
  }

  private clearReconnectTimer(): void {
    if (!this.reconnectTimer) return;
    clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
  }

  private detachSocketHandlers(socket: WebSocket): void {
    socket.onopen = null;
    socket.onmessage = null;
    socket.onclose = null;
    socket.onerror = null;
  }

  private closeSocketSafely(socket: WebSocket, reason: string): void {
    if (socket.readyState === WebSocket.CONNECTING) {
      // Calling close() in CONNECTING triggers a noisy browser error
      // ("closed before the connection is established"). Defer close.
      socket.onopen = () => {
        this.detachSocketHandlers(socket);
        try {
          socket.close(1000, reason);
        } catch {
          // ignore
        }
      };
      return;
    }

    if (socket.readyState === WebSocket.OPEN) {
      try {
        socket.close(1000, reason);
      } catch {
        // ignore
      }
    }
  }

  private resolveAllPendingWithError(error: WebRTCError): void {
    for (const [, pending] of this.pendingRequests) {
      clearTimeout(pending.timeout);
      pending.resolve(err(error));
    }
    this.pendingRequests.clear();
  }

  private describeReadyState(readyState: number | undefined): string {
    switch (readyState) {
      case WebSocket.CONNECTING:
        return 'CONNECTING';
      case WebSocket.OPEN:
        return 'OPEN';
      case WebSocket.CLOSING:
        return 'CLOSING';
      case WebSocket.CLOSED:
        return 'CLOSED';
      default:
        return 'UNKNOWN';
    }
  }
}
