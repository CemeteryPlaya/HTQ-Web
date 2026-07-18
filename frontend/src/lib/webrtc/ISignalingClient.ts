/**
 * ISignalingClient — Common interface for signaling transport implementations.
 *
 * Implemented by:
 *  - SignalingClient             → WebSocket (current, unchanged)
 *  - WebTransportSignalingClient → QUIC bidirectional stream (new)
 *
 * MediaEngine depends only on this interface, so the transport layer
 * can be swapped without touching any media or SDP logic.
 */

import type { Result } from './result';
import type { WebRTCError } from './WebRTCError';

export type SignalingEventHandler<T = unknown> = (data: T) => void | Promise<void>;

export interface ISignalingClient {
  /** The peerId assigned by the SFU after a successful welcome. */
  readonly peerId: string | null;
  /** True when an active connection to the SFU exists. */
  readonly connected: boolean;

  /**
   * Open the transport connection and wait for the SFU 'welcome' event.
   * Returns ok(undefined) when ready to send requests.
   */
  connect(options?: { roomId?: string }): Promise<Result<void, WebRTCError>>;

  /**
   * Gracefully close the connection and cancel all pending requests.
   */
  disconnect(): Result<void, WebRTCError>;

  /**
   * Send a request and wait for the matching response from the SFU.
   * @param method   - Signaling method name (e.g. 'joinRoom')
   * @param data     - Request payload
   * @param timeoutMs - Max wait time (default 10 000 ms)
   */
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  request<TResponse = any>(
    method: string,
    data?: Record<string, unknown>,
    timeoutMs?: number
  ): Promise<Result<TResponse, WebRTCError>>;

  /**
   * Send a fire-and-forget notification to the SFU (no response expected).
   * @param method - Signaling method name (e.g. 'qualityReport')
   * @param data   - Notification payload
   */
  notify(
    method: string,
    data?: Record<string, unknown>
  ): Result<void, WebRTCError>;

  /** Subscribe to a server-pushed event (e.g. 'newConsumer'). */
  on(event: string, handler: SignalingEventHandler): void;

  /** Unsubscribe a previously registered event handler. */
  off(event: string, handler: SignalingEventHandler): void;
}
