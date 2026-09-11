import {
  ChatMessagePayload,
  ConferenceOptions,
  PeerMediaState,
  MediaEngine,
  MediaEngineEvents,
  RemoteStream,
  VideoCodecPolicy,
} from './MediaEngine';
import { fallback } from '@/lib/fallback';
import { Result, err, ok } from './result';
import { WebRTCError, createWebRTCError } from './WebRTCError';
import { QualityMetrics } from './BitrateController';
import type { ISignalingClient } from './ISignalingClient';
import { WebTransportSignalingClient } from './WebTransportSignalingClient';
import i18next from '@/i18n';

export interface WebRTCManagerEvents {
  onRemoteStream?: (stream: RemoteStream) => void;
  onRemoteStreamRemoved?: (consumerId: string) => void;
  onActiveSpeakers?: (speakers: Array<{ peerId: string; isPrimary: boolean }>) => void;
  onParticipantJoined?: (peerId: string, displayName: string, isGuest: boolean) => void;
  onParticipantLeft?: (peerId: string) => void;
  onChatMessage?: (message: ChatMessagePayload) => void;
  onMediaState?: (state: PeerMediaState) => void;
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
  /**
   * QUIC-сигналинг. Если задан и браузер умеет WebTransport — пробуем его
   * первым, WebSocket остаётся запасным маршрутом (мост может быть не
   * поднят, UDP :4433 — прикрыт файрволом, сертификат — просрочен).
   */
  webTransport?: {
    url: string;
    /** Отпечатки самоподписанного сертификата (dev). */
    certificateHashes?: string[];
  };
}

/** Одна попытка подключения к сигналингу: транспорт + адрес. */
interface SignalingAttempt {
  label: string;
  signalingUrl: string;
  signalingFactory?: (url: string) => ISignalingClient;
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
  private readonly signalingAttempts: SignalingAttempt[];
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
      webTransport,
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
    this.signalingAttempts = WebRTCManager.buildSignalingAttempts(
      conferenceOptions.signalingUrl,
      webTransport,
      conferenceOptions.authToken,
      conferenceOptions.signalingFactory
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

    this.events.onInfo?.(i18next.t('conference.signaling.vp8Fallback'));
    // Участник видит «оптимизация», а на деле звонок уехал с аппаратного
    // H.264 на программный VP8: выше нагрузка на CPU, хуже картинка на слабых
    // машинах. Снаружи это выглядит как «что-то подтормаживает», и связать
    // одно с другим без этой строки невозможно.
    fallback('conference.codec.vp8_retry', null, {
      reason: 'основной кодек отвергнут — перезаходим на VP8',
      cause: primaryResult.error,
      context: { code: primaryResult.error.code, from: this.codecPolicy },
    });
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

  /** Объявить своё состояние микрофона и камеры остальным участникам. */
  sendMediaState(state: { micEnabled: boolean; camEnabled: boolean }): Result<void, WebRTCError> {
    if (!this.engine) {
      return err(
        createWebRTCError('TRANSPORT_SETUP_FAILURE', 'Media engine is not initialized', {
          retriable: true,
        })
      );
    }
    return this.engine.sendMediaState(state);
  }

  /** Отправить сообщение в чат комнаты (релей через SFU). */
  sendChatMessage(text: string): Result<void, WebRTCError> {
    if (!this.engine) {
      return err(
        createWebRTCError('TRANSPORT_SETUP_FAILURE', 'Media engine is not initialized', {
          retriable: true,
        })
      );
    }
    return this.engine.sendChatMessage(text);
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

    for (let idx = 0; idx < this.signalingAttempts.length; idx += 1) {
      const attempt = this.signalingAttempts[idx];
      if (idx > 0) {
        this.events.onInfo?.(
          i18next.t('conference.signaling.tryingBackup', { label: attempt.label })
        );
      }

      const engine = new MediaEngine(
        {
          ...this.baseOptions,
          signalingUrl: attempt.signalingUrl,
          signalingFactory: attempt.signalingFactory,
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
        idx < this.signalingAttempts.length - 1 &&
        (joinResult.error.code === 'SIGNALING_TIMEOUT' ||
          joinResult.error.code === 'SIGNALING_CONNECTION_FAILED');

      const cleanupResult = await engine.leave();
      if (!cleanupResult.ok) {
        this.events.onError?.(cleanupResult.error);
      }

      if (shouldTryNext) {
        const nextAttempt = this.signalingAttempts[idx + 1];
        // expected: откат WebTransport → WebSocket заложен в архитектуру
        // (см. CLAUDE.md), и на локальной машине QUIC отваливается штатно —
        // строгий режим не должен из-за этого запирать конференцию. Но в
        // телеметрию событие идёт: если откатываются ВСЕ, значит QUIC-мост
        // лежит, а снаружи это видно только по лишним секундам на входе.
        fallback('conference.signaling.next_channel', null, {
          reason: 'канал сигналинга не поднялся — переходим на резервный',
          expected: true,
          cause: joinResult.error,
          context: {
            failed: attempt.label,
            next: nextAttempt.label,
            code: joinResult.error.code,
          },
        });
        await this.waitBeforeNextSignalingCandidate(
          idx,
          attempt.label,
          nextAttempt.label
        );
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
      onParticipantJoined: (peerId, displayName, isGuest) =>
        this.events.onParticipantJoined?.(peerId, displayName, isGuest),
      onParticipantLeft: (peerId) => this.events.onParticipantLeft?.(peerId),
      onChatMessage: (message) => this.events.onChatMessage?.(message),
      onMediaState: (state) => this.events.onMediaState?.(state),
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

  /**
   * Порядок попыток подключения: сначала QUIC (если настроен и поддержан),
   * затем WebSocket-кандидаты. Явно переданная фабрика (тесты, ручная
   * инъекция транспорта) отключает автоподбор и используется как есть.
   */
  private static buildSignalingAttempts(
    signalingUrl: string,
    webTransport: WebRTCManagerOptions['webTransport'],
    authToken: ConferenceOptions['authToken'],
    explicitFactory: ConferenceOptions['signalingFactory']
  ): SignalingAttempt[] {
    const wsAttempts: SignalingAttempt[] = WebRTCManager
      .buildSignalingUrlCandidates(signalingUrl)
      .map((url) => ({
        label: `WebSocket ${url || '(origin)'}`,
        signalingUrl: url,
        signalingFactory: explicitFactory,
      }));

    if (explicitFactory) {
      return wsAttempts;
    }

    const wtUrl = String(webTransport?.url || '').trim();
    const wtSupported = typeof window !== 'undefined' && 'WebTransport' in window;
    if (!wtUrl || !wtSupported) {
      if (wtUrl && !wtSupported) {
        console.info('[WebRTC] WebTransport не поддержан браузером — сигналинг по WebSocket');
      }
      return wsAttempts;
    }

    const certificateHashes = webTransport?.certificateHashes;
    return [
      {
        label: `WebTransport ${wtUrl}`,
        signalingUrl: wtUrl,
        signalingFactory: () =>
          new WebTransportSignalingClient(wtUrl, { authToken, certificateHashes }),
      },
      ...wsAttempts,
    ];
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
        // Переименовано из `fallback`, чтобы не затенять импорт одноимённой
        // функции: здесь это просто второе написание того же адреса.
        const variant = new URL(parsed.toString());
        variant.pathname = normalizedPath === '/ws/sfu' ? '/ws/sfu/' : '/ws/sfu';
        const variantUrl = variant.toString();
        if (!candidates.includes(variantUrl)) {
          candidates.push(variantUrl);
        }
      }
    } catch {
      // Ignore malformed URL; primary candidate is still returned.
    }

    return candidates;
  }

  private async waitBeforeNextSignalingCandidate(
    failureIndex: number,
    failedLabel: string,
    nextLabel: string | undefined
  ): Promise<void> {
    if (!nextLabel) {
      return;
    }

    const exponentialDelay = Math.min(
      this.signalingRetryBaseDelayMs * Math.pow(2, failureIndex),
      this.signalingRetryMaxDelayMs
    );
    const jitter = Math.floor(Math.random() * this.signalingRetryJitterMs);
    const totalDelayMs = exponentialDelay + jitter;

    this.events.onInfo?.(
      i18next.t('conference.signaling.retry', { failed: failedLabel, delay: totalDelayMs, next: nextLabel })
    );

    await new Promise<void>((resolve) => {
      setTimeout(resolve, totalDelayMs);
    });
  }
}
