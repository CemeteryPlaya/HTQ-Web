/**
 * WebRTCAdapter — IMediaTransport implementation backed by WebRTCManager
 *
 * Responsibilities:
 *  1. Translate TransportJoinOptions → WebRTCManagerOptions
 *  2. Map WebRTCError codes → TransportErrorCode
 *  3. Map RemoteStream (WebRTC) → RemoteParticipantStream (transport-agnostic)
 *  4. Map QualityMetrics (WebRTC) → TransportMetrics (transport-agnostic)
 *  5. Delegate all event callbacks through IMediaTransportEvents
 *  6. Auto-detect WebTransport: if VITE_WEBTRANSPORT_URL is set and the
 *     browser supports WebTransport, injects WebTransportSignalingClient.
 *     Falls back to the existing WebSocket SignalingClient automatically.
 *
 * The existing WebRTCManager and all underlying code are UNCHANGED.
 */

import { WebRTCManager } from '../webrtc/WebRTCManager';
import type { WebRTCManagerOptions } from '../webrtc/WebRTCManager';
import { WebTransportSignalingClient } from '../webrtc/WebTransportSignalingClient';
import type { ISignalingClient } from '../webrtc/ISignalingClient';
import type { WebRTCError, WebRTCErrorCode } from '../webrtc/WebRTCError';
import type { RemoteStream } from '../webrtc/MediaEngine';
import type { QualityMetrics } from '../webrtc/BitrateController';
import { ok, err, isErr } from '../webrtc/result';
import type { Result } from '../webrtc/result';

import type {
  IMediaTransport,
  IMediaTransportEvents,
  TransportError,
  TransportErrorCode,
  RemoteParticipantStream,
  TransportMetrics,
  TransportJoinOptions,
} from './IMediaTransport';

// ─── WebTransport feature detection ─────────────────────────────────────────

/**
 * Returns a signaling factory that uses WebTransport (QUIC) when:
 *   1. The environment variable VITE_WEBTRANSPORT_URL is set, AND
 *   2. The browser supports the WebTransport API.
 *
 * Otherwise returns undefined → MediaEngine falls back to WebSocket SignalingClient.
 *
 * The factory receives the WebSocket URL (ignored) and returns a client
 * connected to the WebTransport endpoint instead.
 */
function buildSignalingFactory(): ((wsUrl: string) => ISignalingClient) | undefined {
  const wtUrl = (import.meta.env as Record<string, unknown>)['VITE_WEBTRANSPORT_URL'];
  if (!wtUrl || typeof wtUrl !== 'string' || wtUrl.trim() === '') return undefined;
  if (typeof window === 'undefined' || !('WebTransport' in window)) return undefined;

  const endpoint = wtUrl.trim();
  console.info('[WebRTCAdapter] WebTransport available — signaling via QUIC:', endpoint);

  return (_wsUrl: string) => new WebTransportSignalingClient(endpoint);
}

// ─── Error mapping ──────────────────────────────────────────────────────────

const WEBRTC_TO_TRANSPORT_ERROR: Record<WebRTCErrorCode, TransportErrorCode> = {
  SIGNALING_CONNECTION_FAILED: 'CONNECTION_FAILED',
  SIGNALING_PROTOCOL_ERROR:    'CONNECTION_FAILED',
  SIGNALING_TIMEOUT:           'CONNECTION_TIMEOUT',
  SIGNALING_REQUEST_FAILED:    'CONNECTION_FAILED',
  SIGNALING_UNSUPPORTED_CODEC: 'UNSUPPORTED_CODEC',
  NATIVE_SDP_REJECTION:        'UNSUPPORTED_CODEC',
  ICE_GATHERING_FAILURE:       'CONNECTION_FAILED',
  MEDIA_CAPTURE_FAILURE:       'MEDIA_CAPTURE_FAILURE',
  TRANSPORT_SETUP_FAILURE:     'CONNECTION_FAILED',
  UNKNOWN:                     'UNKNOWN',
};

function mapError(e: WebRTCError): TransportError {
  return {
    code: WEBRTC_TO_TRANSPORT_ERROR[e.code] ?? 'UNKNOWN',
    message: e.message,
    retriable: e.retriable,
    details: e.details,
    cause: e.cause,
  };
}

// ─── Stream / Metrics mapping ────────────────────────────────────────────────

function mapRemoteStream(s: RemoteStream): RemoteParticipantStream {
  return {
    peerId:      s.peerId,
    displayName: s.displayName,
    streamId:    s.consumerId,
    kind:        s.kind,
    track:       s.track,
    stream:      s.stream,
  };
}

function mapMetrics(m: QualityMetrics): TransportMetrics {
  return {
    rttMs:                          m.rttMs,
    packetLossRate:                 m.packetLossRate,
    jitterMs:                       m.jitterMs,
    currentVideoBitrateBps:         m.currentVideoBitrateBps,
    currentAudioBitrateBps:         m.currentAudioBitrateBps,
    effectiveTargetVideoBitrateBps: m.effectiveTargetVideoBitrateBps,
    nominalTargetVideoBitrateBps:   m.nominalTargetVideoBitrateBps,
    starvationMode:                 m.starvationMode,
    codec:                          m.codec,
    width:                          m.width,
    height:                         m.height,
    fps:                            m.fps,
  };
}

function notConnectedError(): TransportError {
  return {
    code: 'CONNECTION_FAILED',
    message: 'Transport is not connected. Call join() first.',
    retriable: true,
  };
}

// ─── Adapter class ───────────────────────────────────────────────────────────

/**
 * Wraps WebRTCManager to implement the transport-agnostic IMediaTransport interface.
 *
 * Signaling transport selection (evaluated once per join()):
 *   - VITE_WEBTRANSPORT_URL set + browser supports WebTransport
 *     → WebTransportSignalingClient (QUIC bidirectional stream)
 *   - Otherwise
 *     → SignalingClient (WebSocket, existing default)
 *
 * WebRTC media plane (ICE / DTLS / RTP) is unaffected regardless of which
 * signaling transport is chosen.
 */
export class WebRTCAdapter implements IMediaTransport {
  readonly transportType = 'webrtc' as const;

  private manager: WebRTCManager | null = null;
  private readonly events: IMediaTransportEvents;
  private readonly signalingFactory = buildSignalingFactory();

  constructor(events: IMediaTransportEvents = {}) {
    this.events = events;
  }

  async join(options: TransportJoinOptions): Promise<Result<MediaStream, TransportError>> {
    const leaveResult = await this.leave();
    if (isErr(leaveResult)) {
      this.events.onInfo?.(
        `[WebRTCAdapter] Warning: cleanup before rejoin failed — ${leaveResult.error.message}`
      );
    }

    const managerOptions: WebRTCManagerOptions = {
      signalingUrl:     options.signalingUrl ?? '',
      roomId:           options.roomId,
      displayName:      options.displayName,
      signalingFactory: this.signalingFactory,
      ...(options.iceServers?.length ? { iceServers: options.iceServers } : {}),
    };

    this.manager = new WebRTCManager(managerOptions, this.buildManagerEvents());

    const result = await this.manager.join();
    if (isErr(result)) {
      this.manager = null;
      return err(mapError(result.error));
    }

    return result;
  }

  async leave(): Promise<Result<void, TransportError>> {
    if (!this.manager) return ok(undefined);

    const result = await this.manager.leave();
    this.manager = null;

    if (isErr(result)) return err(mapError(result.error));
    return ok(undefined);
  }

  setAudioEnabled(enabled: boolean): Result<void, TransportError> {
    if (!this.manager) return err(notConnectedError());

    const result = this.manager.setAudioEnabled(enabled);
    if (isErr(result)) return err(mapError(result.error));
    return ok(undefined);
  }

  setVideoEnabled(enabled: boolean): Result<void, TransportError> {
    if (!this.manager) return err(notConnectedError());

    const result = this.manager.setVideoEnabled(enabled);
    if (isErr(result)) return err(mapError(result.error));
    return ok(undefined);
  }

  getLocalStream(): MediaStream | null {
    return this.manager?.getLocalStream() ?? null;
  }

  getRemoteStreams(): RemoteParticipantStream[] {
    return (this.manager?.getRemoteStreams() ?? []).map(mapRemoteStream);
  }

  private buildManagerEvents() {
    return {
      onRemoteStream: (s: RemoteStream) =>
        this.events.onRemoteStream?.(mapRemoteStream(s)),
      onRemoteStreamRemoved: (consumerId: string) =>
        this.events.onRemoteStreamRemoved?.(consumerId),
      onActiveSpeakers: (speakers: Array<{ peerId: string; isPrimary: boolean }>) =>
        this.events.onActiveSpeakers?.(speakers),
      onParticipantJoined: (peerId: string, displayName: string) =>
        this.events.onParticipantJoined?.(peerId, displayName),
      onParticipantLeft: (peerId: string) =>
        this.events.onParticipantLeft?.(peerId),
      onQualityMetrics: (m: QualityMetrics) =>
        this.events.onQualityMetrics?.(mapMetrics(m)),
      onConnectionStateChange: (state: string) =>
        this.events.onConnectionStateChange?.(state),
      onError: (e: WebRTCError) =>
        this.events.onError?.(mapError(e)),
      onInfo: (message: string) =>
        this.events.onInfo?.(message),
    };
  }
}
