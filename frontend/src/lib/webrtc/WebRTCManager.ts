import {
  ConferenceOptions,
  MediaEngine,
  MediaEngineEvents,
  RemoteStream,
  VideoCodecPolicy,
} from './MediaEngine';
import { Result, err, ok } from './result';
import { WebRTCError, createWebRTCError } from './WebRTCError';
import { QualityMetrics } from './BitrateController';

export interface WebRTCManagerEvents {
  onRemoteStream?: (stream: RemoteStream) => void;
  onRemoteStreamRemoved?: (consumerId: string) => void;
  onActiveSpeakers?: (speakers: Array<{ peerId: string; isPrimary: boolean }>) => void;
  onParticipantJoined?: (peerId: string, displayName: string) => void;
  onParticipantLeft?: (peerId: string) => void;
  onQualityMetrics?: (metrics: QualityMetrics) => void;
  onConnectionStateChange?: (state: string) => void;
  onError?: (error: WebRTCError) => void;
  onInfo?: (message: string) => void;
  onCodecPolicyChanged?: (policy: VideoCodecPolicy) => void;
}

export interface WebRTCManagerOptions
  extends Omit<ConferenceOptions, 'videoCodecPolicy'> {
  initialVideoCodecPolicy?: VideoCodecPolicy;
  autoVp8Fallback?: boolean;
}

/**
 * Orchestrates MediaEngine lifecycle and automatic codec fallback.
 *
 * Behavior:
 * 1) Try balanced profile (VP8 + H264 baseline)
 * 2) If signaling rejects codec, retry with VP8-only policy
 */
export class WebRTCManager {
  private readonly baseOptions: Omit<ConferenceOptions, 'videoCodecPolicy'>;
  private readonly signalingUrlCandidates: string[];
  private readonly events: WebRTCManagerEvents;
  private readonly initialVideoCodecPolicy: VideoCodecPolicy;
  private readonly autoVp8Fallback: boolean;
  private readonly signalingRetryBaseDelayMs = 1_500;
  private readonly signalingRetryMaxDelayMs = 12_000;
  private readonly signalingRetryJitterMs = 900;
  private engine: MediaEngine | null = null;
  private codecPolicy: VideoCodecPolicy = 'balanced';

  constructor(options: WebRTCManagerOptions, events: WebRTCManagerEvents = {}) {
    const {
      initialVideoCodecPolicy = 'balanced',
      autoVp8Fallback = true,
      ...conferenceOptions
    } = options;

    this.initialVideoCodecPolicy = initialVideoCodecPolicy;
    this.autoVp8Fallback = autoVp8Fallback;
    this.baseOptions = {
      ...conferenceOptions,
      // Always keep working STUN defaults for public NAT traversal.
      // Runtime ICE from backend/env is additive and can append TURN.
      iceServers: WebRTCManager.buildMergedIceServers(conferenceOptions.iceServers),
    };
    this.signalingUrlCandidates = WebRTCManager.buildSignalingUrlCandidates(
      conferenceOptions.signalingUrl
    );
    this.events = events;
  }

  async join(): Promise<Result<MediaStream, WebRTCError>> {
    this.codecPolicy = this.initialVideoCodecPolicy;
    this.events.onCodecPolicyChanged?.(this.codecPolicy);
    const primaryResult = await this.joinWithPolicy(this.codecPolicy);
    if (primaryResult.ok) {
      return primaryResult;
    }

    const shouldRetryWithVp8 =
      this.autoVp8Fallback &&
      this.codecPolicy !== 'vp8-only' &&
      (
        primaryResult.error.code === 'SIGNALING_UNSUPPORTED_CODEC' ||
        primaryResult.error.code === 'NATIVE_SDP_REJECTION'
      );

    if (!shouldRetryWithVp8) {
      this.events.onError?.(primaryResult.error);
      return primaryResult;
    }

    this.events.onInfo?.('Оптимизация видеопотока (fallback на VP8)...');
    this.codecPolicy = 'vp8-only';
    this.events.onCodecPolicyChanged?.(this.codecPolicy);

    const leaveBeforeFallbackResult = await this.leave();
    if (!leaveBeforeFallbackResult.ok) {
      this.events.onError?.(leaveBeforeFallbackResult.error);
    }

    const fallbackResult = await this.joinWithPolicy(this.codecPolicy);
    if (!fallbackResult.ok) {
      this.events.onError?.(fallbackResult.error);
    }

    return fallbackResult;
  }

  async leave(): Promise<Result<void, WebRTCError>> {
    if (!this.engine) return ok(undefined);
    const leaveResult = await this.engine.leave();
    this.engine = null;
    return leaveResult;
  }

  setAudioEnabled(enabled: boolean): Result<void, WebRTCError> {
    if (!this.engine) {
      return err(
        createWebRTCError('TRANSPORT_SETUP_FAILURE', 'Media engine is not initialized', {
          retriable: true,
        })
      );
    }

    return this.engine.setAudioEnabled(enabled);
  }

  setVideoEnabled(enabled: boolean): Result<void, WebRTCError> {
    if (!this.engine) {
      return err(
        createWebRTCError('TRANSPORT_SETUP_FAILURE', 'Media engine is not initialized', {
          retriable: true,
        })
      );
    }

    return this.engine.setVideoEnabled(enabled);
  }

  getLocalStream(): MediaStream | null {
    return this.engine?.getLocalStream() || null;
  }

  getRemoteStreams(): RemoteStream[] {
    return this.engine?.getRemoteStreams() || [];
  }

  getCodecPolicy(): VideoCodecPolicy {
    return this.codecPolicy;
  }

  private async joinWithPolicy(
    policy: VideoCodecPolicy
  ): Promise<Result<MediaStream, WebRTCError>> {
    const leaveResult = await this.leave();
    if (!leaveResult.ok) {
      this.events.onError?.(leaveResult.error);
    }

    let lastFailure: Result<MediaStream, WebRTCError> | null = null;

    for (let idx = 0; idx < this.signalingUrlCandidates.length; idx += 1) {
      const signalingUrl = this.signalingUrlCandidates[idx];
      if (idx > 0) {
        this.events.onInfo?.(
          `Пробуем резервный signaling URL: ${signalingUrl}`
        );
      }

      const engine = new MediaEngine(
        {
          ...this.baseOptions,
          signalingUrl,
          videoCodecPolicy: policy,
        },
        this.buildEngineEvents()
      );

      this.engine = engine;
      const joinResult = await engine.join();

      if (joinResult.ok) {
        return joinResult;
      }

      lastFailure = joinResult;
      this.engine = null;

      const shouldTryNext =
        idx < this.signalingUrlCandidates.length - 1 &&
        (joinResult.error.code === 'SIGNALING_TIMEOUT' ||
          joinResult.error.code === 'SIGNALING_CONNECTION_FAILED');

      const cleanupResult = await engine.leave();
      if (!cleanupResult.ok) {
        this.events.onError?.(cleanupResult.error);
      }

      if (shouldTryNext) {
        const nextSignalingUrl = this.signalingUrlCandidates[idx + 1];
        await this.waitBeforeNextSignalingCandidate(idx, signalingUrl, nextSignalingUrl);
      }

      if (!shouldTryNext) {
        break;
      }
    }

    return (
      lastFailure ??
      err(
        createWebRTCError(
          'SIGNALING_CONNECTION_FAILED',
          'Failed to connect to signaling server',
          { retriable: true }
        )
      )
    );
  }

  private buildEngineEvents(): Partial<MediaEngineEvents> {
    return {
      onRemoteStream: (stream) => this.events.onRemoteStream?.(stream),
      onRemoteStreamRemoved: (consumerId) =>
        this.events.onRemoteStreamRemoved?.(consumerId),
      onActiveSpeakers: (speakers) => this.events.onActiveSpeakers?.(speakers),
      onParticipantJoined: (peerId, displayName) =>
        this.events.onParticipantJoined?.(peerId, displayName),
      onParticipantLeft: (peerId) => this.events.onParticipantLeft?.(peerId),
      onQualityMetrics: (metrics) => this.events.onQualityMetrics?.(metrics),
      onConnectionStateChange: (state) =>
        this.events.onConnectionStateChange?.(state),
      onInfo: (message) => this.events.onInfo?.(message),
      onError: (error) => this.events.onError?.(error),
    };
  }

  private static buildDefaultIceServers(): RTCIceServer[] {
    // Multiple STUN providers reduce ICE 701 lookup failures on broken IPv6 / virtual NIC setups.
    // TURN TCP/TLS fallback is critical for corporate firewalls blocking all outbound UDP.
    const defaultServers: RTCIceServer[] = [
      {
        urls: [
          'stun:stun.l.google.com:19302',
          'stun:stun1.l.google.com:19302',
        ],
      },
      {
        urls: ['stun:stun.cloudflare.com:3478'],
      },
      {
        urls: ['stun:global.stun.twilio.com:3478'],
      },
    ];

    // TURN relay fallback can be injected from runtime env (generic + provider-specific aliases):
    // Generic:
    // VITE_TURN_URLS="turn:global.turn.twilio.com:3478?transport=udp,turns:global.turn.twilio.com:443?transport=tcp"
    // VITE_TURN_USERNAME="<username>"
    // VITE_TURN_CREDENTIAL="<credential>"
    //
    // Twilio aliases:
    // VITE_TWILIO_TURN_URLS="turn:global.turn.twilio.com:3478?transport=udp,turns:global.turn.twilio.com:443?transport=tcp"
    // VITE_TWILIO_TURN_USERNAME="<username>"
    // VITE_TWILIO_TURN_CREDENTIAL="<credential>"
    //
    // Metered aliases:
    // VITE_METERED_TURN_URLS="turn:your-project.metered.live:80?transport=udp,turn:your-project.metered.live:443?transport=tcp,turns:your-project.metered.live:443?transport=tcp"
    // VITE_METERED_TURN_USERNAME="<username>"
    // VITE_METERED_TURN_CREDENTIAL="<credential>"
    const runtimeTurnServers = WebRTCManager.buildRuntimeTurnServers();
    if (runtimeTurnServers.length > 0) {
      defaultServers.push(...runtimeTurnServers);
    }

    return defaultServers;
  }

  private static buildMergedIceServers(customIceServers?: RTCIceServer[]): RTCIceServer[] {
    const defaults = WebRTCManager.buildDefaultIceServers();
    if (!customIceServers || customIceServers.length === 0) {
      return defaults;
    }

    return [...defaults, ...customIceServers];
  }

  private static buildRuntimeTurnServers(): RTCIceServer[] {
    const envCandidates: Array<{
      urls: string;
      username: string;
      credential: string;
    }> = [
      {
        urls: 'VITE_TURN_URLS',
        username: 'VITE_TURN_USERNAME',
        credential: 'VITE_TURN_CREDENTIAL',
      },
      {
        urls: 'VITE_TWILIO_TURN_URLS',
        username: 'VITE_TWILIO_TURN_USERNAME',
        credential: 'VITE_TWILIO_TURN_CREDENTIAL',
      },
      {
        urls: 'VITE_METERED_TURN_URLS',
        username: 'VITE_METERED_TURN_USERNAME',
        credential: 'VITE_METERED_TURN_CREDENTIAL',
      },
    ];

    const servers: RTCIceServer[] = [];
    const seenUrlKeys = new Set<string>();

    for (const candidate of envCandidates) {
      const server = WebRTCManager.buildRuntimeTurnServerFromEnv(
        candidate.urls,
        candidate.username,
        candidate.credential
      );
      if (!server) {
        continue;
      }

      const serverUrls = Array.isArray(server.urls) ? server.urls : [server.urls];
      const dedupeKey = serverUrls
        .map((value) => String(value || '').trim().toLowerCase())
        .filter(Boolean)
        .sort()
        .join('|');
      if (!dedupeKey || seenUrlKeys.has(dedupeKey)) {
        continue;
      }

      seenUrlKeys.add(dedupeKey);
      servers.push(server);
    }

    return servers;
  }

  private static buildRuntimeTurnServerFromEnv(
    urlsEnvKey: string,
    usernameEnvKey: string,
    credentialEnvKey: string
  ): RTCIceServer | null {
    const rawUrls = String((import.meta.env as Record<string, unknown>)?.[urlsEnvKey] || '').trim();
    if (!rawUrls) {
      return null;
    }

    const urls = rawUrls
      .split(',')
      .map((value) => value.trim())
      .filter(Boolean);
    if (urls.length === 0) {
      return null;
    }

    const envValues = import.meta.env as Record<string, unknown>;
    const username = String(envValues?.[usernameEnvKey] || '').trim();
    const credential = String(envValues?.[credentialEnvKey] || '').trim();

    const server: RTCIceServer = {
      urls: urls.length === 1 ? urls[0] : urls,
    };
    if (username) {
      server.username = username;
    }
    if (credential) {
      server.credential = credential;
    }
    return server;
  }

  private static buildSignalingUrlCandidates(primaryUrl: string): string[] {
    const normalizedPrimary = String(primaryUrl || '').trim();
    if (!normalizedPrimary) {
      // Preserve previous behavior: SignalingClient will build
      // ws(s)://<current-origin>/ws/sfu/ when URL is empty.
      return [''];
    }

    const candidates: string[] = [normalizedPrimary];

    if (typeof window === 'undefined') {
      return candidates;
    }

    try {
      const parsed = new URL(normalizedPrimary, window.location.origin);
      const normalizedPath = (parsed.pathname || '/').replace(/\/+$/, '') || '/';
      const shouldAddTrailingSlashVariant =
        normalizedPath === '/ws/sfu' || normalizedPath === '/ws/sfu/';

      if (shouldAddTrailingSlashVariant) {
        const fallback = new URL(parsed.toString());
        fallback.pathname = normalizedPath === '/ws/sfu' ? '/ws/sfu/' : '/ws/sfu';
        const fallbackUrl = fallback.toString();
        if (!candidates.includes(fallbackUrl)) {
          candidates.push(fallbackUrl);
        }
      }
    } catch {
      // Ignore malformed URL; primary candidate is still returned.
    }

    return candidates;
  }

  private async waitBeforeNextSignalingCandidate(
    failureIndex: number,
    failedUrl: string,
    nextUrl: string | undefined
  ): Promise<void> {
    if (!nextUrl) {
      return;
    }

    const exponentialDelay = Math.min(
      this.signalingRetryBaseDelayMs * Math.pow(2, failureIndex),
      this.signalingRetryMaxDelayMs
    );
    const jitter = Math.floor(Math.random() * this.signalingRetryJitterMs);
    const totalDelayMs = exponentialDelay + jitter;

    this.events.onInfo?.(
      `Signaling retry: ${failedUrl} недоступен, ждём ${totalDelayMs} мс перед переходом на ${nextUrl}`
    );

    await new Promise<void>((resolve) => {
      setTimeout(resolve, totalDelayMs);
    });
  }
}
