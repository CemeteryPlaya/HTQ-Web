/**
 * Unit tests for WebRTCAdapter
 *
 * Strategy: mock WebRTCManager entirely so we test only the adapter's
 * mapping / delegation logic — no real WebRTC or network traffic.
 *
 * Test coverage:
 *  ✓ Error-code mapping (all WebRTCErrorCode variants)
 *  ✓ join() — success path (local stream forwarded as-is)
 *  ✓ join() — failure path (error mapped, manager nulled)
 *  ✓ join() — cleans up previous session before reconnecting
 *  ✓ leave() — no-op when not connected
 *  ✓ leave() — maps error correctly
 *  ✓ setAudioEnabled / setVideoEnabled — returns notConnectedError when not joined
 *  ✓ setAudioEnabled / setVideoEnabled — success and failure paths
 *  ✓ getLocalStream() — returns null when not joined
 *  ✓ getRemoteStreams() — maps RemoteStream → RemoteParticipantStream
 *  ✓ Event delegation — all IMediaTransportEvents wired correctly
 *  ✓ transportType — always 'webrtc'
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { MockInstance } from 'vitest';

import { WebRTCAdapter } from './WebRTCAdapter';
import type { IMediaTransportEvents, RemoteParticipantStream, TransportMetrics } from './IMediaTransport';
import type { WebRTCManagerEvents, WebRTCManagerOptions } from '../webrtc/WebRTCManager';
import type { RemoteStream } from '../webrtc/MediaEngine';
import type { QualityMetrics } from '../webrtc/BitrateController';

// ─── MediaStream stub (jsdom doesn't implement it) ───────────────────────────

class StubMediaStream {
  readonly id = 'stub-stream-id';
  getTracks()       { return []; }
  getVideoTracks()  { return []; }
  getAudioTracks()  { return []; }
}

// ─── Mock WebRTCManager ───────────────────────────────────────────────────────

// Holds the events object that the adapter passed to the constructor.
// Tests can call captured events to simulate server-side pushes.
let capturedManagerEvents: Partial<WebRTCManagerEvents> = {};
let capturedManagerOptions: WebRTCManagerOptions | null = null;

const mockManagerInstance = {
  join:             vi.fn(),
  leave:            vi.fn(),
  setAudioEnabled:  vi.fn(),
  setVideoEnabled:  vi.fn(),
  getLocalStream:   vi.fn(),
  getRemoteStreams:  vi.fn(),
};

vi.mock('../webrtc/WebRTCManager', () => ({
  WebRTCManager: vi.fn((options: WebRTCManagerOptions, events: WebRTCManagerEvents) => {
    capturedManagerOptions = options;
    capturedManagerEvents  = events ?? {};
    return mockManagerInstance;
  }),
}));

// ─── Helpers ─────────────────────────────────────────────────────────────────

const JOIN_OPTIONS = {
  roomId:       'room-001',
  displayName:  'Test User',
  signalingUrl: 'wss://sfu.example.com/ws',
};

function makeWebRTCError(code: string, retriable = false) {
  return { code, message: `Error: ${code}`, retriable, details: undefined, cause: undefined };
}

function makeRemoteStream(overrides: Partial<RemoteStream> = {}): RemoteStream {
  return {
    peerId:      'peer-1',
    displayName: 'Alice',
    consumerId:  'consumer-abc',
    kind:        'video',
    track:       {} as MediaStreamTrack,
    stream:      new StubMediaStream() as unknown as MediaStream,
    ...overrides,
  };
}

function makeQualityMetrics(overrides: Partial<QualityMetrics> = {}): QualityMetrics {
  return {
    rttMs:                          42,
    packetLossRate:                 0.01,
    jitterMs:                       5,
    currentVideoBitrateBps:         1_200_000,
    currentAudioBitrateBps:         64_000,
    effectiveTargetVideoBitrateBps: 1_500_000,
    nominalTargetVideoBitrateBps:   1_500_000,
    starvationMode:                 false,
    codec:                          'VP8',
    width:                          1280,
    height:                         720,
    fps:                            30,
    ...overrides,
  };
}

// ─── Setup / Teardown ─────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks();
  capturedManagerEvents  = {};
  capturedManagerOptions = null;
  // Default: leave always succeeds
  mockManagerInstance.leave.mockResolvedValue({ ok: true, value: undefined });
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ═══════════════════════════════════════════════════════════════════════════════
// transportType
// ═══════════════════════════════════════════════════════════════════════════════

describe('transportType', () => {
  it('is always "webrtc"', () => {
    const adapter = new WebRTCAdapter();
    expect(adapter.transportType).toBe('webrtc');
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// join()
// ═══════════════════════════════════════════════════════════════════════════════

describe('join()', () => {
  it('returns the local MediaStream on success', async () => {
    const stream = new StubMediaStream() as unknown as MediaStream;
    mockManagerInstance.join.mockResolvedValue({ ok: true, value: stream });

    const adapter = new WebRTCAdapter();
    const result  = await adapter.join(JOIN_OPTIONS);

    expect(result.ok).toBe(true);
    if (result.ok) expect(result.value).toBe(stream);
  });

  it('passes roomId, displayName, signalingUrl to WebRTCManager', async () => {
    mockManagerInstance.join.mockResolvedValue({ ok: true, value: new StubMediaStream() });

    const adapter = new WebRTCAdapter();
    await adapter.join(JOIN_OPTIONS);

    expect(capturedManagerOptions).toMatchObject({
      roomId:       JOIN_OPTIONS.roomId,
      displayName:  JOIN_OPTIONS.displayName,
      signalingUrl: JOIN_OPTIONS.signalingUrl,
    });
  });

  it('passes custom iceServers to WebRTCManager when provided', async () => {
    mockManagerInstance.join.mockResolvedValue({ ok: true, value: new StubMediaStream() });
    const iceServers = [{ urls: 'stun:custom.stun.com:3478' }];

    await new WebRTCAdapter().join({ ...JOIN_OPTIONS, iceServers });

    expect(capturedManagerOptions).toMatchObject({ iceServers });
  });

  it('maps WebRTC error to TransportError on failure', async () => {
    mockManagerInstance.join.mockResolvedValue({
      ok:    false,
      error: makeWebRTCError('SIGNALING_CONNECTION_FAILED', true),
    });

    const adapter = new WebRTCAdapter();
    const result  = await adapter.join(JOIN_OPTIONS);

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.code).toBe('CONNECTION_FAILED');
      expect(result.error.retriable).toBe(true);
    }
  });

  it('cleans up previous session before reconnecting', async () => {
    const stream = new StubMediaStream() as unknown as MediaStream;
    mockManagerInstance.join.mockResolvedValue({ ok: true, value: stream });

    const adapter = new WebRTCAdapter();
    // First join
    await adapter.join(JOIN_OPTIONS);
    // Second join should trigger leave() on previous manager
    await adapter.join(JOIN_OPTIONS);

    // leave() on the first manager must have been called once during the second join
    expect(mockManagerInstance.leave).toHaveBeenCalledTimes(1);
  });

  it('nulls the internal manager after a failed join', async () => {
    mockManagerInstance.join.mockResolvedValue({
      ok:    false,
      error: makeWebRTCError('MEDIA_CAPTURE_FAILURE'),
    });

    const adapter = new WebRTCAdapter();
    await adapter.join(JOIN_OPTIONS);

    // getLocalStream() must return null — no dangling manager reference
    expect(adapter.getLocalStream()).toBeNull();
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// leave()
// ═══════════════════════════════════════════════════════════════════════════════

describe('leave()', () => {
  it('returns ok(undefined) when not connected', async () => {
    const result = await new WebRTCAdapter().leave();
    expect(result.ok).toBe(true);
  });

  it('delegates to manager.leave() and returns ok on success', async () => {
    mockManagerInstance.join.mockResolvedValue({ ok: true, value: new StubMediaStream() });

    const adapter = new WebRTCAdapter();
    await adapter.join(JOIN_OPTIONS);
    const result = await adapter.leave();

    expect(result.ok).toBe(true);
    expect(mockManagerInstance.leave).toHaveBeenCalledTimes(1);
  });

  it('maps manager.leave() error to TransportError', async () => {
    mockManagerInstance.join.mockResolvedValue({ ok: true, value: new StubMediaStream() });
    mockManagerInstance.leave.mockResolvedValue({
      ok:    false,
      error: makeWebRTCError('TRANSPORT_SETUP_FAILURE'),
    });

    const adapter = new WebRTCAdapter();
    await adapter.join(JOIN_OPTIONS);
    const result = await adapter.leave();

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.code).toBe('CONNECTION_FAILED');
  });

  it('nulls the manager after leave so subsequent calls return no-op', async () => {
    mockManagerInstance.join.mockResolvedValue({ ok: true, value: new StubMediaStream() });

    const adapter = new WebRTCAdapter();
    await adapter.join(JOIN_OPTIONS);
    await adapter.leave();

    // Second leave() must not call manager.leave() again
    mockManagerInstance.leave.mockClear();
    await adapter.leave();
    expect(mockManagerInstance.leave).not.toHaveBeenCalled();
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// setAudioEnabled() / setVideoEnabled()
// ═══════════════════════════════════════════════════════════════════════════════

describe('setAudioEnabled()', () => {
  it('returns CONNECTION_FAILED error when not connected', () => {
    const result = new WebRTCAdapter().setAudioEnabled(true);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.code).toBe('CONNECTION_FAILED');
  });

  it('returns ok on success', async () => {
    mockManagerInstance.join.mockResolvedValue({ ok: true, value: new StubMediaStream() });
    mockManagerInstance.setAudioEnabled.mockReturnValue({ ok: true, value: undefined });

    const adapter = new WebRTCAdapter();
    await adapter.join(JOIN_OPTIONS);
    const result = adapter.setAudioEnabled(false);

    expect(result.ok).toBe(true);
    expect(mockManagerInstance.setAudioEnabled).toHaveBeenCalledWith(false);
  });

  it('maps manager error to TransportError', async () => {
    mockManagerInstance.join.mockResolvedValue({ ok: true, value: new StubMediaStream() });
    mockManagerInstance.setAudioEnabled.mockReturnValue({
      ok:    false,
      error: makeWebRTCError('TRANSPORT_SETUP_FAILURE'),
    });

    const adapter = new WebRTCAdapter();
    await adapter.join(JOIN_OPTIONS);
    const result = adapter.setAudioEnabled(true);

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.code).toBe('CONNECTION_FAILED');
  });
});

describe('setVideoEnabled()', () => {
  it('returns CONNECTION_FAILED error when not connected', () => {
    const result = new WebRTCAdapter().setVideoEnabled(true);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.code).toBe('CONNECTION_FAILED');
  });

  it('returns ok on success', async () => {
    mockManagerInstance.join.mockResolvedValue({ ok: true, value: new StubMediaStream() });
    mockManagerInstance.setVideoEnabled.mockReturnValue({ ok: true, value: undefined });

    const adapter = new WebRTCAdapter();
    await adapter.join(JOIN_OPTIONS);
    const result = adapter.setVideoEnabled(false);

    expect(result.ok).toBe(true);
    expect(mockManagerInstance.setVideoEnabled).toHaveBeenCalledWith(false);
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// getLocalStream() / getRemoteStreams()
// ═══════════════════════════════════════════════════════════════════════════════

describe('getLocalStream()', () => {
  it('returns null when not connected', () => {
    expect(new WebRTCAdapter().getLocalStream()).toBeNull();
  });

  it('delegates to manager.getLocalStream() after join', async () => {
    const stream = new StubMediaStream() as unknown as MediaStream;
    mockManagerInstance.join.mockResolvedValue({ ok: true, value: stream });
    mockManagerInstance.getLocalStream.mockReturnValue(stream);

    const adapter = new WebRTCAdapter();
    await adapter.join(JOIN_OPTIONS);

    expect(adapter.getLocalStream()).toBe(stream);
  });
});

describe('getRemoteStreams()', () => {
  it('returns empty array when not connected', () => {
    expect(new WebRTCAdapter().getRemoteStreams()).toEqual([]);
  });

  it('maps RemoteStream.consumerId to RemoteParticipantStream.streamId', async () => {
    const raw = makeRemoteStream({ consumerId: 'consumer-xyz', peerId: 'peer-2' });
    mockManagerInstance.join.mockResolvedValue({ ok: true, value: new StubMediaStream() });
    mockManagerInstance.getRemoteStreams.mockReturnValue([raw]);

    const adapter = new WebRTCAdapter();
    await adapter.join(JOIN_OPTIONS);

    const [mapped] = adapter.getRemoteStreams();
    expect(mapped.streamId).toBe('consumer-xyz');
    expect(mapped.peerId).toBe('peer-2');
  });

  it('preserves kind, track, stream, displayName', async () => {
    const track  = {} as MediaStreamTrack;
    const stream = new StubMediaStream() as unknown as MediaStream;
    const raw    = makeRemoteStream({ kind: 'audio', track, stream, displayName: 'Bob' });
    mockManagerInstance.join.mockResolvedValue({ ok: true, value: new StubMediaStream() });
    mockManagerInstance.getRemoteStreams.mockReturnValue([raw]);

    const adapter = new WebRTCAdapter();
    await adapter.join(JOIN_OPTIONS);

    const [mapped] = adapter.getRemoteStreams();
    expect(mapped.kind).toBe('audio');
    expect(mapped.track).toBe(track);
    expect(mapped.stream).toBe(stream);
    expect(mapped.displayName).toBe('Bob');
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// Event delegation
// ═══════════════════════════════════════════════════════════════════════════════

describe('event delegation', () => {
  async function joinedAdapter(events: IMediaTransportEvents) {
    mockManagerInstance.join.mockResolvedValue({ ok: true, value: new StubMediaStream() });
    const adapter = new WebRTCAdapter(events);
    await adapter.join(JOIN_OPTIONS);
    return adapter;
  }

  it('onRemoteStream fires with mapped RemoteParticipantStream', async () => {
    const onRemoteStream = vi.fn<[RemoteParticipantStream], void>();
    await joinedAdapter({ onRemoteStream });

    const raw = makeRemoteStream({ consumerId: 'consumer-1' });
    capturedManagerEvents.onRemoteStream?.(raw);

    expect(onRemoteStream).toHaveBeenCalledTimes(1);
    const arg = onRemoteStream.mock.calls[0][0];
    expect(arg.streamId).toBe('consumer-1');
  });

  it('onRemoteStreamRemoved forwards streamId unchanged', async () => {
    const onRemoteStreamRemoved = vi.fn<[string], void>();
    await joinedAdapter({ onRemoteStreamRemoved });

    capturedManagerEvents.onRemoteStreamRemoved?.('consumer-42');

    expect(onRemoteStreamRemoved).toHaveBeenCalledWith('consumer-42');
  });

  it('onActiveSpeakers forwards speakers unchanged', async () => {
    const onActiveSpeakers = vi.fn();
    await joinedAdapter({ onActiveSpeakers });

    const speakers = [{ peerId: 'p1', isPrimary: true }];
    capturedManagerEvents.onActiveSpeakers?.(speakers);

    expect(onActiveSpeakers).toHaveBeenCalledWith(speakers);
  });

  it('onParticipantJoined forwards peerId and displayName', async () => {
    const onParticipantJoined = vi.fn();
    await joinedAdapter({ onParticipantJoined });

    capturedManagerEvents.onParticipantJoined?.('peer-99', 'Charlie');

    expect(onParticipantJoined).toHaveBeenCalledWith('peer-99', 'Charlie');
  });

  it('onParticipantLeft forwards peerId', async () => {
    const onParticipantLeft = vi.fn();
    await joinedAdapter({ onParticipantLeft });

    capturedManagerEvents.onParticipantLeft?.('peer-99');

    expect(onParticipantLeft).toHaveBeenCalledWith('peer-99');
  });

  it('onQualityMetrics fires with mapped TransportMetrics', async () => {
    const onQualityMetrics = vi.fn<[TransportMetrics], void>();
    await joinedAdapter({ onQualityMetrics });

    const raw = makeQualityMetrics({ rttMs: 99, codec: 'H264' });
    capturedManagerEvents.onQualityMetrics?.(raw);

    expect(onQualityMetrics).toHaveBeenCalledTimes(1);
    const arg = onQualityMetrics.mock.calls[0][0];
    expect(arg.rttMs).toBe(99);
    expect(arg.codec).toBe('H264');
    expect(arg.effectiveTargetVideoBitrateBps).toBe(raw.effectiveTargetVideoBitrateBps);
  });

  it('onConnectionStateChange forwards state string', async () => {
    const onConnectionStateChange = vi.fn();
    await joinedAdapter({ onConnectionStateChange });

    capturedManagerEvents.onConnectionStateChange?.('connected');

    expect(onConnectionStateChange).toHaveBeenCalledWith('connected');
  });

  it('onError fires with mapped TransportError', async () => {
    const onError = vi.fn();
    await joinedAdapter({ onError });

    capturedManagerEvents.onError?.(makeWebRTCError('ICE_GATHERING_FAILURE', true) as any);

    expect(onError).toHaveBeenCalledTimes(1);
    const arg = onError.mock.calls[0][0];
    expect(arg.code).toBe('CONNECTION_FAILED');
    expect(arg.retriable).toBe(true);
  });

  it('onInfo forwards message string', async () => {
    const onInfo = vi.fn();
    await joinedAdapter({ onInfo });

    capturedManagerEvents.onInfo?.('switching codec...');

    expect(onInfo).toHaveBeenCalledWith('switching codec...');
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// Error code mapping table
// ═══════════════════════════════════════════════════════════════════════════════

describe('WebRTC error code mapping', () => {
  const TABLE: Array<[string, string]> = [
    ['SIGNALING_CONNECTION_FAILED', 'CONNECTION_FAILED'],
    ['SIGNALING_PROTOCOL_ERROR',    'CONNECTION_FAILED'],
    ['SIGNALING_TIMEOUT',           'CONNECTION_TIMEOUT'],
    ['SIGNALING_REQUEST_FAILED',    'CONNECTION_FAILED'],
    ['SIGNALING_UNSUPPORTED_CODEC', 'UNSUPPORTED_CODEC'],
    ['NATIVE_SDP_REJECTION',        'UNSUPPORTED_CODEC'],
    ['ICE_GATHERING_FAILURE',       'CONNECTION_FAILED'],
    ['MEDIA_CAPTURE_FAILURE',       'MEDIA_CAPTURE_FAILURE'],
    ['TRANSPORT_SETUP_FAILURE',     'CONNECTION_FAILED'],
    ['UNKNOWN',                     'UNKNOWN'],
  ];

  it.each(TABLE)('%s → %s', async (webrtcCode, expectedTransportCode) => {
    mockManagerInstance.join.mockResolvedValue({
      ok:    false,
      error: makeWebRTCError(webrtcCode, false),
    });

    const result = await new WebRTCAdapter().join(JOIN_OPTIONS);

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.code).toBe(expectedTransportCode);
  });
});
