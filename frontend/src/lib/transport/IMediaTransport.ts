/**
 * IMediaTransport — Transport-Agnostic Conference Interface
 *
 * This interface abstracts over the underlying media transport (WebRTC, WebTransport, etc.)
 * so that the UI layer can work with either implementation interchangeably.
 *
 * Pattern: Adapter / Strategy
 *   - WebRTCAdapter  → wraps existing WebRTCManager (WebRTC / ICE / SDP)
 *   - WebTransportAdapter → future HTTP/3 QUIC implementation
 */

import type { Result } from '../webrtc/result';

// ─── Error types ────────────────────────────────────────────────────────────

export type TransportErrorCode =
  | 'CONNECTION_FAILED'
  | 'CONNECTION_TIMEOUT'
  | 'MEDIA_CAPTURE_FAILURE'
  | 'STREAM_ERROR'
  | 'UNSUPPORTED_CODEC'
  | 'DISCONNECTED'
  | 'UNKNOWN';

export interface TransportError {
  code: TransportErrorCode;
  message: string;
  retriable: boolean;
  details?: Record<string, unknown>;
  cause?: unknown;
}

// ─── Stream / Participant types ──────────────────────────────────────────────

/**
 * Describes a single audio or video track received from a remote participant.
 * `streamId` maps to `consumerId` in WebRTC and to a QUIC stream ID in WebTransport.
 */
export interface RemoteParticipantStream {
  peerId: string;
  displayName: string;
  /** Transport-agnostic stream identifier. */
  streamId: string;
  kind: 'audio' | 'video';
  track: MediaStreamTrack;
  stream: MediaStream;
}

// ─── Metrics types ──────────────────────────────────────────────────────────

/**
 * Quality metrics that can be reported by any transport.
 * WebRTC-specific fields (effectiveTarget, nominalTarget) are optional
 * so they can be omitted by non-WebRTC implementations.
 */
export interface TransportMetrics {
  rttMs: number;
  packetLossRate: number;
  jitterMs: number;
  currentVideoBitrateBps: number;
  currentAudioBitrateBps: number;
  effectiveTargetVideoBitrateBps?: number;
  nominalTargetVideoBitrateBps?: number;
  starvationMode: boolean;
  codec: string;
  width: number;
  height: number;
  fps: number;
}

// ─── Event callbacks ────────────────────────────────────────────────────────

export interface IMediaTransportEvents {
  /** A new remote stream (audio or video track) became available. */
  onRemoteStream?: (stream: RemoteParticipantStream) => void;
  /** A remote stream was removed (participant left or track ended). */
  onRemoteStreamRemoved?: (streamId: string) => void;
  /** Active speaker list changed. `isPrimary` flags the loudest speaker. */
  onActiveSpeakers?: (speakers: Array<{ peerId: string; isPrimary: boolean }>) => void;
  onParticipantJoined?: (peerId: string, displayName: string) => void;
  onParticipantLeft?: (peerId: string) => void;
  /** Periodic quality metrics update (typically every 2 seconds). */
  onQualityMetrics?: (metrics: TransportMetrics) => void;
  /** High-level connection state change. */
  onConnectionStateChange?: (state: string) => void;
  /** A recoverable or fatal error occurred. */
  onError?: (error: TransportError) => void;
  /** Informational message for the user (e.g. "switching codec…"). */
  onInfo?: (message: string) => void;
}

// ─── Join options ───────────────────────────────────────────────────────────

export interface TransportJoinOptions {
  roomId: string;
  displayName: string;
  /**
   * WebSocket URL for WebRTC signaling, or HTTPS URL for WebTransport endpoint.
   * If omitted, the adapter will derive it from window.location.
   */
  signalingUrl?: string;
  /**
   * Custom ICE servers. Silently ignored by WebTransport adapters.
   */
  iceServers?: RTCIceServer[];
}

// ─── Core interface ──────────────────────────────────────────────────────────

export interface IMediaTransport {
  /**
   * Identifies the underlying transport technology.
   * Useful for diagnostics, feature-flag checks, and UI badges.
   */
  readonly transportType: 'webrtc' | 'webtransport';

  /**
   * Join a conference room and begin capturing/receiving media.
   * Returns the local MediaStream on success.
   */
  join(options: TransportJoinOptions): Promise<Result<MediaStream, TransportError>>;

  /**
   * Leave the room, stop all tracks, and release all transport resources.
   */
  leave(): Promise<Result<void, TransportError>>;

  /** Mute or unmute the local audio track without renegotiating. */
  setAudioEnabled(enabled: boolean): Result<void, TransportError>;

  /** Enable or disable the local video track without renegotiating. */
  setVideoEnabled(enabled: boolean): Result<void, TransportError>;

  /** Returns the current local MediaStream, or null if not joined. */
  getLocalStream(): MediaStream | null;

  /** Returns all currently active remote streams. */
  getRemoteStreams(): RemoteParticipantStream[];
}
