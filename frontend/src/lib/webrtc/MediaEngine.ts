/**
 * Media Engine — Result-based WebRTC pipeline with codec hardening.
 *
 * Key safety features:
 * - No throw-based API on join path (Result<T, WebRTCError> only).
 * - Proactive codec filtering with RTCRtpSender.getCapabilities + setCodecPreferences.
 * - Stable video codec policy: VP8 + H264 Baseline only.
 */

import { SignalingClient } from './SignalingClient';
import type { ISignalingClient } from './ISignalingClient';
import { BitrateController, QualityMetrics } from './BitrateController';
// Removed SdpMunger dependencies for bitrate tuning
import {
  AUDIO_TARGET_BITRATE_BPS,
  TARGET_FPS,
  VIDEO_TARGET_BITRATE_BPS,
  VIDEO_TARGET_HEIGHT,
  VIDEO_TARGET_WIDTH,
} from './qualityProfile';
import { Result, err, ok } from './result';
import {
  WebRTCError,
  createWebRTCError,
  webRTCErrorFromUnknown,
} from './WebRTCError';

// ═══════════════════════════════════════════════════════════
// Types
// ═══════════════════════════════════════════════════════════

export type VideoCodecPolicy = 'balanced' | 'vp8-only';

export interface ConferenceOptions {
  signalingUrl: string;
  roomId: string;
  displayName: string;
  videoCodecPolicy?: VideoCodecPolicy;
  iceServers?: RTCIceServer[];
  /**
   * Optional factory that returns a custom signaling client.
   * When provided, the engine uses it instead of the default WebSocket-based SignalingClient.
   * Use this to inject WebTransportSignalingClient for QUIC-based signaling.
   */
  signalingFactory?: (url: string) => ISignalingClient;
}

export interface RemoteStream {
  peerId: string;
  displayName: string;
  consumerId: string;
  kind: 'audio' | 'video';
  track: MediaStreamTrack;
  stream: MediaStream;
}

export interface MediaEngineEvents {
  onRemoteStream: (stream: RemoteStream) => void;
  onRemoteStreamRemoved: (consumerId: string) => void;
  onActiveSpeakers: (speakers: Array<{ peerId: string; isPrimary: boolean }>) => void;
  onParticipantJoined: (peerId: string, displayName: string) => void;
  onParticipantLeft: (peerId: string) => void;
  onQualityMetrics: (metrics: QualityMetrics) => void;
  onConnectionStateChange: (state: string) => void;
  onInfo: (message: string) => void;
  onError: (error: WebRTCError) => void;
}

interface JoinRoomResult {
  routerRtpCapabilities: any;
  participants: Array<{ peerId: string; displayName: string }>;
  turnConfig?: TurnConfig;
}

interface CreateTransportResult {
  id: string;
  iceParameters: RTCIceParameters;
  iceCandidates: RTCIceCandidate[];
  dtlsParameters: RTCDtlsParameters;
}

interface TurnConfig {
  urls?: string[];
  url?: string;
  username?: string;
  credential?: string;
}

interface NewConsumerEvent {
  consumerId: string;
  producerId?: string;
  kind: 'audio' | 'video';
  rtpParameters: any;
  peerId: string;
  displayName: string;
}

interface ActiveConsumerEntry {
  consumerId: string;
  mid: string;
  kind: 'audio' | 'video';
  rtpParameters: any;
  peerId: string;
  displayName: string;
}

type LeaveTrigger = 'manual' | 'pagehide' | 'beforeunload';

// ═══════════════════════════════════════════════════════════
// Virtual-network subnet classification (RFC 1918, CGNAT, Hamachi, WSL)
// ═══════════════════════════════════════════════════════════

interface Ipv4Cidr {
  readonly base: number;
  readonly mask: number;
  readonly label: string;
}

function parseIpv4(ip: string): number | null {
  const parts = ip.split('.');
  if (parts.length !== 4) return null;
  let result = 0;
  for (const part of parts) {
    const n = Number(part);
    if (!Number.isInteger(n) || n < 0 || n > 255) return null;
    result = (result << 8) | n;
  }
  return result >>> 0; // unsigned 32-bit
}

function cidr(base: string, prefix: number, label: string): Ipv4Cidr {
  const parsed = parseIpv4(base);
  if (parsed === null) throw new Error(`Invalid CIDR base: ${base}`);
  return { base: parsed >>> 0, mask: (~0 << (32 - prefix)) >>> 0, label };
}

/**
 * Known virtual/mesh network CIDRs where ICE gathering failures
 * are expected and non-actionable.
 *
 * - 25.0.0.0/8, 26.0.0.0/8  — Hamachi VPN
 * - 100.64.0.0/10            — CGNAT (RFC 6598), used by Tailscale
 * - 172.16.0.0/12            — RFC 1918 private, often WSL / Docker
 * - 198.18.0.0/15            — RFC 2544 benchmarking, used by some VPNs
 * - fd00::/8 is IPv6 ULA, handled separately via the existing IPv6 filter.
 */
const VIRTUAL_NETWORK_CIDRS: readonly Ipv4Cidr[] = [
  cidr('25.0.0.0', 8, 'Hamachi'),
  cidr('26.0.0.0', 8, 'Hamachi'),
  cidr('100.64.0.0', 10, 'CGNAT/Tailscale'),
  cidr('172.16.0.0', 12, 'Private/WSL'),
  cidr('198.18.0.0', 15, 'Benchmarking/VPN'),
];

/**
 * Returns the label of the matching virtual network CIDR, or null if
 * the address does not belong to any known VPN/mesh subnet.
 */
export function classifyVirtualNetwork(address: string | null | undefined): string | null {
  if (!address) return null;
  const ip = parseIpv4(address);
  if (ip === null) return null;
  for (const { base, mask, label } of VIRTUAL_NETWORK_CIDRS) {
    if ((ip & mask) === (base & mask)) return label;
  }
  return null;
}

// ═══════════════════════════════════════════════════════════
// MediaEngine Class
// ═══════════════════════════════════════════════════════════

export class MediaEngine {
  private static readonly DEFAULT_ICE_SERVERS: RTCIceServer[] = [
    {
      urls: [
        'stun:stun.l.google.com:19302',
        'stun:stun1.l.google.com:19302',
        'stun:stun2.l.google.com:19302',
        'stun:stun3.l.google.com:19302',
        'stun:stun4.l.google.com:19302',
      ],
    },
    {
      urls: ['stun:stun.cloudflare.com:3478'],
    },
    {
      urls: ['stun:global.stun.twilio.com:3478'],
    },
    // DNS-independent IP-based STUN fallback servers.
    // These ensure ICE gathering succeeds even when the system DNS resolver
    // is broken (e.g. split-tunnel VPNs, corporate proxies, NXDOMAIN hijacking).
    // Google STUN (74.125.250.129) and Cloudflare STUN (162.159.200.1) are
    // long-lived anycast IPs unlikely to change.
    {
      urls: [
        'stun:74.125.250.129:19302',  // Google STUN (anycast)
        'stun:162.159.200.1:3478',     // Cloudflare STUN (anycast)
      ],
    },
    // TURN relay fallback — critical for corporate firewalls blocking UDP.
    // Do NOT hardcode credentials here.
    // Instead, the SFU server pushes valid TURN config via joinRoom → turnConfig.
    // Users can also pass custom TURN servers via ConferenceOptions.iceServers.
  ];

  /** Wait a few seconds for direct ICE candidates before forcing relay-only mode. */
  private static readonly DIRECT_ICE_CANDIDATE_TIMEOUT_MS = 3500;

  /** Maximum number of automatic ICE restart attempts before giving up. */
  private static readonly MAX_ICE_RESTART_ATTEMPTS = 3;

  /** Number of retries for resumeConsumer after SDP is fully applied. */
  private static readonly RESUME_CONSUMER_MAX_ATTEMPTS = 3;

  /** Delay between resumeConsumer retries (network/signaling race window). */
  private static readonly RESUME_CONSUMER_RETRY_DELAY_MS = 250;

  /** Media validation timeout budgets before adding tracks to PeerConnection. */
  private static readonly MEDIA_VALIDATION_TIMEOUT_MS = 1600;
  private static readonly MEDIA_PROBE_SAMPLE_COUNT = 6;

  /** Tracks automatic ICE restart attempts per PeerConnection. */
  private iceRestartAttempts: Map<RTCPeerConnection, number> = new Map();
  private iceRestartInProgress: Set<RTCPeerConnection> = new Set();
  private relayFallbackTimers: Map<RTCPeerConnection, ReturnType<typeof setTimeout>> = new Map();
  private disconnectedRecoveryTimers: Map<RTCPeerConnection, ReturnType<typeof setTimeout>> = new Map();
  private pcHasTurnServer: Map<RTCPeerConnection, boolean> = new Map();
  private gatheredCandidateCounts: Map<RTCPeerConnection, number> = new Map();
  private directCandidateDiscovered: Map<RTCPeerConnection, boolean> = new Map();
  private publicSrflxCandidateDiscovered: Map<RTCPeerConnection, boolean> = new Map();
  private warnedAboutMissingPublicSrflx: Map<RTCPeerConnection, boolean> = new Map();
  private relayPolicyForced: Map<RTCPeerConnection, boolean> = new Map();
  private announcedPublicSrflx = false;
  private warnedAboutPrivateSfuCandidates = false;
  private loggedPlaceholderIceUrls: Set<string> = new Set();
  private pageLifecycleHandlersAttached = false;
  private isLeaving = false;
  private readonly handlePageHide = (): void => {
    this.leaveFastPath('pagehide');
  };
  private readonly handleBeforeUnload = (): void => {
    this.leaveFastPath('beforeunload');
  };

  private signaling: ISignalingClient;
  private events: Partial<MediaEngineEvents>;
  private options: ConferenceOptions;

  private sharedCertificate: RTCCertificate | null = null;
  private sendPc: RTCPeerConnection | null = null;
  private recvPc: RTCPeerConnection | null = null;
  private sendTransportId: string | null = null;
  private sendTransportData: CreateTransportResult | null = null;
  private recvTransportId: string | null = null;

  private localStream: MediaStream | null = null;
  private remoteStreams: Map<string, RemoteStream> = new Map();
  private bitrateController: BitrateController | null = null;

  private joined = false;
  private videoCodecPolicy: VideoCodecPolicy;

  private routerAudioCodecs: Set<string> = new Set();
  private routerVideoCodecs: Set<string> = new Set();
  private routerH264Profiles: Set<string> = new Set();
  private routerHeaderExtensionUris: Set<string> = new Set();

  // ── Receive transport state ──
  private recvTransportConnected = false;
  private recvTransportData: CreateTransportResult | null = null;
  private nextRecvMid = 0;
  private canProcessConsumers = false;
  private consumerQueue: NewConsumerEvent[] = [];
  private queuedConsumerIds: Set<string> = new Set();
  private consumerQueueDrainPromise: Promise<void> | null = null;
  private recvPipelineWaiters: Set<() => void> = new Set();
  private activeConsumers: Map<string, ActiveConsumerEntry> = new Map();
  // Stable ordered history of all m-lines ever negotiated on recvPc.
  // Entries are never removed, only marked inactive. This guarantees
  // subsequent SDP re-offers keep m-lines in the original order
  // (Chrome rejects re-offers where m-line order changes).
  private recvMLineHistory: Array<{
    mid: string;
    kind: 'audio' | 'video';
    consumerId: string;
    rtpParameters: any;
    active: boolean;
  }> = [];
  private recvNegotiationLock: Promise<void> = Promise.resolve();
  private hardRejectedRecvMids: Set<string> = new Set();
  private readonly recvDiagEnabled = this.resolveRecvDiagnosticsEnabled();
  private readonly iceDiagEnabled = this.resolveIceDiagnosticsEnabled();
  private readonly expectsPublicSrflxCandidate = this.resolvePublicSrflxExpectation();

  constructor(options: ConferenceOptions, events: Partial<MediaEngineEvents> = {}) {
    this.options = options;
    this.events = events;
    this.signaling = options.signalingFactory
      ? options.signalingFactory(options.signalingUrl)
      : new SignalingClient(options.signalingUrl);
    this.videoCodecPolicy = options.videoCodecPolicy || 'balanced';
  }

  setVideoCodecPolicy(policy: VideoCodecPolicy): void {
    this.videoCodecPolicy = policy;
  }

  getVideoCodecPolicy(): VideoCodecPolicy {
    return this.videoCodecPolicy;
  }

  private resolveRecvDiagnosticsEnabled(): boolean {
    return this.resolveDiagnosticFlag(['webrtcDiag', 'webrtcRecvDiag']);
  }

  private resolveIceDiagnosticsEnabled(): boolean {
    return this.resolveDiagnosticFlag(['webrtcDiag', 'webrtcIceDiag']);
  }

  private resolvePublicSrflxExpectation(): boolean {
    if (typeof window === 'undefined') {
      return false;
    }

    const host = String(window.location.hostname || '').trim().toLowerCase();
    if (!host) {
      return false;
    }

    if (this.isKnownTunnelHost(host)) {
      return true;
    }

    return !this.isLocalOrPrivateHost(host);
  }

  private resolveDiagnosticFlag(keys: string[]): boolean {
    if (typeof window === 'undefined') {
      return false;
    }

    try {
      const query = new URLSearchParams(window.location.search);
      for (const key of keys) {
        const fromQuery = query.get(key);
        if (fromQuery === '1' || fromQuery === 'true') {
          return true;
        }

        const fromStorage = window.localStorage?.getItem(key);
        if (fromStorage === '1' || fromStorage === 'true') {
          return true;
        }
      }
    } catch {
      // Diagnostics are optional. Ignore storage/query parsing errors.
    }

    return false;
  }

  private isKnownTunnelHost(hostname: string): boolean {
    const normalized = hostname.trim().toLowerCase();
    return (
      normalized.endsWith('.instatunnel.my') ||
      normalized.endsWith('.ngrok-free.app') ||
      normalized.endsWith('.ngrok-free.dev') ||
      normalized.endsWith('.ngrok.app') ||
      normalized.endsWith('.ngrok.io')
    );
  }

  private isLocalOrPrivateHost(hostname: string): boolean {
    const normalized = hostname.trim().toLowerCase().replace(/^\[|\]$/g, '');
    if (!normalized) {
      return true;
    }
    if (normalized === 'localhost' || normalized === '::1' || normalized.endsWith('.localhost')) {
      return true;
    }
    if (normalized.endsWith('.local')) {
      return true;
    }
    return this.isPrivateOrLoopbackIp(normalized);
  }

  private isPrivateOrLoopbackIp(rawAddress: string): boolean {
    const address = rawAddress.trim().toLowerCase().replace(/^\[|\]$/g, '');
    if (!address) {
      return true;
    }

    if (address.includes(':')) {
      return (
        address === '::1' ||
        address.startsWith('fc') ||
        address.startsWith('fd') ||
        address.startsWith('fe80')
      );
    }

    const octets = address.split('.').map((part) => Number(part));
    if (octets.length !== 4 || octets.some((part) => Number.isNaN(part))) {
      return false;
    }
    const [a, b] = octets;
    if (a === 10 || a === 127 || a === 0) {
      return true;
    }
    if (a === 172 && b >= 16 && b <= 31) {
      return true;
    }
    if (a === 192 && b === 168) {
      return true;
    }
    if (a === 169 && b === 254) {
      return true;
    }
    return false;
  }

  private getRecvDescriptionSdps(): string[] {
    if (!this.recvPc) {
      return [];
    }

    const seen = new Set<string>();
    const sdps: string[] = [];
    const candidates = [
      this.recvPc.currentRemoteDescription?.sdp,
      this.recvPc.remoteDescription?.sdp,
      this.recvPc.pendingRemoteDescription?.sdp,
      this.recvPc.currentLocalDescription?.sdp,
      this.recvPc.localDescription?.sdp,
      this.recvPc.pendingLocalDescription?.sdp,
    ];

    for (const maybeSdp of candidates) {
      if (typeof maybeSdp !== 'string' || maybeSdp.length === 0) {
        continue;
      }
      if (seen.has(maybeSdp)) {
        continue;
      }
      seen.add(maybeSdp);
      sdps.push(maybeSdp);
    }

    return sdps;
  }

  private inferKindForMid(mid: string): 'audio' | 'video' {
    if (!mid) {
      return 'audio';
    }

    const historyEntry = this.recvMLineHistory.find((entry) => entry.mid === mid);
    if (historyEntry) {
      return historyEntry.kind;
    }

    for (const sdp of this.getRecvDescriptionSdps()) {
      const section = this.summarizeSdpMSections(sdp).find((candidate) => candidate.mid === mid);
      if (section?.kind === 'audio' || section?.kind === 'video') {
        return section.kind;
      }
    }

    if (this.recvPc) {
      const transceiver = this.recvPc
        .getTransceivers()
        .find((candidate) => candidate.mid?.trim() === mid);
      const kind = transceiver?.receiver.track?.kind;
      if (kind === 'audio' || kind === 'video') {
        return kind;
      }
    }

    return 'audio';
  }

  private ensureHardRejectedMidsHaveHistoryEntries(): void {
    if (this.hardRejectedRecvMids.size === 0) {
      return;
    }

    const existingMids = new Set(this.recvMLineHistory.map((entry) => entry.mid));

    for (const mid of this.hardRejectedRecvMids) {
      if (existingMids.has(mid)) {
        continue;
      }

      const kind = this.inferKindForMid(mid);
      this.recvMLineHistory.push({
        mid,
        kind,
        consumerId: `__hard_rejected_mid_${mid}`,
        rtpParameters: { codecs: [] },
        active: false,
      });
      existingMids.add(mid);
    }

    const maxKnownMid = Array.from(existingMids)
      .map((mid) => Number(mid))
      .filter((mid) => Number.isFinite(mid))
      .reduce((max, current) => Math.max(max, current), -1);
    if (maxKnownMid >= 0) {
      this.nextRecvMid = Math.max(this.nextRecvMid, maxKnownMid + 1);
    }
  }

  private allocateFreshRecvMid(): string {
    this.ensureHardRejectedMidsHaveHistoryEntries();

    while (true) {
      const candidate = String(this.nextRecvMid++);
      if (this.hardRejectedRecvMids.has(candidate)) {
        continue;
      }
      if (this.recvMLineHistory.some((entry) => entry.mid === candidate)) {
        continue;
      }
      return candidate;
    }
  }

  // ─────────────────────────────────────────────────────
  // Public API
  // ─────────────────────────────────────────────────────

  async join(): Promise<Result<MediaStream, WebRTCError>> {
    this.events.onConnectionStateChange?.('connecting');
    try {
      const connectResult = await this.signaling.connect({ roomId: this.options.roomId });
      if (!connectResult.ok) {
        return this.failJoin(connectResult.error);
      }

      this.setupSignalingEvents();

      const joinResult = await this.signaling.request<JoinRoomResult>('joinRoom', {
        roomId: this.options.roomId,
        displayName: this.options.displayName,
      });
      if (!joinResult.ok) {
        return this.failJoin(joinResult.error);
      }

      const roomData = joinResult.value;
      this.updateRouterCodecWhitelist(roomData.routerRtpCapabilities);

      // Intersect router capabilities with real browser receiver capabilities.
      const clientCaps = this.buildClientRtpCapabilities(roomData.routerRtpCapabilities);

      const setCapsResult = await this.signaling.request('setRtpCapabilities', {
        rtpCapabilities: clientCaps,
      });
      if (!setCapsResult.ok) {
        return this.failJoin(setCapsResult.error);
      }

      const sendTransportResult = await this.signaling.request<CreateTransportResult>(
        'createTransport',
        { direction: 'send' }
      );
      if (!sendTransportResult.ok) {
        return this.failJoin(sendTransportResult.error);
      }
      this.sendTransportId = sendTransportResult.value.id;
      this.sendTransportData = sendTransportResult.value;

      const recvTransportResult = await this.signaling.request<CreateTransportResult>(
        'createTransport',
        { direction: 'recv' }
      );
      if (!recvTransportResult.ok) {
        return this.failJoin(recvTransportResult.error);
      }
      this.recvTransportId = recvTransportResult.value.id;
      this.recvTransportData = recvTransportResult.value;

      this.inspectSfuTransportCandidates(
        sendTransportResult.value,
        'send',
        roomData.turnConfig
      );
      this.inspectSfuTransportCandidates(
        recvTransportResult.value,
        'recv',
        roomData.turnConfig
      );

      // Generate one shared DTLS certificate for both PeerConnections.
      // Chrome normally generates a new certificate per RTCPeerConnection, giving
      // sendPc and recvPc different fingerprints. By pre-generating a single cert
      // and passing it to both constructors we ensure they advertise the same
      // fingerprint — so we can call connectTransport for the recv transport right
      // after the send transport (same DTLS params), before any ICE completes.
      if (!this.sharedCertificate) {
        this.sharedCertificate = await RTCPeerConnection.generateCertificate({
          name: 'ECDSA',
          namedCurve: 'P-256',
        } as AlgorithmIdentifier);
      }
      const cert = this.sharedCertificate;

      this.sendPc = this.createPeerConnection(sendTransportResult.value, roomData.turnConfig, cert);
      this.recvPc = this.createPeerConnection(recvTransportResult.value, roomData.turnConfig, cert);
      this.attachRecvPipelineStateListeners();
      this.notifyRecvPipelineStateChanged();

      const localStreamResult = await this.captureMedia();
      if (!localStreamResult.ok) {
        return this.failJoin(localStreamResult.error);
      }
      const capturedStream = localStreamResult.value;
      const mediaValidationResult = await this.validateCapturedMediaStream(capturedStream);
      if (!mediaValidationResult.ok) {
        for (const track of capturedStream.getTracks()) {
          track.stop();
        }
        return this.failJoin(mediaValidationResult.error);
      }
      this.localStream = capturedStream;

      for (const track of this.localStream.getTracks()) {
        this.sendPc.addTrack(track, this.localStream);
      }

      // Proactively narrow browser codec set before createOffer().
      const codecPreferenceResult = this.setCodecPreferences();
      if (!codecPreferenceResult.ok) {
        // Not fatal: keep connection attempt running and let fallback policy recover.
        this.events.onError?.(codecPreferenceResult.error);
      }

      const offerResult = await this.createAndSetLocalOffer();
      if (!offerResult.ok) {
        return this.failJoin(offerResult.error);
      }

      // Tell the server our DTLS fingerprint so it can accept the handshake.
      // Force role to 'client' — browser is always DTLS-active.
      const clientDtls = this.extractDtlsFromSdp(offerResult.value.sdp || '');
      clientDtls.role = 'client';

      const connectTransportResult = await this.signaling.request('connectTransport', {
        transportId: this.sendTransportId,
        dtlsParameters: clientDtls,
      });
      if (!connectTransportResult.ok) {
        return this.failJoin(connectTransportResult.error);
      }

      // Both PCs share the same DTLS certificate, so the recv transport has the
      // same fingerprint as the send transport. Connect it now — before any ICE
      // candidate is exchanged — so the SFU already knows our certificate when
      // Chrome fires its DTLS ClientHello (which can arrive in < 10 ms on LAN).
      if (!this.recvTransportConnected && this.recvTransportId && this.recvTransportData) {
        const connectRecvResult = await this.signaling.request('connectTransport', {
          transportId: this.recvTransportId,
          dtlsParameters: clientDtls,
        });
        if (!connectRecvResult.ok) {
          return this.failJoin(connectRecvResult.error);
        }
        this.recvTransportConnected = true;
        console.log('[MediaEngine] Recv transport connected (DTLS, shared cert, early)');
        this.notifyRecvPipelineStateChanged();
      }

      // Build synthetic SDP answer from server transport params and set as
      // remote description. Without this the browser cannot perform ICE
      // connectivity checks or DTLS handshake, so no RTP would ever flow.
      const sendAnswerSdp = this.buildSendAnswerSdp(offerResult.value.sdp || '');
      console.log('[MediaEngine] Send answer SDP:\n', sendAnswerSdp);
      await this.sendPc.setRemoteDescription({ type: 'answer', sdp: sendAnswerSdp });
      console.log('[MediaEngine] Send transport: remote answer set, ICE/DTLS starting');

      for (const sender of this.sendPc.getSenders()) {
        if (!sender.track) continue;
        const kind = sender.track.kind as 'audio' | 'video';
        const rtpParameters = this.extractRtpParameters(sender);

        const firstEncoding = rtpParameters.encodings?.[0];
        console.log(
          `[MediaEngine] produce ${kind}: SSRC=${firstEncoding?.ssrc ?? 'none'} ` +
            `rtxSSRC=${firstEncoding?.rtx?.ssrc ?? 'none'} ` +
            `codecs=${rtpParameters.codecs?.map((c: any) => `${c.mimeType}(PT=${c.payloadType})`).join(',')}`
        );

        const produceResult = await this.signaling.request('produce', {
          transportId: this.sendTransportId,
          kind,
          rtpParameters,
        });

        if (!produceResult.ok) {
          return this.failJoin(produceResult.error);
        }
      }

      // Force catch-up for existing producers already in room.
      const syncConsumersResult = await this.signaling.request('syncConsumers', {});
      if (!syncConsumersResult.ok) {
        // Non-fatal: regular push notifications may still populate remote streams.
        this.events.onError?.(syncConsumersResult.error);
      }

      this.bitrateController = new BitrateController(this.sendPc);
      this.bitrateController.start((metrics) => {
        this.events.onQualityMetrics?.(metrics);
        const qualityReportResult = this.signaling.notify('qualityReport', {
          packetLossRate: metrics.packetLossRate,
          rttMs: metrics.rttMs,
        });
        if (!qualityReportResult.ok) {
          this.events.onError?.(qualityReportResult.error);
        }
      });

      for (const participant of roomData.participants || []) {
        // Skip self — getParticipants() includes the joining peer,
        // but the UI already counts the local user separately (+1).
        if (participant.peerId === this.signaling.peerId) continue;
        this.events.onParticipantJoined?.(participant.peerId, participant.displayName);
      }

      this.joined = true;
      this.registerPageLifecycleHandlers();
      this.canProcessConsumers = true;
      this.notifyRecvPipelineStateChanged();
      void this.scheduleConsumerQueueDrain();

      this.events.onConnectionStateChange?.('connected');

      return ok(this.localStream);
    } catch (cause) {
      return this.failJoin(
        createWebRTCError('TRANSPORT_SETUP_FAILURE', 'Unexpected join pipeline failure', {
          retriable: true,
          cause,
        })
      );
    }
  }

  async leave(): Promise<Result<void, WebRTCError>> {
    this.leaveFastPath('manual');
    return ok(undefined);
  }

  private leaveFastPath(trigger: LeaveTrigger): void {
    if (this.isLeaving) {
      return;
    }

    this.isLeaving = true;
    try {
      const hadActiveSession =
        this.joined || !!this.sendPc || !!this.recvPc || !!this.localStream;

      this.joined = false;
      this.unregisterPageLifecycleHandlers();
      this.bitrateController?.stop();
      this.bitrateController = null;

      this.sendLeaveSignalBestEffort(trigger);
      this.stopLocalTracks();
      this.closePeerConnections();
      this.signaling.disconnect();
      this.resetSessionState();

      if (hadActiveSession) {
        this.events.onConnectionStateChange?.('disconnected');
      }
    } finally {
      this.isLeaving = false;
    }
  }

  private registerPageLifecycleHandlers(): void {
    if (this.pageLifecycleHandlersAttached || typeof window === 'undefined') {
      return;
    }
    window.addEventListener('pagehide', this.handlePageHide, true);
    window.addEventListener('beforeunload', this.handleBeforeUnload, true);
    this.pageLifecycleHandlersAttached = true;
  }

  private unregisterPageLifecycleHandlers(): void {
    if (!this.pageLifecycleHandlersAttached || typeof window === 'undefined') {
      return;
    }
    window.removeEventListener('pagehide', this.handlePageHide, true);
    window.removeEventListener('beforeunload', this.handleBeforeUnload, true);
    this.pageLifecycleHandlersAttached = false;
  }

  private sendLeaveSignalBestEffort(trigger: LeaveTrigger): void {
    if (trigger === 'pagehide' || trigger === 'beforeunload') {
      this.trySendLeaveBeacon(trigger);
    }

    if (!this.signaling.connected) {
      return;
    }

    const leavePayload = {
      roomId: this.options.roomId,
      trigger,
      ts: Date.now(),
      peerId: this.signaling.peerId,
    };
    const notifyResult = this.signaling.notify('leaveRoom', leavePayload);
    if (!notifyResult.ok) {
      console.warn('[MediaEngine] leaveRoom notify failed:', notifyResult.error.message);
    }
  }

  private trySendLeaveBeacon(trigger: Exclude<LeaveTrigger, 'manual'>): void {
    if (
      typeof navigator === 'undefined' ||
      typeof navigator.sendBeacon !== 'function'
    ) {
      return;
    }

    const beaconUrl = this.resolveSignalingBeaconUrl();
    if (!beaconUrl) {
      return;
    }

    const payload = JSON.stringify({
      method: 'leaveRoom',
      data: {
        roomId: this.options.roomId,
        peerId: this.signaling.peerId,
        trigger,
        ts: Date.now(),
      },
    });
    const body = new Blob([payload], { type: 'application/json' });
    const sent = navigator.sendBeacon(beaconUrl, body);
    if (!sent) {
      console.warn('[MediaEngine] leaveRoom beacon was not accepted by browser');
    }
  }

  private resolveSignalingBeaconUrl(): string | null {
    if (typeof window === 'undefined') {
      return null;
    }

    try {
      const parsed = new URL(this.options.signalingUrl, window.location.origin);
      if (parsed.protocol === 'ws:') {
        parsed.protocol = 'http:';
      } else if (parsed.protocol === 'wss:') {
        parsed.protocol = 'https:';
      }
      return parsed.toString();
    } catch {
      return null;
    }
  }

  private stopLocalTracks(): void {
    if (!this.localStream) {
      return;
    }
    for (const track of this.localStream.getTracks()) {
      track.stop();
    }
    this.localStream = null;
  }

  private closePeerConnections(): void {
    this.sendPc?.close();
    this.recvPc?.close();
    this.sendPc = null;
    this.recvPc = null;
  }

  private resetSessionState(): void {
    this.remoteStreams.clear();
    this.activeConsumers.clear();
    this.recvMLineHistory = [];
    this.hardRejectedRecvMids.clear();
    this.recvTransportConnected = false;
    this.recvTransportData = null;
    this.nextRecvMid = 0;
    this.recvNegotiationLock = Promise.resolve();
    this.canProcessConsumers = false;
    this.consumerQueue = [];
    this.queuedConsumerIds.clear();
    this.consumerQueueDrainPromise = null;
    this.notifyRecvPipelineStateChanged();
    this.sendTransportId = null;
    this.sendTransportData = null;
    this.recvTransportId = null;
    this.iceRestartAttempts.clear();
    this.iceRestartInProgress.clear();
    this.gatheredCandidateCounts.clear();
    this.directCandidateDiscovered.clear();
    this.publicSrflxCandidateDiscovered.clear();
    this.warnedAboutMissingPublicSrflx.clear();
    this.relayPolicyForced.clear();
    this.pcHasTurnServer.clear();
    this.announcedPublicSrflx = false;
    this.clearAllRelayFallbackTimers();
  }

  setAudioEnabled(enabled: boolean): Result<void, WebRTCError> {
    const audioTrack = this.localStream?.getAudioTracks()[0];
    if (!audioTrack) {
      return err(
        createWebRTCError('MEDIA_CAPTURE_FAILURE', 'Local audio track is not available', {
          retriable: true,
        })
      );
    }

    audioTrack.enabled = enabled;
    return ok(undefined);
  }

  setVideoEnabled(enabled: boolean): Result<void, WebRTCError> {
    const videoTrack = this.localStream?.getVideoTracks()[0];
    if (!videoTrack) {
      // Audio-only sessions are valid: camera may be unavailable/disabled.
      return ok(undefined);
    }

    videoTrack.enabled = enabled;
    return ok(undefined);
  }

  getLocalStream(): MediaStream | null {
    return this.localStream;
  }

  getRemoteStreams(): RemoteStream[] {
    return Array.from(this.remoteStreams.values());
  }

  // ─────────────────────────────────────────────────────
  // Media Capture + Offer
  // ─────────────────────────────────────────────────────

  private async captureMedia(): Promise<Result<MediaStream, WebRTCError>> {
    const hasNavigator = typeof navigator !== 'undefined';
    const mediaDevices = hasNavigator ? navigator.mediaDevices : undefined;
    const hasGetUserMedia = typeof mediaDevices?.getUserMedia === 'function';
    const hasWindow = typeof window !== 'undefined';
    const isSecureContext =
      hasWindow && typeof window.isSecureContext === 'boolean'
        ? window.isSecureContext
        : undefined;

    if (!hasGetUserMedia) {
      const host = hasWindow ? window.location.host : 'n/a';
      const protocol = hasWindow ? window.location.protocol : 'n/a';
      const secureHint =
        isSecureContext === false
          ? 'Browser blocked camera/microphone on insecure origin. Open app over HTTPS (or localhost).'
          : 'Browser does not support navigator.mediaDevices.getUserMedia.';

      return err(
        createWebRTCError('MEDIA_CAPTURE_FAILURE', secureHint, {
          retriable: true,
          details: {
            protocol,
            host,
            isSecureContext,
            hasNavigator,
            hasMediaDevices: !!mediaDevices,
          },
        })
      );
    }

    const videoConstraints: MediaTrackConstraints = {
      // Keep profile ambitious, but do not force high minima.
      // On constrained uplinks/CPU, hard minima lead to 1080p + very low FPS (often 1-3),
      // which looks like "bitrate starvation" despite connected transport.
      width: { ideal: VIDEO_TARGET_WIDTH },
      height: { ideal: VIDEO_TARGET_HEIGHT },
      frameRate: { ideal: TARGET_FPS },
    };
    const audioConstraints: MediaTrackConstraints = {
      // Keep these as "ideal" for better compatibility with varied microphones.
      channelCount: { ideal: 2 },
      sampleRate: { ideal: 48000 },
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
    };

    try {
      const stream = await mediaDevices.getUserMedia({
        video: false,
        audio: audioConstraints,
      });
      return ok(stream);
    } catch (fullCaptureCause) {
      // If camera capture fails, continue in audio-only mode.
      try {
        const audioOnlyStream = await mediaDevices.getUserMedia({
          video: false,
          audio: audioConstraints,
        });
        this.events.onInfo?.(
          'Камера недоступна. Продолжаем в аудио-режиме.'
        );
        return ok(audioOnlyStream);
      } catch (audioOnlyCause) {
        const domException =
          typeof DOMException !== 'undefined' && audioOnlyCause instanceof DOMException
            ? audioOnlyCause
            : typeof DOMException !== 'undefined' && fullCaptureCause instanceof DOMException
              ? fullCaptureCause
              : null;
        const normalizedMessage =
          domException?.name === 'NotAllowedError'
            ? 'Microphone permission denied by user or browser policy'
            : domException?.name === 'NotFoundError'
              ? 'Microphone device not found'
              : domException?.name === 'NotReadableError'
                ? 'Microphone is already in use by another application'
                : 'Failed to capture microphone';

        return err(
          createWebRTCError('MEDIA_CAPTURE_FAILURE', normalizedMessage, {
            retriable: false,
            details: {
              name: domException?.name,
              isSecureContext,
              protocol: hasWindow ? window.location.protocol : 'n/a',
              host: hasWindow ? window.location.host : 'n/a',
              attemptedAudioOnlyFallback: true,
            },
            cause: audioOnlyCause,
          })
        );
      }
    }
  }

  private async validateCapturedMediaStream(
    stream: MediaStream
  ): Promise<Result<void, WebRTCError>> {
    const audioTrack = stream.getAudioTracks()[0];
    const videoTrack = stream.getVideoTracks()[0];
    const errors: string[] = [];
    const warnings: string[] = [];
    const details: Record<string, unknown> = {
      audioTrackId: audioTrack?.id || null,
      videoTrackId: videoTrack?.id || null,
      audioTrackState: audioTrack?.readyState || null,
      videoTrackState: videoTrack?.readyState || null,
      audioTrackMuted: audioTrack?.muted ?? null,
      videoTrackMuted: videoTrack?.muted ?? null,
      audioTrackEnabled: audioTrack?.enabled ?? null,
      videoTrackEnabled: videoTrack?.enabled ?? null,
      audioTrackSettings: audioTrack?.getSettings?.() || null,
      videoTrackSettings: videoTrack?.getSettings?.() || null,
    };

    const audioStateError = await this.validateTrackState(audioTrack, 'audio');
    if (audioStateError) {
      errors.push(audioStateError);
    }

    const videoStateError = videoTrack
      ? await this.validateTrackState(videoTrack, 'video')
      : null;
    if (videoStateError) {
      warnings.push(videoStateError);
    }

    if (audioTrack && !audioStateError) {
      const audioProbe = await this.probeAudioTrack(audioTrack);
      details.audioProbe = audioProbe;
      if (audioProbe.isLikelySilence) {
        warnings.push(audioProbe.reason);
      } else if (!audioProbe.ok) {
        errors.push(audioProbe.reason);
      }
    }

    if (videoTrack && !videoStateError) {
      const videoProbe = await this.probeVideoTrack(videoTrack);
      details.videoProbe = videoProbe;
      if (!videoProbe.ok) {
        warnings.push(videoProbe.reason);
      }
    }

    if (errors.length > 0) {
      return err(
        createWebRTCError(
          'MEDIA_CAPTURE_FAILURE',
          `Local media validation failed: ${errors.join('; ')}`,
          {
            retriable: true,
            details,
          }
        )
      );
    }

    if (warnings.length > 0) {
      console.warn('[MediaEngine] Media validation warnings (non-fatal):', {
        warnings,
        details,
      });
      const hasLikelySilentMicWarning = warnings.some((warning) =>
        warning.toLowerCase().includes('microphone track is currently silent')
      );
      const hasCameraWarning = warnings.some((warning) =>
        warning.toLowerCase().includes('camera')
      );

      if (hasCameraWarning) {
        this.events.onInfo?.(
          'Камера сейчас недоступна. Звонок продолжен только со звуком.'
        );
      }
      if (hasLikelySilentMicWarning) {
        this.events.onInfo?.(
          'Микрофон сейчас не даёт заметного сигнала (тишина). Подключение продолжено; попробуйте сказать пару слов после входа.'
        );
      }
    }

    return ok(undefined);
  }

  private async validateTrackState(
    track: MediaStreamTrack | undefined,
    kind: 'audio' | 'video'
  ): Promise<string | null> {
    if (!track) {
      return `${kind === 'audio' ? 'Microphone' : 'Camera'} track is missing`;
    }

    if (track.readyState !== 'live') {
      return `${kind === 'audio' ? 'Microphone' : 'Camera'} track is not live (state=${track.readyState})`;
    }

    if (!track.enabled) {
      return `${kind === 'audio' ? 'Microphone' : 'Camera'} track is disabled`;
    }

    const unmuted = await this.waitForTrackUnmute(track, 700);
    if (!unmuted || track.muted) {
      return `${kind === 'audio' ? 'Microphone' : 'Camera'} track stayed muted and produced no active media`;
    }

    return null;
  }

  private async waitForTrackUnmute(
    track: MediaStreamTrack,
    timeoutMs: number
  ): Promise<boolean> {
    if (!track.muted) {
      return true;
    }

    return await new Promise<boolean>((resolve) => {
      const timerId = setTimeout(() => {
        cleanup();
        resolve(false);
      }, timeoutMs);

      const handleUnmute = () => {
        cleanup();
        resolve(true);
      };

      const cleanup = () => {
        clearTimeout(timerId);
        track.removeEventListener('unmute', handleUnmute);
      };

      track.addEventListener('unmute', handleUnmute);
    });
  }

  private async probeAudioTrack(track: MediaStreamTrack): Promise<{
    ok: boolean;
    reason: string;
    peakDeviation?: number;
    isLikelySilence?: boolean;
  }> {
    if (typeof window === 'undefined') {
      return { ok: true, reason: 'audio probe skipped (no window)' };
    }

    const extendedWindow = window as Window & {
      webkitAudioContext?: typeof AudioContext;
    };
    const AudioContextCtor = extendedWindow.AudioContext || extendedWindow.webkitAudioContext;
    if (!AudioContextCtor) {
      return { ok: true, reason: 'audio probe skipped (AudioContext is unavailable)' };
    }

    let audioContext: AudioContext | null = null;
    try {
      audioContext = new AudioContextCtor();
      const sourceStream = new MediaStream([track]);
      const source = audioContext.createMediaStreamSource(sourceStream);
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 1024;
      analyser.smoothingTimeConstant = 0.2;
      source.connect(analyser);

      const pcm = new Uint8Array(analyser.fftSize);
      let peakDeviation = 0;
      const sampleDelayMs = Math.max(
        80,
        Math.floor(MediaEngine.MEDIA_VALIDATION_TIMEOUT_MS / MediaEngine.MEDIA_PROBE_SAMPLE_COUNT)
      );

      for (let index = 0; index < MediaEngine.MEDIA_PROBE_SAMPLE_COUNT; index += 1) {
        await this.wait(sampleDelayMs);
        analyser.getByteTimeDomainData(pcm);
        for (let i = 0; i < pcm.length; i += 32) {
          peakDeviation = Math.max(peakDeviation, Math.abs(pcm[i] - 128));
        }
      }

      source.disconnect();
      analyser.disconnect();

      if (peakDeviation <= 1) {
        return {
          ok: true,
          reason:
            'microphone track is currently silent (sampled PCM values stayed near zero level)',
          peakDeviation,
          isLikelySilence: true,
        };
      }

      return {
        ok: true,
        reason: 'audio probe passed',
        peakDeviation,
      };
    } catch (cause) {
      return {
        ok: false,
        reason: `audio probe failed: ${this.getErrorMessage(cause)}`,
      };
    } finally {
      if (audioContext) {
        try {
          await audioContext.close();
        } catch {
          // Ignore close errors in diagnostics-only probe.
        }
      }
    }
  }

  private async probeVideoTrack(track: MediaStreamTrack): Promise<{
    ok: boolean;
    reason: string;
    maxAverageLuma?: number;
    signatureChanges?: number;
  }> {
    if (typeof document === 'undefined') {
      return { ok: true, reason: 'video probe skipped (no document)' };
    }

    const probeStream = new MediaStream([track]);
    const video = document.createElement('video');
    video.autoplay = true;
    video.muted = true;
    video.playsInline = true;
    video.srcObject = probeStream;

    try {
      await video.play().catch(() => undefined);
      const becameReady = await this.waitForVideoCurrentData(
        video,
        MediaEngine.MEDIA_VALIDATION_TIMEOUT_MS
      );
      if (!becameReady) {
        return {
          ok: false,
          reason: 'camera track did not produce readable frames in time',
        };
      }

      const settings = track.getSettings();
      const width = Math.max(32, Math.min(320, Number(settings.width || video.videoWidth || 160)));
      const height = Math.max(24, Math.min(240, Number(settings.height || video.videoHeight || 90)));
      const canvas = document.createElement('canvas');
      canvas.width = width;
      canvas.height = height;
      const context = canvas.getContext('2d', { willReadFrequently: true });
      if (!context) {
        return {
          ok: false,
          reason: 'video probe failed to initialize canvas context',
        };
      }

      let maxAverageLuma = 0;
      let signatureChanges = 0;
      let previousSignature: number | null = null;
      const sampleDelayMs = Math.max(
        80,
        Math.floor(MediaEngine.MEDIA_VALIDATION_TIMEOUT_MS / MediaEngine.MEDIA_PROBE_SAMPLE_COUNT)
      );

      for (let index = 0; index < MediaEngine.MEDIA_PROBE_SAMPLE_COUNT; index += 1) {
        await this.wait(sampleDelayMs);
        if (video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) {
          continue;
        }
        context.drawImage(video, 0, 0, width, height);
        const frameSample = this.sampleVideoFrame(context, width, height);
        maxAverageLuma = Math.max(maxAverageLuma, frameSample.averageLuma);
        if (
          previousSignature !== null &&
          Math.abs(frameSample.signature - previousSignature) > 0.35
        ) {
          signatureChanges += 1;
        }
        previousSignature = frameSample.signature;
      }

      const likelyBlackFrozenFrame = maxAverageLuma < 6 && signatureChanges === 0;
      if (likelyBlackFrozenFrame) {
        return {
          ok: false,
          reason:
            'camera track appears black/frozen (frames have near-zero brightness and no motion)',
          maxAverageLuma,
          signatureChanges,
        };
      }

      return {
        ok: true,
        reason: 'video probe passed',
        maxAverageLuma,
        signatureChanges,
      };
    } catch (cause) {
      return {
        ok: false,
        reason: `video probe failed: ${this.getErrorMessage(cause)}`,
      };
    } finally {
      video.pause();
      video.srcObject = null;
    }
  }

  private sampleVideoFrame(
    context: CanvasRenderingContext2D,
    width: number,
    height: number
  ): { averageLuma: number; signature: number } {
    const imageData = context.getImageData(0, 0, width, height);
    const pixels = imageData.data;
    let lumaSum = 0;
    let weightedSignature = 0;
    let sampleCount = 0;

    for (let index = 0; index < pixels.length; index += 16) {
      const r = pixels[index] || 0;
      const g = pixels[index + 1] || 0;
      const b = pixels[index + 2] || 0;
      const luma = 0.2126 * r + 0.7152 * g + 0.0722 * b;
      lumaSum += luma;
      weightedSignature += luma * ((sampleCount % 29) + 1);
      sampleCount += 1;
    }

    if (sampleCount === 0) {
      return { averageLuma: 0, signature: 0 };
    }

    return {
      averageLuma: lumaSum / sampleCount,
      signature: weightedSignature / sampleCount,
    };
  }

  private async waitForVideoCurrentData(
    video: HTMLVideoElement,
    timeoutMs: number
  ): Promise<boolean> {
    const startedAt = Date.now();
    while (Date.now() - startedAt < timeoutMs) {
      if (video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) {
        return true;
      }
      await this.wait(80);
    }
    return false;
  }

  private async createAndSetLocalOffer(): Promise<Result<RTCSessionDescriptionInit, WebRTCError>> {
    if (!this.sendPc) {
      return err(
        createWebRTCError('TRANSPORT_SETUP_FAILURE', 'Send PeerConnection is not initialized')
      );
    }

    try {
      const offer = await this.sendPc.createOffer();
      let safeSdp = (offer.sdp || '').trim() + '\r\n';
      
      // Provide a tiny 100kbps spark to avoid the 0 byte TCP deadlock 
      // This is small enough to avoid buffer bloat, but enough to trigger REMB.
      safeSdp = safeSdp.replace(
        /(a=fmtp:\d+ .*)/g,
        '$1;x-google-start-bitrate=100'
      );

      await this.sendPc.setLocalDescription({ type: 'offer', sdp: safeSdp });
      offer.sdp = safeSdp;
      return ok(offer);
    } catch (cause) {
      return err(
        createWebRTCError(
          'NATIVE_SDP_REJECTION',
          'Browser rejected local SDP during offer creation',
          { retriable: true, cause }
        )
      );
    }
  }

  // ─────────────────────────────────────────────────────
  // PeerConnection setup
  // ─────────────────────────────────────────────────────

  private createPeerConnection(
    transportData: CreateTransportResult,
    turnConfig?: TurnConfig,
    certificate?: RTCCertificate
  ): RTCPeerConnection {
    const iceServers = this.getIceServers(turnConfig);
    const hasTurnServer = this.hasTurnServerConfigured(iceServers);

    const pcConfig: RTCConfiguration = {
      iceServers,
      bundlePolicy: 'max-bundle',
      rtcpMuxPolicy: 'require',
      iceTransportPolicy: 'all', // Allow both direct and relay candidates
    };
    if (certificate) {
      pcConfig.certificates = [certificate];
    }
    const pc = new RTCPeerConnection(pcConfig);

    // Initialize ICE restart counter for this PC.
    this.iceRestartAttempts.set(pc, 0);
    this.pcHasTurnServer.set(pc, hasTurnServer);
    this.relayPolicyForced.set(pc, false);
    this.resetIceState(pc);

    // ── Robust ICE connection state handler ──
    // Drives UI states and automatic ICE restart on failure.
    pc.oniceconnectionstatechange = () => {
      const state = pc.iceConnectionState;
      console.log(
        `[MediaEngine] ICE state (${pc === this.sendPc ? 'send' : 'recv'}): ${state}`
      );
      if (this.iceDiagEnabled) {
        void this.logSelectedIceCandidatePair(pc, `ice-state:${state}`);
      }

      if (pc === this.recvPc) {
        this.notifyRecvPipelineStateChanged();
      }

      switch (state) {
        case 'connected':
        case 'completed': {
          // Transport is healthy — reset restart counter and notify UI.
          this.iceRestartAttempts.set(pc, 0);
          this.markDirectCandidateDiscovered(pc);
          this.clearDisconnectedRecoveryTimer(pc);
          this.events.onConnectionStateChange?.('connected');
          break;
        }

        case 'disconnected': {
          // Temporary disruption — show reconnecting state.
          // If ICE does not self-recover within 6 s, trigger an ICE restart
          // rather than waiting indefinitely for 'failed' (which may never come
          // when the only path is a flaky TCP-passive candidate).
          console.warn(
            `[MediaEngine] ICE disconnected (${pc === this.sendPc ? 'send' : 'recv'}) — ` +
              'notifying UI to show reconnecting state'
          );
          this.events.onConnectionStateChange?.('reconnecting');
          this.armDisconnectedRecoveryTimer(pc);
          break;
        }

        case 'failed': {
          // ICE failed — immediately attempt automatic restart.
          const attempts = this.iceRestartAttempts.get(pc) ?? 0;
          if (attempts < MediaEngine.MAX_ICE_RESTART_ATTEMPTS) {
            this.iceRestartAttempts.set(pc, attempts + 1);
            console.warn(
              `[MediaEngine] ICE failed (${pc === this.sendPc ? 'send' : 'recv'}) — ` +
                'immediately performing automatic ICE restart ' +
                `(attempt ${attempts + 1}/${MediaEngine.MAX_ICE_RESTART_ATTEMPTS})`
            );
            this.events.onConnectionStateChange?.('reconnecting');
            this.performIceRestart(pc);
          } else {
            console.error(
              `[MediaEngine] ICE failed after ${MediaEngine.MAX_ICE_RESTART_ATTEMPTS} restart attempts`
            );
            this.events.onConnectionStateChange?.('failed');
            this.events.onError?.(
              createWebRTCError(
                'ICE_GATHERING_FAILURE',
                `ICE connection failed after ${MediaEngine.MAX_ICE_RESTART_ATTEMPTS} restart attempts. ` +
                  'Check network/firewall settings or TURN server availability.',
                { retriable: true }
              )
            );
          }
          break;
        }

        case 'closed': {
          this.clearRelayFallbackTimer(pc);
          this.clearDisconnectedRecoveryTimer(pc);
          this.events.onConnectionStateChange?.('disconnected');
          break;
        }
      }
    };

    pc.onsignalingstatechange = () => {
      if (pc === this.recvPc) {
        this.notifyRecvPipelineStateChanged();
      }
    };

    // ── DTLS / overall connection state ──
    // connectionState reflects DTLS completion (ICE connected → DTLS handshake → 'connected').
    // Without this handler, DTLS failures are completely silent.
    pc.onconnectionstatechange = () => {
      const label = pc === this.sendPc ? 'send' : 'recv';
      const state = pc.connectionState;
      console.log(`[MediaEngine] Connection state (${label}): ${state}`);
      if (state === 'failed') {
        console.error(
          `[MediaEngine] DTLS/connection failed on ${label} transport — ` +
            'media will not flow on this transport'
        );
        this.events.onError?.(
          createWebRTCError(
            'TRANSPORT_SETUP_FAILURE',
            `DTLS connection failed on ${label} transport`,
            { retriable: true }
          )
        );
      }
    };

    pc.onicecandidate = (event) => {
      if (event.candidate) {
        const currentCount = this.gatheredCandidateCounts.get(pc) ?? 0;
        this.gatheredCandidateCounts.set(pc, currentCount + 1);
        const candidateType = this.extractIceCandidateType(event.candidate);
        // peer-reflexive candidates are produced only when a round-trip ICE
        // connectivity check has already succeeded — that is actual evidence of
        // a working direct path.  host/srflx merely mean the candidate was
        // *gathered*; gathering succeeds even when the remote peer is unreachable.
        // Cancelling the relay-fallback timer on host/srflx was causing the timer
        // to be suppressed in <100 ms (before any connectivity was proven), leaving
        // the engine stuck in 'checking' → 'disconnected' loops for 60+ s instead
        // of switching to relay after 3.5 s.
        if (candidateType === 'prflx') {
          this.markDirectCandidateDiscovered(pc);
        }

        this.handleIceCandidateForGlobalRouting(pc, event.candidate);
      }
    };

    pc.onicegatheringstatechange = () => {
      const gatheredCandidates = this.gatheredCandidateCounts.get(pc) ?? 0;

      // Arm the relay-fallback timer the moment gathering begins, not at PC
      // creation.  Arming at creation caused premature fires on slow permission
      // grants: the 3500 ms expired before addTrack() was called, leaving zero
      // active transceivers and making performIceRestart() bail unconditionally.
      if (pc.iceGatheringState === 'gathering') {
        if (this.pcHasTurnServer.get(pc) && !this.relayPolicyForced.get(pc)) {
          this.armRelayFallbackTimer(pc);
        }
      }

      if (pc.iceGatheringState === 'complete' && gatheredCandidates === 0) {
        this.events.onError?.(
          createWebRTCError(
            'ICE_GATHERING_FAILURE',
            'ICE gathering completed with zero candidates. ' +
              'Possible causes: mDNS blocked on LAN, STUN unreachable, or firewall restrictions.',
            {
              retriable: true,
              details: {
                iceServers: iceServers.map((server) => server.urls),
              },
            }
          )
        );

        // If STUN discovery produced nothing and TURN exists — force relay mode.
        if (hasTurnServer && !this.relayPolicyForced.get(pc)) {
          this.forceRelayTransportPolicy(pc);
        }
      }

      if (pc.iceGatheringState === 'complete') {
        this.logPublicSrflxGatheringOutcome(pc, gatheredCandidates);
      }
    };

    pc.onicecandidateerror = (event) => {
      const isDnsLookupIssue =
        event.errorCode === 701 ||
        /dns\s*lookup/i.test(String(event.errorText || ''));
      const isTurnAllocateError = event.errorCode === 400;
      const isMdnsIssue = event.errorCode === 701 && /\.local/i.test(event.address || '');
      const details = {
        address: event.address,
        errorCode: event.errorCode,
        errorText: event.errorText,
        url: event.url,
      };

      // ── VPN / Mesh network graceful degradation ────────────────────
      // ICE errors on virtual-network interfaces (Hamachi, Tailscale CGNAT,
      // WSL private ranges) are expected: these adapters rarely have public
      // STUN reachability. Demote to debug-level so operators aren't alarmed.
      const vpnLabel = classifyVirtualNetwork(event.address);
      if (vpnLabel) {
        console.debug(
          `[MediaEngine] Expected ICE error on ${vpnLabel} interface — skipped:`,
          details
        );
        return;
      }

      // TURN allocate errors (400) are expected when no valid TURN credentials
      // are configured. The SFU provides its own ICE candidates via transport
      // params, so TURN is a fallback — its failure is non-fatal.
      if (isTurnAllocateError) {
        console.warn('[MediaEngine] Non-fatal TURN allocate error (credentials may be invalid):', details);
        return;
      }

      // ── DNS failure resilience ─────────────────────────────────────
      // errorCode 701 (RFC 7064) or "DNS lookup" text with no resolved
      // address means the system resolver failed for this STUN/TURN URL.
      // IP-based fallback servers in DEFAULT_ICE_SERVERS ensure gathering
      // continues; log at debug level since the fallback path covers it.
      if (isDnsLookupIssue) {
        const isIpv6 =
          event.url?.includes('[') ||
          event.address?.includes(':') ||
          /aaaa|ipv6/i.test(String(event.errorText || ''));

        const isDnsWithoutAddress = !event.address;

        // Silence IPv6 and mDNS (.local) lookup errors to prevent log spam.
        // mDNS failures are expected on LAN when multicast is blocked;
        // TURN relay will handle connectivity.
        if (isDnsWithoutAddress) {
          // No address resolved at all — pure DNS failure.
          // IP-based fallback STUN servers will cover this case.
          console.debug(
            '[MediaEngine] DNS resolution failed for ICE server (IP fallback active):',
            details
          );
        } else if (!isIpv6 && !isMdnsIssue) {
          console.warn('[MediaEngine] Non-fatal ICE DNS lookup issue:', details);
        }
        return;
      }

      this.events.onError?.(
        createWebRTCError('ICE_GATHERING_FAILURE', 'ICE candidate gathering failed', {
          retriable: true,
          details,
        })
      );
    };

    pc.ontrack = (event: RTCTrackEvent) => {
      console.log(
        `[MediaEngine] Remote track (${transportData.id}): ${event.track.kind} mid=${event.transceiver?.mid}`
      );
      this.handleRecvTrack(event);
    };

    return pc;
  }

  /**
   * Perform an ICE restart on the given PeerConnection.
   * For the send PC: creates a new offer with iceRestart and re-applies
   * the synthetic answer to re-establish transport without page reload.
   * For the recv PC: triggers restartIce() and waits for next renegotiation.
   */
  private performIceRestart(pc: RTCPeerConnection): void {
    if (this.iceRestartInProgress.has(pc)) {
      return;
    }

    this.iceRestartInProgress.add(pc);
    void (async () => {
      try {
        this.resetIceState(pc);

        // For send transport we explicitly build a new ICE-restart offer.
        // Do NOT call pc.restartIce() before createOffer({ iceRestart: true }) —
        // the combination confuses Chrome's internal session state after
        // setConfiguration({ iceTransportPolicy: 'relay' }), causing a
        // "max-bundle configured but session description has no BUNDLE group" error.
        // createOffer({ iceRestart: true }) is sufficient on its own.
        if (pc === this.sendPc && this.sendTransportData && this.sendTransportId) {
          // Pre-flight guard: if the PC was closed (e.g. leave() fired concurrently)
          // or all transceivers are stopped, createOffer() would generate a BUNDLE-less
          // SDP that Chrome immediately rejects with the "max-bundle configured but
          // session description has no BUNDLE group" OperationError.  Bail cleanly
          // without burning a restart attempt — the closed-PC path is not an error.
          if (pc.signalingState === 'closed') {
            console.warn('[MediaEngine] ICE restart aborted: PC already closed (send)');
            return;
          }
          const activeTransceivers = pc.getTransceivers().filter(
            t => t.currentDirection !== 'stopped'
          );
          if (activeTransceivers.length === 0) {
            console.warn(
              '[MediaEngine] ICE restart deferred: no active transceivers on send PC ' +
                '(tracks may be mid-teardown). Restart attempt not consumed.'
            );
            // Give back the attempt that was incremented by the caller so the next
            // genuine failure is still eligible for an automatic retry.
            const current = this.iceRestartAttempts.get(pc) ?? 0;
            if (current > 0) {
              this.iceRestartAttempts.set(pc, current - 1);
            }
            return;
          }
          console.log('[MediaEngine] ICE restart: creating new offer (send)');
          const rawOffer = await pc.createOffer({ iceRestart: true });
          
          // Remove stale candidate lines, so gathering restarts from a clean SDP.
          const strippedSdp = this.stripIceCandidatesFromSdp(rawOffer.sdp || '');
          // Sanitize SDP strictly avoiding EOF truncation NATIVE_SDP_REJECTION error
          const safeSdp = strippedSdp.trim() + '\r\n';
          
          const offer: RTCSessionDescriptionInit = {
            type: 'offer',
            sdp: safeSdp,
          };
          
          try {
            await pc.setLocalDescription(offer);
          } catch (descErr: any) {
            const msg = String(descErr?.message || '');
            const isCriticalSdp =
              descErr?.name === 'OperationError' &&
              (msg.includes('Failed to parse SessionDescription') ||
                msg.includes('no BUNDLE group') ||
                msg.includes('max-bundle'));
            if (isCriticalSdp) {
              console.error('[MediaEngine] CRITICAL_SDP_FAILURE during ICE Restart:', descErr);

              // Prevent new automatic ICE retries cycle
              this.iceRestartAttempts.set(pc, MediaEngine.MAX_ICE_RESTART_ATTEMPTS);

              // Dispatch fatal error forcing application to recreate the hard state
              this.events.onError?.(
                createWebRTCError(
                  'CRITICAL_SDP_FAILURE',
                  'Unrecoverable SDP format corruption. WebRTC engine requires hard reconnect.',
                  { retriable: false, cause: descErr }
                )
              );
              this.events.onConnectionStateChange?.('failed');
              return;
            }
            throw descErr;
          }

          const localOfferSdp = pc.localDescription?.sdp || offer.sdp || '';
          this.signalUpdatedOfferToSfu(localOfferSdp, this.sendTransportId, 'send');

          // Re-build synthetic answer with server transport params.
          const answerSdp = this.buildSendAnswerSdp(localOfferSdp);
          await pc.setRemoteDescription({ type: 'answer', sdp: answerSdp });

          console.log('[MediaEngine] ICE restart offer/answer exchange complete (send)');
        } else if (pc === this.recvPc) {
          // Recv PC doesn't own the offer/answer cycle (SFU drives it).
          // restartIce() is safe here since we're not following it with createOffer.
          pc.restartIce();
          console.log('[MediaEngine] restartIce() called (recv)');
        }
      } catch (err) {
        console.error('[MediaEngine] ICE restart negotiation failed:', err);
        this.events.onError?.(
          webRTCErrorFromUnknown(err, 'TRANSPORT_SETUP_FAILURE')
        );
      } finally {
        this.iceRestartInProgress.delete(pc);
      }
    })();
  }

  private hasTurnServerConfigured(iceServers: RTCIceServer[]): boolean {
    for (const server of iceServers) {
      const urls = Array.isArray(server.urls) ? server.urls : [server.urls];
      for (const rawUrl of urls) {
        const url = String(rawUrl || '').trim().toLowerCase();
        if (url.startsWith('turn:') || url.startsWith('turns:')) {
          return true;
        }
      }
    }
    return false;
  }

  private armRelayFallbackTimer(pc: RTCPeerConnection): void {
    this.clearRelayFallbackTimer(pc);
    const timerId = setTimeout(() => {
      if (pc.signalingState === 'closed') {
        return;
      }
      if (this.directCandidateDiscovered.get(pc)) {
        return;
      }
      if (this.relayPolicyForced.get(pc)) {
        return;
      }
      this.forceRelayTransportPolicy(pc);
    }, MediaEngine.DIRECT_ICE_CANDIDATE_TIMEOUT_MS);
    this.relayFallbackTimers.set(pc, timerId);
  }

  private clearRelayFallbackTimer(pc: RTCPeerConnection): void {
    const timerId = this.relayFallbackTimers.get(pc);
    if (!timerId) {
      return;
    }
    clearTimeout(timerId);
    this.relayFallbackTimers.delete(pc);
  }

  private clearAllRelayFallbackTimers(): void {
    for (const timerId of this.relayFallbackTimers.values()) {
      clearTimeout(timerId);
    }
    this.relayFallbackTimers.clear();
    for (const timerId of this.disconnectedRecoveryTimers.values()) {
      clearTimeout(timerId);
    }
    this.disconnectedRecoveryTimers.clear();
  }

  private armDisconnectedRecoveryTimer(pc: RTCPeerConnection): void {
    this.clearDisconnectedRecoveryTimer(pc);
    const timerId = setTimeout(() => {
      if (pc.iceConnectionState !== 'disconnected') return;
      const attempts = this.iceRestartAttempts.get(pc) ?? 0;
      if (attempts < MediaEngine.MAX_ICE_RESTART_ATTEMPTS) {
        this.iceRestartAttempts.set(pc, attempts + 1);
        console.warn(
          `[MediaEngine] ICE stuck in disconnected after 20 s — triggering ICE restart ` +
            `(attempt ${attempts + 1}/${MediaEngine.MAX_ICE_RESTART_ATTEMPTS})`
        );
        this.performIceRestart(pc);
      }
    }, 20_000);
    this.disconnectedRecoveryTimers.set(pc, timerId);
  }

  private clearDisconnectedRecoveryTimer(pc: RTCPeerConnection): void {
    const timerId = this.disconnectedRecoveryTimers.get(pc);
    if (timerId !== undefined) {
      clearTimeout(timerId);
      this.disconnectedRecoveryTimers.delete(pc);
    }
  }

  private markDirectCandidateDiscovered(pc: RTCPeerConnection): void {
    this.directCandidateDiscovered.set(pc, true);
    this.clearRelayFallbackTimer(pc);
  }

  private handleIceCandidateForGlobalRouting(
    pc: RTCPeerConnection,
    candidate: RTCIceCandidate
  ): void {
    const candidateType = this.extractIceCandidateType(candidate);
    const parsedCandidate = this.parseIceCandidate(candidate);
    const address = parsedCandidate.address || null;
    const transportLabel = this.getTransportLabel(pc);
    const shouldLogIceRouting =
      this.iceDiagEnabled || this.expectsPublicSrflxCandidate || candidateType === 'srflx';

    if (candidateType === 'srflx') {
      const isPublicAddress = !!address && !this.isPrivateOrLoopbackIp(address);

      if (isPublicAddress) {
        this.publicSrflxCandidateDiscovered.set(pc, true);
        if (!this.announcedPublicSrflx && this.expectsPublicSrflxCandidate) {
          this.announcedPublicSrflx = true;
          this.events.onInfo?.('STUN вернул публичный srflx ICE-кандидат. Глобальный маршрут доступен.');
        }

        if (shouldLogIceRouting) {
          console.info('[MediaEngine][ICE] Public srflx candidate detected', {
            transport: transportLabel,
            address,
            port: parsedCandidate.port,
            protocol: parsedCandidate.protocol,
          });
        }
      } else if (shouldLogIceRouting) {
        console.warn('[MediaEngine][ICE] Non-public srflx candidate detected', {
          transport: transportLabel,
          address,
          port: parsedCandidate.port,
          protocol: parsedCandidate.protocol,
        });
      }
      return;
    }

    if (
      candidateType === 'host' &&
      address &&
      this.isPrivateOrLoopbackIp(address) &&
      shouldLogIceRouting
    ) {
      console.debug('[MediaEngine][ICE] Local host candidate gathered', {
        transport: transportLabel,
        address,
        port: parsedCandidate.port,
        protocol: parsedCandidate.protocol,
      });
    }
  }

  private logPublicSrflxGatheringOutcome(
    pc: RTCPeerConnection,
    gatheredCandidates: number
  ): void {
    const transportLabel = this.getTransportLabel(pc);
    const hasPublicSrflx = this.publicSrflxCandidateDiscovered.get(pc) === true;
    const shouldLog = this.iceDiagEnabled || this.expectsPublicSrflxCandidate;

    if (hasPublicSrflx) {
      if (shouldLog) {
        console.info('[MediaEngine][ICE] ICE gathering completed with public srflx candidate', {
          transport: transportLabel,
          gatheredCandidates,
        });
      }
      return;
    }

    if (!this.expectsPublicSrflxCandidate) {
      return;
    }

    if (this.warnedAboutMissingPublicSrflx.get(pc)) {
      return;
    }
    this.warnedAboutMissingPublicSrflx.set(pc, true);

    console.warn(
      '[MediaEngine][ICE] ICE gathering finished without public srflx candidate. ' +
        'Only local/private candidates are available; internet media routing may fail.',
      {
        transport: transportLabel,
        gatheredCandidates,
      }
    );
    this.events.onInfo?.(
      'Публичный srflx ICE-кандидат не получен. Проверьте доступ к STUN/TURN (особенно при тесте через ngrok).'
    );
  }

  private inspectSfuTransportCandidates(
    transportData: CreateTransportResult,
    transportLabel: 'send' | 'recv',
    turnConfig?: TurnConfig
  ): void {
    const rawCandidates = Array.isArray(transportData.iceCandidates)
      ? transportData.iceCandidates
      : [];
    if (rawCandidates.length === 0) {
      return;
    }

    const addresses = new Set<string>();
    const privateAddresses = new Set<string>();
    const publicAddresses = new Set<string>();

    for (const candidate of rawCandidates as unknown[]) {
      const parsed = this.parseServerTransportCandidate(candidate);
      if (!parsed.address) continue;

      addresses.add(parsed.address);
      if (this.isPrivateOrLoopbackIp(parsed.address)) {
        privateAddresses.add(parsed.address);
      } else {
        publicAddresses.add(parsed.address);
      }
    }

    if (this.iceDiagEnabled || this.expectsPublicSrflxCandidate) {
      console.info('[MediaEngine][SFU ICE] Transport candidates received', {
        transport: transportLabel,
        transportId: transportData.id,
        totalCandidates: rawCandidates.length,
        addresses: Array.from(addresses),
      });
    }

    if (
      this.expectsPublicSrflxCandidate &&
      publicAddresses.size === 0 &&
      privateAddresses.size > 0 &&
      !this.warnedAboutPrivateSfuCandidates
    ) {
      this.warnedAboutPrivateSfuCandidates = true;
      const hasUsableTurnRelay = this.hasTurnServerConfigured(this.getIceServers(turnConfig));

      if (hasUsableTurnRelay) {
        console.warn(
          '[MediaEngine][SFU ICE] SFU returned private-only transport candidates on a public/tunnel route. ' +
            'Will rely on TURN relay for internet clients.',
          {
            transport: transportLabel,
            privateAddresses: Array.from(privateAddresses),
            candidateCount: rawCandidates.length,
          }
        );
        this.events.onInfo?.(
          'SFU выдал только локальные ICE-адреса. Для связи через интернет будет использован TURN relay.'
        );
        return;
      }

      console.error(
        '[MediaEngine][SFU ICE] SFU returned private-only transport candidates on a public/tunnel route. ' +
          'Remote internet clients will not be able to reach media port directly.',
        {
          transport: transportLabel,
          privateAddresses: Array.from(privateAddresses),
          candidateCount: rawCandidates.length,
        }
      );
      this.events.onInfo?.(
        'SFU выдал только локальные ICE-адреса (например 192.168.x.x). ' +
          'Для звонков через интернет нужен публичный WEBRTC_ANNOUNCED_IP и открытый media-порт SFU (UDP/TCP), либо рабочий TURN relay.'
      );
    }
  }

  private parseServerTransportCandidate(candidate: unknown): {
    address: string | null;
    port: number | null;
    protocol: string | null;
    type: string | null;
  } {
    const record =
      candidate && typeof candidate === 'object'
        ? (candidate as Record<string, unknown>)
        : null;
    if (!record) {
      return { address: null, port: null, protocol: null, type: null };
    }

    const ipRaw = String(record.ip || record.address || '').trim();
    const ip = ipRaw.replace(/^\[|\]$/g, '');

    const portValue = Number(record.port);
    const protocol = String(record.protocol || '').trim().toLowerCase() || null;
    const type = String(record.type || '').trim().toLowerCase() || null;

    if (ip) {
      return {
        address: ip,
        port: Number.isFinite(portValue) ? portValue : null,
        protocol,
        type,
      };
    }

    const candidateLine = String(record.candidate || '').trim();
    if (!candidateLine) {
      return { address: null, port: null, protocol: null, type: null };
    }

    const tokens = candidateLine.split(/\s+/);
    const parsedAddress = String(tokens[4] || '').trim().replace(/^\[|\]$/g, '');
    const parsedPort = Number(tokens[5]);
    const parsedProtocol = String(tokens[2] || '').trim().toLowerCase();
    const parsedTypeMatch = candidateLine.match(/\btyp\s+([a-z0-9]+)/i);

    return {
      address: parsedAddress || null,
      port: Number.isFinite(parsedPort) ? parsedPort : null,
      protocol: parsedProtocol || null,
      type: (parsedTypeMatch?.[1] || '').toLowerCase() || null,
    };
  }

  private parseIceCandidate(candidate: RTCIceCandidate): {
    address: string | null;
    port: number | null;
    protocol: string | null;
  } {
    const raw = String(candidate.candidate || '').trim();
    if (!raw) {
      return { address: null, port: null, protocol: null };
    }

    const tokens = raw.split(/\s+/);
    if (tokens.length < 6) {
      return { address: null, port: null, protocol: null };
    }

    const address = String(tokens[4] || '').trim().replace(/^\[|\]$/g, '');
    const port = Number(tokens[5]);
    const protocol = String(tokens[2] || '').trim().toLowerCase();

    return {
      address: address || null,
      port: Number.isFinite(port) ? port : null,
      protocol: protocol || null,
    };
  }

  private extractIceCandidateType(candidate: RTCIceCandidate): string {
    const nativeType = String(candidate.type || '').trim().toLowerCase();
    if (nativeType) {
      return nativeType;
    }

    const raw = String(candidate.candidate || '');
    const match = raw.match(/\btyp\s+([a-z0-9]+)/i);
    return (match?.[1] || '').toLowerCase();
  }

  private getTransportLabel(pc: RTCPeerConnection): 'send' | 'recv' | 'unknown' {
    if (pc === this.sendPc) {
      return 'send';
    }
    if (pc === this.recvPc) {
      return 'recv';
    }
    return 'unknown';
  }

  private async logSelectedIceCandidatePair(
    pc: RTCPeerConnection,
    reason: string
  ): Promise<void> {
    if (!this.iceDiagEnabled) {
      return;
    }

    const transportLabel = pc === this.sendPc ? 'send' : pc === this.recvPc ? 'recv' : 'unknown';

    try {
      const stats = await pc.getStats();
      let selectedPair: (RTCStats & Record<string, any>) | null = null;

      stats.forEach((report) => {
        if (selectedPair) return;
        const item = report as RTCStats & Record<string, any>;
        if (item.type !== 'transport') {
          return;
        }
        const selectedPairId = String(item.selectedCandidatePairId || '').trim();
        if (!selectedPairId) {
          return;
        }
        const pair = stats.get(selectedPairId) as (RTCStats & Record<string, any>) | undefined;
        if (pair?.type === 'candidate-pair') {
          selectedPair = pair;
        }
      });

      if (!selectedPair) {
        stats.forEach((report) => {
          if (selectedPair) return;
          const item = report as RTCStats & Record<string, any>;
          const isSelected =
            item.type === 'candidate-pair' &&
            (item.selected === true || (item.nominated === true && item.state === 'succeeded'));
          if (isSelected) {
            selectedPair = item;
          }
        });
      }

      if (!selectedPair) {
        console.debug('[MediaEngine][IceDiag] No selected candidate pair', {
          reason,
          transport: transportLabel,
          iceConnectionState: pc.iceConnectionState,
        });
        return;
      }

      const localCandidate = selectedPair.localCandidateId
        ? (stats.get(String(selectedPair.localCandidateId)) as
            | (RTCStats & Record<string, any>)
            | undefined)
        : undefined;
      const remoteCandidate = selectedPair.remoteCandidateId
        ? (stats.get(String(selectedPair.remoteCandidateId)) as
            | (RTCStats & Record<string, any>)
            | undefined)
        : undefined;

      console.debug('[MediaEngine][IceDiag] Selected candidate pair', {
        reason,
        transport: transportLabel,
        pairId: selectedPair.id,
        pairState: selectedPair.state,
        nominated: selectedPair.nominated === true,
        currentRoundTripTimeMs:
          typeof selectedPair.currentRoundTripTime === 'number'
            ? Math.round(selectedPair.currentRoundTripTime * 1000)
            : null,
        availableOutgoingBitrateBps:
          typeof selectedPair.availableOutgoingBitrate === 'number'
            ? Math.round(selectedPair.availableOutgoingBitrate)
            : null,
        availableIncomingBitrateBps:
          typeof selectedPair.availableIncomingBitrate === 'number'
            ? Math.round(selectedPair.availableIncomingBitrate)
            : null,
        local: localCandidate
          ? {
              type: localCandidate.candidateType || null,
              protocol: localCandidate.protocol || null,
              address: localCandidate.address || localCandidate.ip || null,
              port: localCandidate.port || null,
              networkType: localCandidate.networkType || null,
            }
          : null,
        remote: remoteCandidate
          ? {
              type: remoteCandidate.candidateType || null,
              protocol: remoteCandidate.protocol || null,
              address: remoteCandidate.address || remoteCandidate.ip || null,
              port: remoteCandidate.port || null,
            }
          : null,
      });
    } catch (error) {
      console.debug('[MediaEngine][IceDiag] Failed to inspect selected candidate pair', {
        reason,
        transport: transportLabel,
        error: this.getErrorMessage(error),
      });
    }
  }

  private forceRelayTransportPolicy(pc: RTCPeerConnection): void {
    try {
      const configuration = pc.getConfiguration();
      const currentPolicy = configuration.iceTransportPolicy || 'all';
      if (currentPolicy === 'relay') {
        return;
      }

      const configIceServers = configuration.iceServers || [];
      if (!this.hasTurnServerConfigured(configIceServers)) {
        return;
      }

      pc.setConfiguration({
        ...configuration,
        iceTransportPolicy: 'relay',
      });
      this.clearRelayFallbackTimer(pc);
      this.relayPolicyForced.set(pc, true);
      this.resetIceState(pc);
      console.warn(
        `[MediaEngine] No direct ICE candidates after ${MediaEngine.DIRECT_ICE_CANDIDATE_TIMEOUT_MS}ms. ` +
          'Switching to relay-only mode and restarting ICE.'
      );
      this.events.onInfo?.(
        'Прямые ICE-кандидаты не получены, включаю TURN relay и выполняю ICE restart'
      );
      this.performIceRestart(pc);
    } catch (cause) {
      this.events.onError?.(
        createWebRTCError(
          'ICE_GATHERING_FAILURE',
          'Failed to switch ICE transport policy to relay',
          {
            retriable: true,
            cause,
          }
        )
      );
    }
  }

  private resetIceState(pc: RTCPeerConnection): void {
    this.gatheredCandidateCounts.set(pc, 0);
    this.directCandidateDiscovered.set(pc, false);
    this.publicSrflxCandidateDiscovered.set(pc, false);
    this.warnedAboutMissingPublicSrflx.set(pc, false);
    if (!this.relayPolicyForced.has(pc)) {
      this.relayPolicyForced.set(pc, false);
    }
    // Relay-fallback timer is armed from onicegatheringstatechange ('gathering')
    // so it only fires after ICE gathering has actually started and transceivers
    // are in place.  Do not arm it here at reset time.
  }

  private stripIceCandidatesFromSdp(sdp: string): string {
    return sdp
      .split('\r\n')
      .filter((line) => line && !line.startsWith('a=candidate:') && line !== 'a=end-of-candidates')
      .join('\r\n');
  }

  private signalUpdatedOfferToSfu(
    sdp: string,
    transportId: string,
    direction: 'send' | 'recv'
  ): void {
    if (!sdp) {
      return;
    }

    const payload = {
      roomId: this.options.roomId,
      transportId,
      direction,
      iceRestart: true,
      sdp,
      sentAt: Date.now(),
    };

    const offerResult = this.signaling.notify('sdp_offer', payload);
    const legacyOfferResult = this.signaling.notify('offer', payload);
    if (!offerResult.ok && !legacyOfferResult.ok) {
      // Keep restart non-fatal: best effort signaling only.
      console.warn(
        '[MediaEngine] Failed to signal ICE-restart offer during ICE restart:',
        offerResult.error.message
      );
    }
  }

  private getIceServers(
    turnConfig?: TurnConfig
  ): RTCIceServer[] {
    const seenUrls = new Set<string>();
    const servers: RTCIceServer[] = [];

    const pushServer = (server: RTCIceServer, prioritizeUdp = false): void => {
      const urls = Array.isArray(server.urls) ? server.urls : [server.urls];
      const normalizedUrls = this.normalizeIceUrls(urls, prioritizeUdp);

      if (normalizedUrls.length === 0) return;

      const uniqueUrls = normalizedUrls.filter((url) => {
        if (seenUrls.has(url)) return false;
        seenUrls.add(url);
        return true;
      });

      if (uniqueUrls.length === 0) return;

      servers.push({
        ...server,
        urls: uniqueUrls.length === 1 ? uniqueUrls[0] : uniqueUrls,
      });
    };

    const baseIceServers =
      this.options.iceServers && this.options.iceServers.length > 0
        ? this.options.iceServers
        : MediaEngine.DEFAULT_ICE_SERVERS;

    for (const server of baseIceServers) {
      pushServer(server);
    }

    const turnUrls = Array.from(
      new Set(
        [
          ...(turnConfig?.urls || []),
          turnConfig?.url || '',
        ]
          .map((url) => url.trim())
          .filter(Boolean)
      )
    );

    const expandedTurnUrls: string[] = [];
    for (const url of turnUrls) {
      expandedTurnUrls.push(url);

      const tcpFallbackUrl = this.buildTcpFallbackTurnUrl(url);
      if (tcpFallbackUrl) {
        expandedTurnUrls.push(tcpFallbackUrl);
      }

      const tlsTcpFallbackUrl = this.buildTlsTcpFallbackTurnUrl(url);
      if (tlsTcpFallbackUrl) {
        expandedTurnUrls.push(tlsTcpFallbackUrl);
      }

      const udpFallbackUrl = this.buildUdpFallbackTurnUrl(url);
      if (udpFallbackUrl) {
        expandedTurnUrls.push(udpFallbackUrl);
      }
    }

    if (expandedTurnUrls.length > 0) {
      pushServer({
        urls: expandedTurnUrls,
        username: turnConfig?.username,
        credential: turnConfig?.credential,
      }, true);
    }

    return servers;
  }

  private normalizeIceUrls(
    rawUrls: Array<string | null | undefined>,
    prioritizeUdp: boolean
  ): string[] {
    const dedupe = new Set<string>();
    const normalized: string[] = [];

    for (const rawUrl of rawUrls) {
      const trimmed = String(rawUrl || '').trim();
      if (!trimmed) continue;

      if (this.isPlaceholderIceUrl(trimmed)) {
        if (!this.loggedPlaceholderIceUrls.has(trimmed)) {
          this.loggedPlaceholderIceUrls.add(trimmed);
          console.info(`[MediaEngine] Skipping placeholder ICE URL: ${trimmed}`);
        }
        continue;
      }

      if (this.shouldFilterIpv6LiteralIceUrl(trimmed)) {
        console.info(`[MediaEngine] Skipping IPv6 ICE URL on IPv4-only route: ${trimmed}`);
        continue;
      }

      if (dedupe.has(trimmed)) continue;
      dedupe.add(trimmed);
      normalized.push(trimmed);
    }

    if (!prioritizeUdp) {
      return normalized;
    }

    return normalized.sort((left, right) => {
      return this.getIceUrlPriority(left) - this.getIceUrlPriority(right);
    });
  }

  private getIceUrlPriority(url: string): number {
    const normalized = url.toLowerCase();
    const hasTransportUdp = /(?:\?|&)transport=udp(?:&|$)/.test(normalized);
    const hasTransportTcp = /(?:\?|&)transport=tcp(?:&|$)/.test(normalized);

    if (hasTransportUdp) return 0;
    if (!hasTransportTcp) return 1;
    if (normalized.startsWith('turns:')) return 3;
    return 2;
  }

  private isIpv6LiteralIceUrl(url: string): boolean {
    const match = url.match(/^(?:stun|stuns|turn|turns):(\[[^\]]+\])/i);
    return Boolean(match);
  }

  private isPlaceholderIceUrl(url: string): boolean {
    const normalized = url.toLowerCase();
    // Catch common placeholder patterns: example.com, your-*, ваш-*, non-ASCII domains
    return (
      normalized.includes('example.com') ||
      /(?:your|ваш)-.*\.(com|org|net)/i.test(url) ||
      /[а-яё]/i.test(url)
    );
  }

  private shouldFilterIpv6LiteralIceUrl(url: string): boolean {
    if (!this.isIpv6LiteralIceUrl(url)) {
      return false;
    }

    if (typeof window === 'undefined' || !window.location) {
      return false;
    }

    // If the app itself is reached over IPv6, keep literal IPv6 ICE URLs.
    const currentHost = String(window.location.hostname || '');
    return !currentHost.includes(':');
  }

  private buildUdpFallbackTurnUrl(url: string): string | null {
    const normalized = url.toLowerCase();
    if (!normalized.startsWith('turn:') && !normalized.startsWith('turns:')) {
      return null;
    }

    const hasTransportTcp = /(?:\?|&)transport=tcp(?:&|$)/.test(normalized);
    if (!hasTransportTcp) {
      // turns: without explicit transport has no UDP path by definition.
      if (normalized.startsWith('turns:') && !/(?:\?|&)transport=/.test(normalized)) {
        const base = `turn:${url.slice('turns:'.length)}`;
        const separator = base.includes('?') ? '&' : '?';
        return `${base}${separator}transport=udp`;
      }
      return null;
    }

    const withUdpTransport = url.replace(
      /([?&])transport=tcp(?=&|$)/i,
      '$1transport=udp'
    );

    // `turns` implies TLS-over-TCP. UDP fallback must use `turn`.
    if (withUdpTransport.toLowerCase().startsWith('turns:')) {
      return `turn:${withUdpTransport.slice('turns:'.length)}`;
    }

    return withUdpTransport;
  }

  private buildTcpFallbackTurnUrl(url: string): string | null {
    const normalized = url.toLowerCase();
    if (!normalized.startsWith('turn:') && !normalized.startsWith('turns:')) {
      return null;
    }

    if (/(?:\?|&)transport=tcp(?:&|$)/.test(normalized)) {
      return null;
    }

    if (/(?:\?|&)transport=udp(?:&|$)/.test(normalized)) {
      return url.replace(
        /([?&])transport=udp(?=&|$)/i,
        '$1transport=tcp'
      );
    }

    const separator = url.includes('?') ? '&' : '?';
    return `${url}${separator}transport=tcp`;
  }

  private buildTlsTcpFallbackTurnUrl(url: string): string | null {
    const normalized = url.toLowerCase();
    if (!normalized.startsWith('turn:')) {
      return null;
    }

    const tcpVariant = this.buildTcpFallbackTurnUrl(url) || url;
    return `turns:${tcpVariant.slice('turn:'.length)}`;
  }

  // ─────────────────────────────────────────────────────
  // Codec hardening
  // ─────────────────────────────────────────────────────

  /**
   * Narrow browser advertised video codecs before createOffer() to avoid
   * unstable profile negotiation (especially H264 profile fragmentation).
   */
  private setCodecPreferences(): Result<void, WebRTCError> {
    if (!this.sendPc) {
      return ok(undefined);
    }

    const caps = RTCRtpSender.getCapabilities?.('video');
    const codecs = caps?.codecs || [];
    if (codecs.length === 0) {
      return ok(undefined);
    }

    const preferredPrimaryCodecs = codecs.filter((codec) =>
      this.isPreferredVideoCodec(codec)
    );
    const retransmissionCodecs = this.selectAssociatedRtxCodecs(
      preferredPrimaryCodecs,
      codecs
    );
    const preferredCodecs = [...preferredPrimaryCodecs, ...retransmissionCodecs];

    if (preferredCodecs.length === 0) {
      return err(
        createWebRTCError(
          'NATIVE_SDP_REJECTION',
          'No compatible video codecs left after preference filtering',
          { retriable: true }
        )
      );
    }

    try {
      for (const transceiver of this.sendPc.getTransceivers()) {
        if (transceiver.sender.track?.kind !== 'video') continue;
        if (typeof transceiver.setCodecPreferences !== 'function') continue;
        transceiver.setCodecPreferences(preferredCodecs);
      }
      return ok(undefined);
    } catch (cause) {
      return err(
        createWebRTCError(
          'NATIVE_SDP_REJECTION',
          'Failed to apply codec preferences on transceiver',
          { retriable: true, cause }
        )
      );
    }
  }

  private isPreferredVideoCodec(codec: RTCRtpCodecCapability): boolean {
    const mimeType = String(codec.mimeType || '').toLowerCase();

    if (mimeType === 'video/vp8') {
      return true;
    }

    if (this.videoCodecPolicy === 'vp8-only') {
      return false;
    }

    // Explicitly reject HEVC/H265 and everything except H264 baseline family.
    if (mimeType === 'video/h265' || mimeType === 'video/hevc') {
      return false;
    }

    if (mimeType !== 'video/h264') {
      return false;
    }

    const fmtp = String(codec.sdpFmtpLine || '');
    const profileLevelId = this.extractFmtpParam(fmtp, 'profile-level-id').toLowerCase();
    if (!profileLevelId) return false;

    // Keep only the most stable H264 Baseline profiles:
    // - Constrained Baseline 42e01f
    // - Baseline 42001f
    return profileLevelId === '42e01f' || profileLevelId === '42001f';
  }

  private isRetransmissionVideoCodec(codec: RTCRtpCodecCapability): boolean {
    const mimeType = String(codec.mimeType || '').toLowerCase();
    return mimeType === 'video/rtx';
  }

  private getCodecPayloadType(codec: RTCRtpCodecCapability): number | null {
    const payloadType =
      typeof codec.preferredPayloadType === 'number'
        ? codec.preferredPayloadType
        : null;

    return Number.isFinite(payloadType) ? payloadType : null;
  }

  private selectAssociatedRtxCodecs(
    primaryCodecs: RTCRtpCodecCapability[],
    allCodecs: RTCRtpCodecCapability[]
  ): RTCRtpCodecCapability[] {
    const selectedPrimaryPts = new Set<number>();
    for (const codec of primaryCodecs) {
      const pt = this.getCodecPayloadType(codec);
      if (pt !== null) {
        selectedPrimaryPts.add(pt);
      }
    }

    if (selectedPrimaryPts.size === 0) {
      return [];
    }

    return allCodecs.filter((codec) => {
      if (!this.isRetransmissionVideoCodec(codec)) {
        return false;
      }

      const aptRaw = this.extractFmtpParam(String(codec.sdpFmtpLine || ''), 'apt');
      const apt = Number(aptRaw);
      if (!Number.isFinite(apt)) {
        return false;
      }

      // Keep only RTX that references codecs we actually kept.
      return selectedPrimaryPts.has(apt);
    });
  }

  private extractFmtpParam(fmtpLine: string, key: string): string {
    const chunks = fmtpLine.split(';').map((entry) => entry.trim());
    for (const chunk of chunks) {
      const [k, v] = chunk.split('=').map((entry) => entry.trim());
      if (k?.toLowerCase() === key.toLowerCase() && v) {
        return v;
      }
    }
    return '';
  }

  // ─────────────────────────────────────────────────────
  // Signaling event handlers
  // ─────────────────────────────────────────────────────

  private attachRecvPipelineStateListeners(): void {
    if (!this.recvPc) return;

    this.recvPc.addEventListener('signalingstatechange', () => {
      this.notifyRecvPipelineStateChanged();
    });
    this.recvPc.addEventListener('connectionstatechange', () => {
      this.notifyRecvPipelineStateChanged();
    });
    this.recvPc.addEventListener('iceconnectionstatechange', () => {
      this.notifyRecvPipelineStateChanged();
    });
  }

  private notifyRecvPipelineStateChanged(): void {
    if (this.recvPipelineWaiters.size === 0) return;
    const waiters = Array.from(this.recvPipelineWaiters);
    this.recvPipelineWaiters.clear();
    for (const resolve of waiters) {
      resolve();
    }
  }

  private waitForRecvPipelineStateChange(): Promise<void> {
    return new Promise((resolve) => {
      this.recvPipelineWaiters.add(resolve);
    });
  }

  private isRecvPipelineReadyForConsumer(): boolean {
    if (!this.canProcessConsumers || !this.joined) {
      return false;
    }

    if (!this.recvPc || !this.recvTransportData) {
      return false;
    }

    if (this.recvPc.signalingState !== 'stable') {
      return false;
    }

    // First consumer establishes DTLS for recv transport.
    // Subsequent consumers require an already connected recv transport.
    if (!this.recvTransportConnected && this.activeConsumers.size > 0) {
      return false;
    }

    return true;
  }

  private async waitForRecvPipelineReady(consumerId: string): Promise<void> {
    while (!this.isRecvPipelineReadyForConsumer()) {
      if (!this.joined || !this.canProcessConsumers) {
        throw createWebRTCError(
          'TRANSPORT_SETUP_FAILURE',
          `Receive pipeline unavailable for consumer ${consumerId}`,
          { retriable: true }
        );
      }
      await this.waitForRecvPipelineStateChange();
    }
  }

  private enqueueConsumer(data: unknown): void {
    const parsed = data as Partial<NewConsumerEvent>;
    const consumerId = String(parsed.consumerId || '').trim();
    const kind = parsed.kind === 'audio' || parsed.kind === 'video' ? parsed.kind : null;

    if (!consumerId || !kind || !parsed.rtpParameters) {
      console.warn('[MediaEngine] newConsumer missing required fields', data);
      return;
    }

    if (this.activeConsumers.has(consumerId) || this.queuedConsumerIds.has(consumerId)) {
      console.log(`[MediaEngine] Duplicate newConsumer ignored: ${consumerId}`);
      return;
    }

    this.consumerQueue.push({
      consumerId,
      producerId: parsed.producerId,
      kind,
      rtpParameters: parsed.rtpParameters,
      peerId: String(parsed.peerId || ''),
      displayName: String(parsed.displayName || ''),
    });
    this.queuedConsumerIds.add(consumerId);
    if (this.canProcessConsumers && this.joined) {
      void this.scheduleConsumerQueueDrain();
    }
  }

  private async scheduleConsumerQueueDrain(): Promise<void> {
    if (this.consumerQueueDrainPromise) {
      return this.consumerQueueDrainPromise;
    }

    this.consumerQueueDrainPromise = this.drainConsumerQueue()
      .catch((error) => {
        if (!this.joined || !this.canProcessConsumers) {
          return;
        }
        console.error('[MediaEngine] Consumer queue drain failed:', error);
      })
      .finally(() => {
        this.consumerQueueDrainPromise = null;
        if (this.consumerQueue.length > 0) {
          void this.scheduleConsumerQueueDrain();
        }
      });

    return this.consumerQueueDrainPromise;
  }

  private async drainConsumerQueue(): Promise<void> {
    while (this.consumerQueue.length > 0) {
      const next = this.consumerQueue[0];
      const consumerId = next.consumerId;

      try {
        await this.waitForRecvPipelineReady(consumerId);

        if (this.consumerQueue[0]?.consumerId !== consumerId) {
          continue;
        }

        await this.handleNewConsumer(next);

        if (this.consumerQueue[0]?.consumerId === consumerId) {
          this.consumerQueue.shift();
        } else {
          this.consumerQueue = this.consumerQueue.filter(
            (queuedConsumer) => queuedConsumer.consumerId !== consumerId
          );
        }
        this.queuedConsumerIds.delete(consumerId);
      } catch (error) {
        if (!this.joined || !this.canProcessConsumers) {
          return;
        }

        if (this.isRecoverableConsumerError(error)) {
          await this.waitForRecvPipelineStateChange();
          continue;
        }

        console.error(
          `[MediaEngine] Dropping consumer ${consumerId} after non-recoverable error`,
          error
        );
        this.removeQueuedConsumer(consumerId);
        this.events.onError?.(
          webRTCErrorFromUnknown(error, 'TRANSPORT_SETUP_FAILURE')
        );
      }
    }
  }

  private isRecoverableConsumerError(error: unknown): boolean {
    if (!error) return false;

    if (
      typeof error === 'object' &&
      error !== null &&
      'retriable' in (error as Record<string, unknown>)
    ) {
      return Boolean((error as { retriable?: boolean }).retriable);
    }

    const errorName = String((error as { name?: string })?.name || '').toLowerCase();
    if (errorName === 'invalidstateerror' || errorName === 'operationerror') {
      return true;
    }

    const message = String((error as { message?: string })?.message || '').toLowerCase();
    return message.includes('signalingstate') || message.includes('state');
  }

  private removeQueuedConsumer(consumerId: string): void {
    if (!consumerId) return;
    const beforeSize = this.consumerQueue.length;
    this.queuedConsumerIds.delete(consumerId);
    this.consumerQueue = this.consumerQueue.filter(
      (queuedConsumer) => queuedConsumer.consumerId !== consumerId
    );
    if (this.consumerQueue.length !== beforeSize) {
      this.notifyRecvPipelineStateChanged();
    }
  }

  private setupSignalingEvents(): void {
    this.signaling.on('newConsumer', (data: unknown) => {
      this.enqueueConsumer(data);
    });

    this.signaling.on('activeSpeakerUpdate', (data: any) => {
      this.events.onActiveSpeakers?.(data.speakers || []);
    });

    this.signaling.on('participantJoined', (data: any) => {
      this.events.onParticipantJoined?.(data.peerId, data.displayName);
    });

    this.signaling.on('participantLeft', (data: any) => {
      this.events.onParticipantLeft?.(data.peerId);
      const queueSizeBefore = this.consumerQueue.length;
      this.consumerQueue = this.consumerQueue.filter((queuedConsumer) => {
        if (queuedConsumer.peerId !== data.peerId) {
          return true;
        }
        this.queuedConsumerIds.delete(queuedConsumer.consumerId);
        return false;
      });
      if (this.consumerQueue.length !== queueSizeBefore) {
        this.notifyRecvPipelineStateChanged();
      }
      for (const [consumerId, rs] of this.remoteStreams) {
        if (rs.peerId === data.peerId) {
          this.remoteStreams.delete(consumerId);
          this.activeConsumers.delete(consumerId);
          this.removeQueuedConsumer(consumerId);
          this.deactivateMLineHistoryForConsumer(consumerId);
          this.events.onRemoteStreamRemoved?.(consumerId);
        }
      }
    });

    this.signaling.on('consumerClosed', (data: any) => {
      const consumerId = data.consumerId;
      this.activeConsumers.delete(consumerId);
      this.removeQueuedConsumer(consumerId);
      this.deactivateMLineHistoryForConsumer(consumerId);
      if (this.remoteStreams.has(consumerId)) {
        this.remoteStreams.delete(consumerId);
        this.events.onRemoteStreamRemoved?.(consumerId);
      }
    });

    this.signaling.on('reconnectFailed', () => {
      this.events.onError?.(
        createWebRTCError('SIGNALING_CONNECTION_FAILED', 'Signaling reconnect failed', {
          retriable: true,
        })
      );
    });

    this.signaling.on('signalingError', (error: WebRTCError) => {
      this.events.onError?.(error);
    });
  }

  /**
   * Serialize consumer negotiation — each newConsumer must complete
   * its SDP negotiation before the next one starts.
   */
  private async handleNewConsumer(data: NewConsumerEvent): Promise<void> {
    const negotiation = this.recvNegotiationLock.then(() => this.processNewConsumer(data));
    this.recvNegotiationLock = negotiation.catch((err) => {
      console.error('[MediaEngine] Consumer negotiation error:', err);
    });
    await negotiation;
  }

  /**
   * Core consumer receive pipeline:
   *  1) Register consumer metadata + assign a mid
   *  2) Build synthetic remote SDP offer from server transport params + all consumers' RTP params
   *  3) setRemoteDescription(offer) → browser creates ICE/DTLS connection to server
   *  4) createAnswer() → setLocalDescription(answer)
   *  5) connectTransport (DTLS) — first consumer only
   *  6) resumeConsumer → server starts sending RTP
   *  7) ontrack fires → handleRecvTrack matches track to consumer → RemoteStream
   */
  private async processNewConsumer(data: NewConsumerEvent): Promise<void> {
    const {
      consumerId,
      kind,
      rtpParameters,
      peerId,
      displayName,
    } = data;

    if (!consumerId || !kind) {
      console.warn('[MediaEngine] newConsumer missing consumerId or kind', data);
      return;
    }

    if (this.activeConsumers.has(consumerId)) {
      // Duplicate notification for the same consumer can cause mid churn and
      // unstable re-offers; keep the first registration.
      console.log(`[MediaEngine] Duplicate newConsumer ignored: ${consumerId}`);
      return;
    }

    if (!this.recvPc || !this.recvTransportData) {
      throw createWebRTCError(
        'TRANSPORT_SETUP_FAILURE',
        `Receive pipeline not ready for consumer ${consumerId}`,
        { retriable: true }
      );
    }

    // ── Proactive codec filtering ──
    // Validate consumer's codecs against browser receiver capabilities BEFORE
    // inserting into SDP to prevent NATIVE_SDP_REJECTION ("mid should be rejected").
    const filteredRtpParameters = this.filterConsumerCodecsAgainstBrowser(kind, rtpParameters);
    const primaryCodecs = (filteredRtpParameters.codecs || []).filter(
      (c: any) => !String(c.mimeType || '').toLowerCase().endsWith('/rtx')
    );

    if (primaryCodecs.length === 0) {
      console.warn(
        `[MediaEngine] Consumer ${consumerId} (${kind}) rejected: no compatible codecs after browser capability filtering. ` +
          `Original codecs: ${JSON.stringify((rtpParameters.codecs || []).map((c: any) => c.mimeType))}`
      );
      this.events.onError?.(
        createWebRTCError(
          'NATIVE_SDP_REJECTION',
          `No supported ${kind} codecs for consumer ${consumerId} — browser lacks compatible decoder`,
          { retriable: false }
        )
      );
      return;
    }

    const mid = this.allocateFreshRecvMid();
    console.log(
      `[MediaEngine] newConsumer: ${kind} mid=${mid} consumerId=${consumerId} from=${displayName} (${peerId})`
    );

    // Register consumer with assigned mid and filtered RTP parameters.
    this.activeConsumers.set(consumerId, {
      consumerId,
      mid,
      kind,
      rtpParameters: filteredRtpParameters,
      peerId,
      displayName,
    });

    // Append to m-line history (never removed, only deactivated).
    this.recvMLineHistory.push({
      mid,
      kind,
      consumerId,
      rtpParameters: filteredRtpParameters,
      active: true,
    });
    this.logRecvNegotiationSnapshot('consumer-registered', {
      consumerId,
      kind,
      assignedMid: mid,
      queueLength: this.consumerQueue.length,
    });

    try {
      await this.applyRecvNegotiation();
    } catch (err) {
      const rejectedMid = this.extractRejectedMidFromNegotiationError(err);
      let recoveredFromRejectedMid = false;
      this.logRecvNegotiationSnapshot('consumer-negotiation-error-initial', {
        consumerId,
        assignedMid: mid,
        rejectedMid,
        error: this.getErrorMessage(err),
      });

      // Browser can reject a previously closed m-line. Keep local SDP history in
      // sync and try one fast renegotiation before dropping the new consumer.
      if (rejectedMid) {
        const preserveConsumerId = rejectedMid === mid ? consumerId : undefined;
        this.forceRejectMid(rejectedMid, { preserveConsumerId });
        this.logRecvNegotiationSnapshot('consumer-negotiation-after-force-reject', {
          consumerId,
          assignedMid: mid,
          rejectedMid,
          preserveConsumerId: preserveConsumerId || null,
        });

        if (rejectedMid === mid) {
          const reassignedMid = this.reassignConsumerToFreshMid({
            consumerId,
            kind,
            rtpParameters: filteredRtpParameters,
            peerId,
            displayName,
            rejectedMid,
          });
          if (!reassignedMid) {
            err = createWebRTCError(
              'NATIVE_SDP_REJECTION',
              `Failed to recover consumer ${consumerId} from rejected mid ${rejectedMid}`,
              { retriable: true, cause: err }
            );
          }
          this.logRecvNegotiationSnapshot('consumer-negotiation-after-reassign', {
            consumerId,
            previousMid: mid,
            reassignedMid: this.activeConsumers.get(consumerId)?.mid || null,
          });
        }

        if (rejectedMid !== mid || this.activeConsumers.has(consumerId)) {
          try {
            await this.applyRecvNegotiation();
            recoveredFromRejectedMid = true;
            this.logRecvNegotiationSnapshot('consumer-negotiation-retry-succeeded', {
              consumerId,
              rejectedMid,
              activeMid: this.activeConsumers.get(consumerId)?.mid || null,
            });
          } catch (retryErr) {
            err = retryErr;
            const retryRejectedMid = this.extractRejectedMidFromNegotiationError(retryErr);
            if (retryRejectedMid) {
              this.forceRejectMid(retryRejectedMid);
            }
            this.logRecvNegotiationSnapshot('consumer-negotiation-retry-failed', {
              consumerId,
              rejectedMid: retryRejectedMid || rejectedMid,
              error: this.getErrorMessage(retryErr),
            });
          }
        }
      }

      if (!this.recvTransportConnected) {
        // No recv transport means renegotiation did not recover.
        console.error('[MediaEngine] Failed to negotiate recvPc for consumer', consumerId, err);
      } else if (!this.activeConsumers.has(consumerId)) {
        // The consumer may have been force-rejected while healing stale mids.
        return;
      } else if (recoveredFromRejectedMid) {
        // Recovery path succeeded.
      } else {
        console.error('[MediaEngine] Failed to negotiate recvPc for consumer', consumerId, err);
      }

      if (!this.activeConsumers.has(consumerId)) {
        return;
      }

      // Mark m-line as inactive but keep in history for stable ordering.
      this.activeConsumers.delete(consumerId);
      this.deactivateMLineHistoryForConsumer(consumerId);
      if (this.remoteStreams.has(consumerId)) {
        this.remoteStreams.delete(consumerId);
        this.events.onRemoteStreamRemoved?.(consumerId);
      }
      this.events.onError?.(
        webRTCErrorFromUnknown(err, 'TRANSPORT_SETUP_FAILURE')
      );
      return;
    }

    // Resume only after SDP is applied locally and (for first consumer) DTLS is connected.
    if (!this.activeConsumers.has(consumerId)) {
      console.warn(
        `[MediaEngine] Consumer ${consumerId} was rejected by local SDP, skipping resume`
      );
      return;
    }
    await this.resumeConsumerAfterSdpApplied(consumerId);
  }

  /**
   * Проверяет, что recv-транспорт находится в рабочем состоянии.
   * Возвращает false, если ICE или DTLS соединение завершилось с ошибкой —
   * в этом случае вызывать resumeConsumer бессмысленно и опасно.
   */
  private isRecvTransportHealthy(): boolean {
    if (!this.recvPc) return false;
    const ice = this.recvPc.iceConnectionState;
    const conn = this.recvPc.connectionState;
    // 'disconnected' — временный сбой, может восстановиться; прерываем цикл retry.
    // 'failed' / 'closed' — финальные состояния, дальнейшие попытки бессмысленны.
    if (ice === 'failed' || ice === 'disconnected') return false;
    if (conn === 'failed' || conn === 'disconnected' || conn === 'closed') return false;
    return true;
  }

  private async resumeConsumerAfterSdpApplied(consumerId: string): Promise<void> {
    // Ранняя проверка: если транспорт уже не работает, не начинаем попытки.
    // Это исправляет гонку: DTLS failed → C++ worker уничтожает Consumer →
    // клиент с задержкой пытается вызвать resume() → "Consumer not found" в цикле.
    if (!this.isRecvTransportHealthy()) {
      console.warn(
        `[MediaEngine] resumeConsumer ${consumerId} пропущен — ` +
        `транспорт не подключён (ICE: ${this.recvPc?.iceConnectionState}, ` +
        `conn: ${this.recvPc?.connectionState})`
      );
      this.dropConsumerState(consumerId);
      return;
    }

    for (
      let attempt = 1;
      attempt <= MediaEngine.RESUME_CONSUMER_MAX_ATTEMPTS;
      attempt++
    ) {
      // Проверяем состояние транспорта перед каждой попыткой.
      // Если ICE перешёл в disconnected/failed во время retry — прекращаем.
      if (!this.isRecvTransportHealthy()) {
        console.warn(
          `[MediaEngine] resumeConsumer ${consumerId} прерван на попытке ${attempt} — ` +
          `транспорт отключился (ICE: ${this.recvPc?.iceConnectionState})`
        );
        this.dropConsumerState(consumerId);
        return;
      }

      const resumeResult = await this.signaling.request('resumeConsumer', { consumerId });
      if (resumeResult.ok) {
        return;
      }

      const resumeErrorMessage = String(resumeResult.error?.message || '');
      if (/consumer\s+.+\s+(не найден|not found|already closed)/i.test(resumeErrorMessage)) {
        // Consumer уничтожен сервером (DTLS failure, peer disconnect) — это ожидаемо.
        console.warn(
          `[MediaEngine] Consumer ${consumerId} не найден на сервере, удаляем устаревшую запись`
        );
        this.dropConsumerState(consumerId);
        return;
      }

      const isLastAttempt =
        attempt >= MediaEngine.RESUME_CONSUMER_MAX_ATTEMPTS || !this.signaling.connected;
      if (isLastAttempt) {
        console.error(
          `[MediaEngine] resumeConsumer failed for ${consumerId} after ${attempt} attempt(s): ${resumeErrorMessage || 'unknown error'}`
        );
        this.dropConsumerState(consumerId);

        if (this.signaling.connected) {
          const syncResult = await this.signaling.request('syncConsumers', {});
          if (!syncResult.ok) {
            this.events.onError?.(syncResult.error);
          }
        }

        this.events.onError?.(resumeResult.error);
        return;
      }

      await this.wait(MediaEngine.RESUME_CONSUMER_RETRY_DELAY_MS);
    }
  }

  private dropConsumerState(consumerId: string): void {
    this.activeConsumers.delete(consumerId);
    this.removeQueuedConsumer(consumerId);
    this.deactivateMLineHistoryForConsumer(consumerId);
    if (this.remoteStreams.has(consumerId)) {
      this.remoteStreams.delete(consumerId);
      this.events.onRemoteStreamRemoved?.(consumerId);
    }
  }

  private async wait(ms: number): Promise<void> {
    await new Promise<void>((resolve) => {
      setTimeout(resolve, ms);
    });
  }

  /**
   * Handle incoming track on recvPc — match it with an active consumer
   * by transceiver mid and create a RemoteStream.
   */
  private handleRecvTrack(event: RTCTrackEvent): void {
    const track = event.track;
    const mid = event.transceiver?.mid?.trim() ?? null;
    const stream = event.streams?.[0] || new MediaStream([track]);

    console.log(
      `[MediaEngine] handleRecvTrack: kind=${track.kind} mid=${mid} id=${track.id} readyState=${track.readyState}`
    );

    // DIAGNOSTIC: Log track details for debugging
    if (this.recvDiagEnabled) {
      console.log('[MediaEngine] Track details:', {
        kind: track.kind,
        id: track.id,
        label: track.label,
        readyState: track.readyState,
        enabled: track.enabled,
        muted: track.muted,
        mid: mid,
        transceiverMid: event.transceiver?.mid,
        streamId: stream?.id,
        streamTrackCount: stream?.getTracks().length,
      });
    }

    type ConsumerEntry = {
      consumerId: string;
      mid: string;
      kind: 'audio' | 'video';
      rtpParameters: any;
      peerId: string;
      displayName: string;
    };

    // Match by transceiver mid → consumer mid.
    let matchedConsumer: ConsumerEntry | null = null;
    if (mid !== null) {
      for (const [, consumer] of this.activeConsumers) {
        if (consumer.mid === mid) {
          matchedConsumer = consumer;
          break;
        }
      }
    }

    // Fallback 1: match by kind among consumers that don't have a remote stream yet.
    if (!matchedConsumer) {
      for (const [, consumer] of this.activeConsumers) {
        if (consumer.kind === track.kind && !this.remoteStreams.has(consumer.consumerId)) {
          matchedConsumer = consumer;
          console.log(
            `[MediaEngine] handleRecvTrack fallback match: consumer=${consumer.consumerId} kind=${consumer.kind}`
          );
          break;
        }
      }
    }

    // Fallback 2: match by transceiver index (ordered by mid number).
    if (!matchedConsumer && this.recvPc) {
      const transceivers = this.recvPc.getTransceivers();
      const idx = transceivers.indexOf(event.transceiver);
      if (idx >= 0) {
        const consumers = Array.from(this.activeConsumers.values());
        if (idx < consumers.length && !this.remoteStreams.has(consumers[idx].consumerId)) {
          matchedConsumer = consumers[idx];
          console.log(
            `[MediaEngine] handleRecvTrack index fallback: idx=${idx} consumer=${matchedConsumer.consumerId}`
          );
        }
      }
    }

    if (!matchedConsumer) {
      console.warn(
        `[MediaEngine] Received track without matching consumer, mid=${mid}, kind=${track.kind}, ` +
        `activeConsumers=${this.activeConsumers.size}, remoteStreams=${this.remoteStreams.size}`
      );
      
      // DIAGNOSTIC: Log active consumers for debugging
      if (this.recvDiagEnabled) {
        console.log('[MediaEngine] Active consumers:', Array.from(this.activeConsumers.entries()));
        console.log('[MediaEngine] Remote streams:', Array.from(this.remoteStreams.entries()));
      }
      
      return;
    }

    const remoteStream: RemoteStream = {
      peerId: matchedConsumer.peerId,
      displayName: matchedConsumer.displayName,
      consumerId: matchedConsumer.consumerId,
      kind: matchedConsumer.kind as 'audio' | 'video',
      track,
      stream,
    };

    this.remoteStreams.set(matchedConsumer.consumerId, remoteStream);
    this.events.onRemoteStream?.(remoteStream);
    console.log(
      `[MediaEngine] Remote stream ready: ${matchedConsumer.kind} from ${matchedConsumer.displayName} (consumer=${matchedConsumer.consumerId})`
    );
    
    // DIAGNOSTIC: Verify stream is properly configured
    if (this.recvDiagEnabled) {
      const videoTracks = stream.getVideoTracks();
      const audioTracks = stream.getAudioTracks();
      console.log('[MediaEngine] Stream tracks after onRemoteStream:', {
        videoCount: videoTracks.length,
        audioCount: audioTracks.length,
        videoTracks: videoTracks.map(t => ({ id: t.id, readyState: t.readyState, enabled: t.enabled })),
        audioTracks: audioTracks.map(t => ({ id: t.id, readyState: t.readyState, enabled: t.enabled })),
      });
    }
  }

  /**
   * Build a synthetic SDP remote offer from the mediasoup transport parameters
   * and all active consumers' RTP parameters.
   *
   * This is what mediasoup-client does internally — we replicate it here
   * to avoid the dependency.
   */
  private buildRecvOfferSdp(): string {
    this.reconcileRejectedMidsFromCurrentDescriptions();
    this.ensureHardRejectedMidsHaveHistoryEntries();

    const td = this.recvTransportData!;
    const iceParams = td.iceParameters as any;
    const dtlsParams = td.dtlsParameters as any;
    const iceCandidates = td.iceCandidates as any[];

    // DIAGNOSTIC: Log ICE candidates received from SFU
    if (this.iceDiagEnabled) {
      console.log('[MediaEngine] SFU ICE Candidates:', JSON.stringify(iceCandidates, null, 2));
    }

    // BUNDLE group must only include active (non-rejected) m-lines.
    // Chrome rejects offers where a mid in BUNDLE has port=0.
    const bundleMids = this.recvMLineHistory
      .filter(m => m.active && !this.hardRejectedRecvMids.has(m.mid))
      .map(m => m.mid);

    let sdp = '';
    sdp += 'v=0\r\n';
    sdp += `o=mediasoup-server ${Date.now()} 2 IN IP4 127.0.0.1\r\n`;
    sdp += 's=-\r\n';
    sdp += 't=0 0\r\n';
    sdp += `a=group:BUNDLE ${bundleMids.join(' ')}\r\n`;
    sdp += 'a=msid-semantic: WMS *\r\n';

    // ice-lite at session level (mediasoup is always ice-lite)
    if (iceParams.iceLite) {
      sdp += 'a=ice-lite\r\n';
    }

    for (let i = 0; i < this.recvMLineHistory.length; i++) {
      const entry = this.recvMLineHistory[i];
      const codecs = entry.rtpParameters?.codecs || [];
      const headerExtensions = entry.rtpParameters?.headerExtensions || [];
      const encoding = entry.rtpParameters?.encodings?.[0];
      const isHardRejectedMid = this.hardRejectedRecvMids.has(entry.mid);

      if (isHardRejectedMid && entry.active) {
        entry.active = false;
      }

      if (!entry.active || isHardRejectedMid) {
        // Inactive (closed) m-line: port 0 marks it as rejected.
        // Must still appear in the same position to preserve ordering.
        const pts = codecs.length > 0
          ? codecs.map((c: any) => c.payloadType).join(' ')
          : '0';
        sdp += `m=${entry.kind} 0 UDP/TLS/RTP/SAVPF ${pts}\r\n`;
        sdp += 'c=IN IP4 0.0.0.0\r\n';
        sdp += `a=mid:${entry.mid}\r\n`;
        sdp += 'a=inactive\r\n';
        continue;
      }

      const pts = codecs.map((c: any) => c.payloadType).join(' ');

      sdp += `m=${entry.kind} 7 UDP/TLS/RTP/SAVPF ${pts}\r\n`;
      sdp += 'c=IN IP4 0.0.0.0\r\n';
      sdp += 'a=rtcp:9 IN IP4 0.0.0.0\r\n';

      // ICE credentials (per m= line, required for BUNDLE)
      sdp += `a=ice-ufrag:${iceParams.usernameFragment}\r\n`;
      sdp += `a=ice-pwd:${iceParams.password}\r\n`;

      // DTLS fingerprints
      for (const fp of dtlsParams.fingerprints || []) {
        sdp += `a=fingerprint:${fp.algorithm} ${fp.value}\r\n`;
      }
      sdp += 'a=setup:actpass\r\n';

      sdp += `a=mid:${entry.mid}\r\n`;
      sdp += 'a=sendonly\r\n';
      sdp += 'a=rtcp-mux\r\n';
      sdp += 'a=rtcp-rsize\r\n';

      // Codec rtpmap + fmtp + rtcp-fb
      for (const codec of codecs) {
        const codecName = (codec.mimeType || '').split('/')[1];
        const channels = codec.channels && codec.channels > 1 ? `/${codec.channels}` : '';
        sdp += `a=rtpmap:${codec.payloadType} ${codecName}/${codec.clockRate}${channels}\r\n`;

        const fmtpParts = Object.entries(codec.parameters || {})
          .map(([k, v]) => `${k}=${v}`)
          .join(';');
        if (fmtpParts) {
          sdp += `a=fmtp:${codec.payloadType} ${fmtpParts}\r\n`;
        }

        for (const fb of codec.rtcpFeedback || []) {
          const fbStr = fb.parameter ? `${fb.type} ${fb.parameter}` : fb.type;
          sdp += `a=rtcp-fb:${codec.payloadType} ${fbStr}\r\n`;
        }
      }

      // Header extensions
      for (const ext of headerExtensions) {
        sdp += `a=extmap:${ext.id} ${ext.uri}\r\n`;
      }

      // msid at media level (Unified Plan requires this instead of ssrc-level msid)
      const msid = `mediasoup-${entry.mid}`;
      const trackLabel = `${entry.kind}-${entry.mid}`;
      sdp += `a=msid:${msid} ${trackLabel}\r\n`;

      // SSRC lines. Keep a single track identity (same msid/trackLabel) for
      // primary+RTX SSRC to satisfy Unified Plan parser requirements.
      const ssrc = encoding?.ssrc;
      const cname = entry.rtpParameters.rtcp?.cname || 'mediasoup';
      if (ssrc) {
        sdp += `a=ssrc:${ssrc} cname:${cname}\r\n`;
        sdp += `a=ssrc:${ssrc} msid:${msid} ${trackLabel}\r\n`;

        // RTX SSRC (retransmission)
        const rtxSsrc = encoding?.rtx?.ssrc;
        if (rtxSsrc) {
          sdp += `a=ssrc:${rtxSsrc} cname:${cname}\r\n`;
          sdp += `a=ssrc:${rtxSsrc} msid:${msid} ${trackLabel}\r\n`;
          sdp += `a=ssrc-group:FID ${ssrc} ${rtxSsrc}\r\n`;
        }
      }

      // ICE candidates (on every m= line for compatibility)
      let validCandidateCount = 0;
      let invalidCandidateCount = 0;
      
      for (const cand of iceCandidates) {
        // Validate and log candidate issues
        const candidateIp = cand.ip;
        const isPrivateIp = candidateIp && (
          candidateIp.startsWith('10.') ||
          candidateIp.startsWith('192.168.') ||
          candidateIp.startsWith('172.16.') ||
          candidateIp.startsWith('127.') ||
          candidateIp === '0.0.0.0'
        );

        if (this.iceDiagEnabled) {
          console.log(
            `[MediaEngine] ICE Candidate: ${cand.foundation} ${cand.protocol} ${cand.ip}:${cand.port} ` +
            `type=${cand.type} priority=${cand.priority} ${isPrivateIp ? '(PRIVATE)' : '(PUBLIC)'}`
          );
        }

        // Skip invalid candidates (0.0.0.0 is not useful for remote peers)
        if (candidateIp === '0.0.0.0') {
          invalidCandidateCount++;
          if (this.iceDiagEnabled) {
            console.warn('[MediaEngine] Skipping 0.0.0.0 candidate - not useful for remote connection');
          }
          continue;
        }

        validCandidateCount++;
        let line = `a=candidate:${cand.foundation} 1 ${cand.protocol} ${cand.priority} ${cand.ip} ${cand.port} typ ${cand.type}`;
        if (cand.protocol === 'tcp' && cand.tcpType) {
          line += ` tcptype ${cand.tcpType}`;
        }
        sdp += line + '\r\n';
      }
      
      if (this.iceDiagEnabled) {
        console.log(
          `[MediaEngine] ICE Candidates summary: ${validCandidateCount} valid, ` +
          `${invalidCandidateCount} invalid (0.0.0.0)`
        );
      }
      
      sdp += 'a=end-of-candidates\r\n';
    }

    // DIAGNOSTIC: Log final SDP offer for debugging
    if (this.recvDiagEnabled) {
      console.log('[MediaEngine] Recv Offer SDP (first 500 chars):\n', sdp.substring(0, 500));
    }

    return sdp;
  }

  private async applyRecvNegotiation(): Promise<void> {
    if (!this.recvPc || !this.recvTransportData) {
      throw createWebRTCError('TRANSPORT_SETUP_FAILURE', 'Receive pipeline is not initialized', {
        retriable: true,
      });
    }

    const offerSdp = this.buildRecvOfferSdp();
    const offerSummary = this.summarizeSdpMSections(offerSdp);
    this.logRecvNegotiationSnapshot('before-setRemoteDescription', {
      offerSummary,
    });
    this.prepareRecvTransceiversForOffer();
    try {
      await this.recvPc.setRemoteDescription({
        type: 'offer',
        sdp: offerSdp,
      });
    } catch (error) {
      this.logRecvNegotiationSnapshot('setRemoteDescription-failed', {
        offerSummary,
        rejectedMid: this.extractRejectedMidFromNegotiationError(error),
        error: this.getErrorMessage(error),
      });
      throw error;
    }

    const answer = await this.recvPc.createAnswer();

    // Connect recv transport BEFORE setLocalDescription.
    // Chrome does not initiate DTLS until it has both a local AND a remote description.
    // By awaiting connectTransport here (SFU stores our fingerprint) and only then
    // calling setLocalDescription, we guarantee that when Chrome eventually sends
    // a DTLS ClientHello the SFU already knows our certificate — eliminating the
    // race condition where same-LAN ICE completes in < 10 ms and Chrome fires
    // a ClientHello before the SFU has our fingerprint.
    if (!this.recvTransportConnected) {
      const dtlsParams = this.extractDtlsFromSdp(answer.sdp || '');
      const connectResult = await this.signaling.request('connectTransport', {
        transportId: this.recvTransportData.id,
        dtlsParameters: dtlsParams,
      });

      if (!connectResult.ok) {
        throw connectResult.error;
      }

      this.recvTransportConnected = true;
      console.log('[MediaEngine] Recv transport connected (DTLS)');
      this.notifyRecvPipelineStateChanged();
    }

    await this.recvPc.setLocalDescription(answer);

    // Browser may reject some m-lines while generating local answer.
    // Keep internal m-line state synchronized to avoid future
    // "mid should be rejected" errors on subsequent offers.
    this.reconcileRejectedMidsFromCurrentDescriptions();
    this.logRecvNegotiationSnapshot('after-setLocalDescription', {
      answerSummary: this.summarizeSdpMSections(answer.sdp || ''),
    });
  }

  private prepareRecvTransceiversForOffer(): void {
    if (!this.recvPc) {
      return;
    }

    for (const transceiver of this.recvPc.getTransceivers()) {
      if (transceiver.stopped) continue;
      if (transceiver.sender.track) continue;
      if (transceiver.direction === 'recvonly' || transceiver.direction === 'inactive') {
        continue;
      }

      try {
        transceiver.direction = 'recvonly';
      } catch (err) {
        console.warn('[MediaEngine] Failed to set transceiver direction=recvonly', err);
      }
    }
  }

  private extractRejectedMidFromNegotiationError(error: unknown): string | null {
    const collectMessages = (value: unknown, acc: string[]): void => {
      if (!value) return;

      if (typeof value === 'string') {
        acc.push(value);
        return;
      }

      if (value instanceof Error) {
        acc.push(value.message);
        const maybeCause = (value as Error & { cause?: unknown }).cause;
        if (maybeCause && maybeCause !== value) {
          collectMessages(maybeCause, acc);
        }
        return;
      }

      if (typeof value === 'object') {
        const record = value as Record<string, unknown>;
        if (typeof record.message === 'string') {
          acc.push(record.message);
        }
        if (record.cause && record.cause !== value) {
          collectMessages(record.cause, acc);
        }
      }
    };

    const messages: string[] = [];
    collectMessages(error, messages);
    messages.push(String(error ?? ''));

    const patterns = [
      /mid=['"]?([^'".\s]+)['"]?\s+should be rejected/i,
      /mid=['"]?([^'".\s]+)['"]?.+rejected/i,
    ];

    for (const message of messages) {
      for (const pattern of patterns) {
        const match = message.match(pattern);
        if (match?.[1]) {
          return match[1];
        }
      }
    }

    return null;
  }

  private getErrorMessage(error: unknown): string {
    if (typeof error === 'string') {
      return error;
    }
    if (error instanceof Error) {
      return error.message;
    }
    if (typeof error === 'object' && error && 'message' in error) {
      const message = (error as { message?: unknown }).message;
      if (typeof message === 'string') {
        return message;
      }
    }
    return String(error ?? 'unknown error');
  }

  private summarizeSdpMSections(sdp: string): Array<{
    index: number;
    kind: string;
    mid: string | null;
    rejected: boolean;
    direction: string | null;
  }> {
    const sections: Array<{
      index: number;
      kind: string;
      mid: string | null;
      rejected: boolean;
      direction: string | null;
    }> = [];

    if (!sdp) {
      return sections;
    }

    const lines = sdp.split('\r\n');
    let current:
      | {
          index: number;
          kind: string;
          mid: string | null;
          rejected: boolean;
          direction: string | null;
        }
      | null = null;

    const flush = () => {
      if (current) {
        sections.push(current);
        current = null;
      }
    };

    for (const line of lines) {
      if (line.startsWith('m=')) {
        flush();
        const tokens = line.slice(2).trim().split(/\s+/);
        current = {
          index: sections.length,
          kind: tokens[0] || 'unknown',
          mid: null,
          rejected: tokens[1] === '0',
          direction: null,
        };
        continue;
      }

      if (!current) {
        continue;
      }

      if (line.startsWith('a=mid:')) {
        current.mid = line.slice('a=mid:'.length).trim() || null;
        continue;
      }

      if (
        line === 'a=inactive' ||
        line === 'a=sendonly' ||
        line === 'a=recvonly' ||
        line === 'a=sendrecv'
      ) {
        current.direction = line.slice('a='.length);
      }
    }

    flush();
    return sections;
  }

  private logRecvNegotiationSnapshot(
    stage: string,
    extra: Record<string, unknown> = {}
  ): void {
    if (!this.recvDiagEnabled || !this.recvPc) {
      return;
    }

    const transceivers = this.recvPc.getTransceivers().map((transceiver, index) => ({
      index,
      mid: transceiver.mid || null,
      stopped: transceiver.stopped,
      direction: transceiver.direction,
      currentDirection: transceiver.currentDirection || null,
      receiverTrackKind: transceiver.receiver.track?.kind || null,
      receiverTrackState: transceiver.receiver.track?.readyState || null,
    }));

    const activeConsumers = Array.from(this.activeConsumers.values()).map((consumer) => ({
      consumerId: consumer.consumerId,
      mid: consumer.mid,
      kind: consumer.kind,
      peerId: consumer.peerId,
    }));

    const mLineHistory = this.recvMLineHistory.map((entry, index) => ({
      index,
      mid: entry.mid,
      kind: entry.kind,
      consumerId: entry.consumerId,
      active: entry.active,
      hardRejected: this.hardRejectedRecvMids.has(entry.mid),
    }));

    console.debug('[MediaEngine][RecvDiag]', {
      stage,
      recvPcSignalingState: this.recvPc.signalingState,
      recvPcIceConnectionState: this.recvPc.iceConnectionState,
      recvTransportConnected: this.recvTransportConnected,
      nextRecvMid: this.nextRecvMid,
      hardRejectedMids: Array.from(this.hardRejectedRecvMids),
      activeConsumers,
      mLineHistory,
      transceivers,
      ...extra,
    });
  }

  private reconcileRejectedMidsFromCurrentDescriptions(): void {
    if (!this.recvPc) return;

    const candidateSdps = this.getRecvDescriptionSdps();

    if (candidateSdps.length === 0) {
      return;
    }

    const rejectedMids = new Set<string>();
    for (const sdp of candidateSdps) {
      const mids = this.extractRejectedMidsFromSdp(sdp);
      for (const mid of mids) {
        rejectedMids.add(mid);
      }
    }

    for (const mid of this.extractStoppedTransceiverMids()) {
      rejectedMids.add(mid);
    }

    if (rejectedMids.size > 0) {
      this.logRecvNegotiationSnapshot('reconcile-rejected-mids', {
        rejectedMids: Array.from(rejectedMids),
      });
    }

    for (const mid of rejectedMids) {
      this.forceRejectMid(mid);
    }

    this.ensureHardRejectedMidsHaveHistoryEntries();
  }

  private extractStoppedTransceiverMids(): Set<string> {
    const mids = new Set<string>();
    if (!this.recvPc) {
      return mids;
    }

    const transceivers = this.recvPc.getTransceivers();
    for (let i = 0; i < transceivers.length; i++) {
      const transceiver = transceivers[i];
      if (!transceiver.stopped) {
        continue;
      }
      
      const mid = transceiver.mid?.trim();
      if (mid) {
        mids.add(mid);
      } else if (i < this.recvMLineHistory.length) {
        // Fallback: transceivers are chronologically ordered in Unified Plan.
        // If a stopped transceiver has no mid, we map it by index.
        mids.add(this.recvMLineHistory[i].mid);
      }
    }

    return mids;
  }

  private extractRejectedMidsFromSdp(sdp: string): Set<string> {
    const rejectedMids = new Set<string>();
    const lines = sdp.split('\r\n');

    let currentMid: string | null = null;
    let currentRejected = false;
    let mLineIndex = -1;

    const flushSection = () => {
      if (currentRejected) {
        if (currentMid) {
          rejectedMids.add(currentMid);
        } else if (mLineIndex >= 0 && mLineIndex < this.recvMLineHistory.length) {
          // Chrome often drops the a=mid attribute in its answer when rejecting 
          // a transceiver. We must fallback to the chronological index to figure 
          // out which mid was dropped.
          rejectedMids.add(this.recvMLineHistory[mLineIndex].mid);
        }
      }
      currentMid = null;
      currentRejected = false;
    };

    for (const line of lines) {
      if (line.startsWith('m=')) {
        flushSection();
        mLineIndex++;
        const tokens = line.split(/\s+/);
        currentRejected = tokens[1] === '0';
        continue;
      }

      if (line.startsWith('a=mid:')) {
        currentMid = line.slice('a=mid:'.length).trim();
      }
    }

    flushSection();
    return rejectedMids;
  }

  private forceRejectMid(
    mid: string,
    options: { preserveConsumerId?: string } = {}
  ): void {
    if (!mid) return;
    const { preserveConsumerId } = options;
    this.hardRejectedRecvMids.add(mid);

    const affectedConsumerIds = new Set<string>();
    for (const [consumerId, consumer] of this.activeConsumers) {
      if (consumer.mid === mid) {
        if (preserveConsumerId && consumerId === preserveConsumerId) {
          continue;
        }
        affectedConsumerIds.add(consumerId);
        this.activeConsumers.delete(consumerId);
      }
    }

    for (const entry of this.recvMLineHistory) {
      if (entry.mid === mid) {
        entry.active = false;
        if (!preserveConsumerId || entry.consumerId !== preserveConsumerId) {
          affectedConsumerIds.add(entry.consumerId);
        }
      }
    }

    for (const consumerId of affectedConsumerIds) {
      if (this.remoteStreams.has(consumerId)) {
        this.remoteStreams.delete(consumerId);
        this.events.onRemoteStreamRemoved?.(consumerId);
      }
      this.removeQueuedConsumer(consumerId);
    }

    this.logRecvNegotiationSnapshot('force-reject-mid', {
      mid,
      preserveConsumerId: preserveConsumerId || null,
      affectedConsumerIds: Array.from(affectedConsumerIds),
      hardRejectedMids: Array.from(this.hardRejectedRecvMids),
    });
  }

  private deactivateMLineHistoryForConsumer(consumerId: string): void {
    if (!consumerId) return;
    for (const entry of this.recvMLineHistory) {
      if (entry.consumerId === consumerId) {
        entry.active = false;
      }
    }
  }

  private reassignConsumerToFreshMid({
    consumerId,
    kind,
    rtpParameters,
    peerId,
    displayName,
    rejectedMid,
  }: {
    consumerId: string;
    kind: 'audio' | 'video';
    rtpParameters: any;
    peerId: string;
    displayName: string;
    rejectedMid: string;
  }): string | null {
    if (!this.activeConsumers.has(consumerId)) {
      return null;
    }

    this.deactivateMLineHistoryForConsumer(consumerId);

    const newMid = this.allocateFreshRecvMid();
    this.hardRejectedRecvMids.delete(newMid);
    this.activeConsumers.set(consumerId, {
      consumerId,
      mid: newMid,
      kind,
      rtpParameters,
      peerId,
      displayName,
    });
    this.recvMLineHistory.push({
      mid: newMid,
      kind,
      consumerId,
      rtpParameters,
      active: true,
    });

    console.warn(
      `[MediaEngine] Reassigned consumer ${consumerId} from rejected mid=${rejectedMid} to mid=${newMid}`
    );
    return newMid;
  }

  /**
   * Build a synthetic SDP answer from the server send-transport params.
   * The browser created a local offer for sendPc but never received an
   * answer, so ICE/DTLS cannot proceed. This method mirrors what
   * mediasoup-client does internally for the send handler.
   */
  private buildSendAnswerSdp(offerSdp: string): string {
    const td = this.sendTransportData!;
    const iceParams = td.iceParameters as any;
    const dtlsParams = td.dtlsParameters as any;
    const iceCandidates = td.iceCandidates as any[];

    // Split offer into lines, separate session header from media sections.
    const allLines = offerSdp.split('\r\n');
    const sessionLines: string[] = [];
    const mediaSections: string[][] = [];
    let cur: string[] | null = null;

    for (const line of allLines) {
      if (line.startsWith('m=')) {
        if (cur) mediaSections.push(cur);
        cur = [line];
      } else if (cur) {
        cur.push(line);
      } else {
        sessionLines.push(line);
      }
    }
    if (cur) mediaSections.push(cur);

    // ── Session header ──
    let sdp = '';
    for (const line of sessionLines) {
      if (
        line.startsWith('v=') ||
        line.startsWith('o=') ||
        line.startsWith('s=') ||
        line.startsWith('t=') ||
        line.startsWith('a=group:BUNDLE') ||
        line.startsWith('a=msid-semantic')
      ) {
        sdp += line + '\r\n';
      }
    }

    if (iceParams.iceLite) {
      sdp += 'a=ice-lite\r\n';
    }

    // ── Media sections ──
    for (const section of mediaSections) {
      // m= line (keep same payload types as the offer)
      sdp += section[0] + '\r\n';
      sdp += 'c=IN IP4 0.0.0.0\r\n';
      sdp += 'a=rtcp:9 IN IP4 0.0.0.0\r\n';

      // Server ICE credentials
      sdp += `a=ice-ufrag:${iceParams.usernameFragment}\r\n`;
      sdp += `a=ice-pwd:${iceParams.password}\r\n`;

      // Server DTLS fingerprints
      for (const fp of dtlsParams.fingerprints || []) {
        sdp += `a=fingerprint:${fp.algorithm} ${fp.value}\r\n`;
      }
      sdp += 'a=setup:passive\r\n'; // Server passive, browser active

      // Copy mid from offer
      for (const line of section) {
        if (line.startsWith('a=mid:')) {
          sdp += line + '\r\n';
          break;
        }
      }

      sdp += 'a=recvonly\r\n'; // Server receives from client
      sdp += 'a=rtcp-mux\r\n';
      sdp += 'a=rtcp-rsize\r\n';

      // Copy codec-related lines from offer (rtpmap, fmtp, rtcp-fb, extmap)
      for (const line of section) {
        if (
          line.startsWith('a=rtpmap:') ||
          line.startsWith('a=fmtp:') ||
          line.startsWith('a=rtcp-fb:') ||
          line.startsWith('a=extmap:') ||
          line.startsWith('a=extmap-allow-mixed')
        ) {
          // Prevent Chrome from spoofing its own TWCC negotiation, which overrides REMB.
          // Mediasoup is not configured for TWCC in media-codecs.ts, so if we accept this,
          // Chrome waits forever for TWCC feedback and forces 0 kbps starvation.
          // Both TWCC-related patterns must be filtered:
          //   - 'transport-cc'       → a=rtcp-fb:N transport-cc
          //   - 'transport-wide-cc'  → a=extmap TWCC URIs (draft-holmer-rmcat-... and transport-wide-cc-02)
          if (line.includes('transport-cc') || line.includes('transport-wide-cc')) {
            continue;
          }
          sdp += line + '\r\n';
        }
      }

      // Server ICE candidates
      for (const cand of iceCandidates) {
        let candLine = `a=candidate:${cand.foundation} 1 ${cand.protocol} ${cand.priority} ${cand.ip} ${cand.port} typ ${cand.type}`;
        if (cand.protocol === 'tcp' && cand.tcpType) {
          candLine += ` tcptype ${cand.tcpType}`;
        }
        sdp += candLine + '\r\n';
      }
      sdp += 'a=end-of-candidates\r\n';
    }

    return sdp;
  }

  // ─────────────────────────────────────────────────────
  // SDP helpers
  // ─────────────────────────────────────────────────────

  private extractDtlsFromSdp(sdp: string): any {
    const fingerprintMatch = sdp.match(/a=fingerprint:(\S+)\s+([0-9A-Fa-f:]+)/);
    const setupMatch = sdp.match(/a=setup:(\S+)/);

    return {
      role: setupMatch?.[1] === 'active' ? 'client' : 'server',
      fingerprints: fingerprintMatch
        ? [
            {
              algorithm: fingerprintMatch[1],
              value: fingerprintMatch[2],
            },
          ]
        : [],
    };
  }

  private static SUPPORTED_AUDIO_CODECS = ['opus'];
  private static SUPPORTED_VIDEO_CODECS = ['vp8', 'h264'];

  private extractRtpParameters(sender: RTCRtpSender): any {
    const params = sender.getParameters();
    const kind = sender.track?.kind as 'audio' | 'video';

    const sdp = this.sendPc?.localDescription?.sdp;
    const codecs = sdp ? this.extractCodecsFromSdp(sdp, kind) : [];
    const sdpHints = sdp ? this.extractMediaEncodingHintsFromSdp(sdp, kind) : {};
    const headerExtensions = sdp ? this.extractHeaderExtensionsFromSdp(sdp, kind) : [];
    const transceiverMid = this.sendPc
      ?.getTransceivers()
      .find((t) => t.sender === sender)?.mid;

    const encodingsFromSender =
      params.encodings?.map((encoding: any) => ({
        ssrc: encoding.ssrc,
        rid: encoding.rid,
        maxBitrate: encoding.maxBitrate,
        maxFramerate: encoding.maxFramerate,
      })) || [];

    const encodings = (encodingsFromSender.length > 0 ? encodingsFromSender : [{}]).map(
      (encoding: any) => {
        const out: any = { ...encoding };
        if (!out.ssrc && !out.rid && sdpHints.ssrc) {
          out.ssrc = sdpHints.ssrc;
        }
        if (kind === 'video' && out.ssrc && sdpHints.rtxSsrc) {
          out.rtx = { ssrc: sdpHints.rtxSsrc };
        }
        return out;
      }
    );

    return {
      mid: sdpHints.mid || transceiverMid || undefined,
      codecs,
      encodings,
      headerExtensions,
      rtcp: { cname: sdpHints.cname || '', reducedSize: true },
    };
  }

  private extractMediaEncodingHintsFromSdp(
    sdp: string,
    kind: 'audio' | 'video'
  ): { mid?: string; ssrc?: number; rtxSsrc?: number; cname?: string } {
    const section = this.getMediaSectionFromSdp(sdp, kind);
    if (!section) return {};

    const midMatch = section.match(/^a=mid:([^\r\n]+)/m);
    const fidMatch = section.match(/^a=ssrc-group:FID\s+(\d+)\s+(\d+)/m);
    const firstSsrcMatch = section.match(/^a=ssrc:(\d+)\s+/m);
    const cnameMatch = section.match(/^a=ssrc:(\d+)\s+cname:([^\r\n]+)/m);

    const primarySsrc = fidMatch
      ? Number(fidMatch[1])
      : firstSsrcMatch
        ? Number(firstSsrcMatch[1])
        : undefined;
    const rtxSsrc = fidMatch ? Number(fidMatch[2]) : undefined;

    return {
      mid: midMatch?.[1]?.trim(),
      ssrc: Number.isFinite(primarySsrc as number) ? primarySsrc : undefined,
      rtxSsrc: Number.isFinite(rtxSsrc as number) ? rtxSsrc : undefined,
      cname: cnameMatch?.[2]?.trim(),
    };
  }

  private getMediaSectionFromSdp(sdp: string, kind: 'audio' | 'video'): string | null {
    // NOTE: Do NOT add the 'm' flag here. With 'm', '$' matches end-of-every-line,
    // causing the lazy [\\s\\S]*? to stop after the very first line of the section,
    // so a=ssrc:, a=extmap: and other per-section attributes are never captured.
    // Without 'm', '$' matches only end-of-string, giving the correct full section.
    const sectionRegex = new RegExp(`(?:^|\\r\\n)(m=${kind}[\\s\\S]*?)(?=\\r\\nm=|$)`);
    const match = sdp.match(sectionRegex);
    return match?.[1] || null;
  }

  private extractHeaderExtensionsFromSdp(sdp: string, kind: 'audio' | 'video'): any[] {
    const section = this.getMediaSectionFromSdp(sdp, kind);
    if (!section) return [];

    const extensions: Array<{
      uri: string;
      id: number;
      encrypt: boolean;
      parameters: Record<string, never>;
    }> = [];

    const extmapRegex = /^a=extmap:(\d+)(?:\/encrypt)?\s+([^\s\r\n]+)/gm;
    let match: RegExpExecArray | null = null;

    while ((match = extmapRegex.exec(section)) !== null) {
      const id = Number(match[1]);
      const uri = String(match[2] || '').trim();
      if (!Number.isFinite(id) || !uri) {
        continue;
      }

      // Only include extensions the router supports. Unknown URIs cause mediasoup
      // to reject the produce() call with "invalid RtpHeaderExtensionUri".
      if (this.routerHeaderExtensionUris.size > 0 && !this.routerHeaderExtensionUris.has(uri)) {
        continue;
      }

      extensions.push({
        uri,
        id,
        encrypt: match[0].includes('/encrypt'),
        parameters: {},
      });
    }

    return extensions;
  }

  private extractCodecsFromSdp(sdp: string, kind: 'audio' | 'video'): any[] {
    const dynamicWhitelist =
      kind === 'audio'
        ? Array.from(this.routerAudioCodecs)
        : Array.from(this.routerVideoCodecs);
    const fallbackWhitelist =
      kind === 'audio'
        ? MediaEngine.SUPPORTED_AUDIO_CODECS
        : MediaEngine.SUPPORTED_VIDEO_CODECS;
    const whitelist = dynamicWhitelist.length > 0 ? dynamicWhitelist : fallbackWhitelist;

    const mLineRegex = new RegExp(`^m=${kind}\\s+\\d+\\s+\\S+\\s+(.+)$`, 'm');
    const mMatch = sdp.match(mLineRegex);
    if (!mMatch) return [];

    const payloadTypes = mMatch[1].trim().split(/\s+/).map(Number);
    const codecs: any[] = [];

    for (const pt of payloadTypes) {
      const rtpMapRegex = new RegExp(
        `^a=rtpmap:${pt}\\s+([^/\\s]+)/(\\d+)(?:/(\\d+))?`,
        'm'
      );
      const rtpMatch = sdp.match(rtpMapRegex);
      if (!rtpMatch) continue;

      const codecName = rtpMatch[1];
      const codecNameLower = codecName.toLowerCase();

      if (!whitelist.some((entry) => entry.toLowerCase() === codecNameLower)) {
        continue;
      }

      if (kind === 'video') {
        if (this.videoCodecPolicy === 'vp8-only' && codecNameLower !== 'vp8') {
          continue;
        }
        if (codecNameLower !== 'vp8' && codecNameLower !== 'h264') {
          continue;
        }
      }

      const fmtpRegex = new RegExp(`^a=fmtp:${pt}\\s+(.+)$`, 'm');
      const fmtpMatch = sdp.match(fmtpRegex);
      const parameters: Record<string, string | number> = {};
      if (fmtpMatch) {
        fmtpMatch[1].split(';').forEach((pair) => {
          const [key, val] = pair.trim().split('=');
          if (key && val !== undefined) {
            parameters[key.trim()] = val.trim();
          }
        });
      }

      if (kind === 'video' && codecNameLower === 'h264') {
        const profileLevelId = String(parameters['profile-level-id'] || '').toLowerCase();
        const isAllowedProfile =
          profileLevelId === '42e01f' || profileLevelId === '42001f';
        if (!isAllowedProfile) {
          continue;
        }

        const routerProfilePrefix = profileLevelId.slice(0, 4);
        if (
          this.routerH264Profiles.size > 0 &&
          routerProfilePrefix &&
          !this.routerH264Profiles.has(routerProfilePrefix)
        ) {
          continue;
        }
      }

      codecs.push({
        mimeType: `${kind}/${codecName}`,
        clockRate: parseInt(rtpMatch[2], 10),
        channels: rtpMatch[3] ? parseInt(rtpMatch[3], 10) : kind === 'audio' ? 2 : undefined,
        payloadType: pt,
        parameters,
      });
    }

    return codecs;
  }

  private buildClientRtpCapabilities(routerRtpCapabilities: any): any {
    const clientCaps = JSON.parse(JSON.stringify(routerRtpCapabilities || {}));
    const routerCodecs: any[] = Array.isArray(clientCaps.codecs) ? clientCaps.codecs : [];

    if (typeof RTCRtpReceiver === 'undefined' || !RTCRtpReceiver.getCapabilities) {
      return clientCaps;
    }

    const browserAudioCodecs = RTCRtpReceiver.getCapabilities('audio')?.codecs || [];
    const browserVideoCodecs = RTCRtpReceiver.getCapabilities('video')?.codecs || [];
    const browserCodecs = [...browserAudioCodecs, ...browserVideoCodecs];
    if (browserCodecs.length === 0) {
      return clientCaps;
    }

    const browserCodecsByMime = new Map<string, RTCRtpCodecCapability[]>();
    for (const codec of browserCodecs) {
      const mimeType = String(codec.mimeType || '').toLowerCase();
      if (!mimeType) continue;
      const existing = browserCodecsByMime.get(mimeType) || [];
      existing.push(codec);
      browserCodecsByMime.set(mimeType, existing);
    }

    const retainedPrimaryPayloadTypes = new Set<number>();
    const primaryFilteredCodecs = routerCodecs.filter((routerCodec) => {
      const mimeType = String(routerCodec?.mimeType || '').toLowerCase();
      if (!mimeType) {
        return false;
      }

      const browserVariants = browserCodecsByMime.get(mimeType) || [];
      if (this.isAuxiliaryCodecMime(mimeType)) {
        if (mimeType === 'video/rtx' || mimeType === 'audio/rtx') {
          return true;
        }
        return browserVariants.length > 0;
      }

      if (browserVariants.length === 0) {
        return false;
      }

      const supported = browserVariants.some((browserCodec) => {
        if (mimeType !== 'video/h264') {
          return true;
        }
        return this.isCompatibleH264Capability(routerCodec, browserCodec);
      });

      if (supported) {
        const payloadType = this.getCodecPayloadTypeFromCapability(routerCodec);
        if (payloadType !== null) {
          retainedPrimaryPayloadTypes.add(payloadType);
        }
      }

      return supported;
    });

    clientCaps.codecs = primaryFilteredCodecs.filter((codec) => {
      const mimeType = String(codec?.mimeType || '').toLowerCase();
      if (mimeType !== 'video/rtx' && mimeType !== 'audio/rtx') {
        return true;
      }

      const apt = Number(codec?.parameters?.apt);
      if (!Number.isFinite(apt)) {
        return false;
      }
      return retainedPrimaryPayloadTypes.has(apt);
    });

    const hasVp8 = clientCaps.codecs.some(
      (codec: any) => String(codec?.mimeType || '').toLowerCase() === 'video/vp8'
    );
    const hasH264 = clientCaps.codecs.some(
      (codec: any) => String(codec?.mimeType || '').toLowerCase() === 'video/h264'
    );

    if (!hasH264 && hasVp8 && this.videoCodecPolicy !== 'vp8-only') {
      console.log('[MediaEngine] H264 unsupported on this client, forcing VP8 fallback');
      this.videoCodecPolicy = 'vp8-only';
    }

    return clientCaps;
  }

  private isAuxiliaryCodecMime(mimeType: string): boolean {
    const normalized = mimeType.toLowerCase();
    return (
      normalized === 'audio/rtx' ||
      normalized === 'video/rtx' ||
      normalized === 'video/ulpfec' ||
      normalized === 'video/red' ||
      normalized === 'video/flexfec-03' ||
      normalized === 'audio/cn' ||
      normalized === 'audio/telephone-event'
    );
  }

  private getCodecPayloadTypeFromCapability(codec: any): number | null {
    const payloadType =
      typeof codec?.preferredPayloadType === 'number'
        ? codec.preferredPayloadType
        : typeof codec?.payloadType === 'number'
          ? codec.payloadType
          : null;

    return Number.isFinite(payloadType) ? payloadType : null;
  }

  private isCompatibleH264Capability(
    routerCodec: any,
    browserCodec: RTCRtpCodecCapability
  ): boolean {
    const routerPacketizationMode = String(
      routerCodec?.parameters?.['packetization-mode'] ?? '0'
    );
    const routerProfileLevelId = String(
      routerCodec?.parameters?.['profile-level-id'] || ''
    ).toLowerCase();

    const browserFmtp = String(browserCodec.sdpFmtpLine || '');
    const browserPacketizationMode = this.extractFmtpParam(browserFmtp, 'packetization-mode') || '0';
    const browserProfileLevelId = this.extractFmtpParam(browserFmtp, 'profile-level-id').toLowerCase();

    if (routerPacketizationMode !== browserPacketizationMode) {
      return false;
    }

    if (!routerProfileLevelId) {
      return true;
    }

    if (!browserProfileLevelId) {
      return false;
    }

    return routerProfileLevelId === browserProfileLevelId;
  }

  private updateRouterCodecWhitelist(routerRtpCapabilities: any): void {
    this.routerAudioCodecs.clear();
    this.routerVideoCodecs.clear();
    this.routerH264Profiles.clear();
    this.routerHeaderExtensionUris.clear();
    for (const ext of routerRtpCapabilities?.headerExtensions || []) {
      if (ext?.uri) this.routerHeaderExtensionUris.add(String(ext.uri));
    }

    for (const codec of routerRtpCapabilities?.codecs || []) {
      const mimeType = String(codec?.mimeType || '');
      const [kind, name] = mimeType.split('/');
      if (!kind || !name) continue;

      const normalizedKind = kind.toLowerCase();
      const normalizedName = name.toLowerCase();

      if (normalizedKind === 'audio') {
        this.routerAudioCodecs.add(normalizedName);
        continue;
      }

      if (normalizedKind === 'video') {
        if (
          normalizedName === 'rtx' ||
          normalizedName === 'ulpfec' ||
          normalizedName === 'red' ||
          normalizedName === 'flexfec-03'
        ) {
          continue;
        }

        // Explicitly exclude H265/HEVC and unknown video codecs from producer mapping.
        if (normalizedName !== 'vp8' && normalizedName !== 'h264') {
          continue;
        }

        this.routerVideoCodecs.add(normalizedName);

        if (normalizedName === 'h264') {
          const plid = String(codec.parameters?.['profile-level-id'] || '').toLowerCase();
          if (plid.length >= 4) {
            this.routerH264Profiles.add(plid.slice(0, 4));
          }
        }
      }
    }
  }

  /**
   * Filter consumer RTP parameters' codecs against the browser's actual
   * receiver capabilities. This prevents building an SDP offer with codecs
   * that setRemoteDescription would reject (NATIVE_SDP_REJECTION).
   *
   * Returns a deep-cloned rtpParameters with only compatible codecs.
   */
  private filterConsumerCodecsAgainstBrowser(
    kind: 'audio' | 'video',
    rtpParameters: any
  ): any {
    const filtered = JSON.parse(JSON.stringify(rtpParameters));
    const codecs: any[] = Array.isArray(filtered.codecs) ? filtered.codecs : [];

    if (codecs.length === 0) return filtered;

    // Get browser receiver capabilities for this media kind.
    const browserCaps =
      typeof RTCRtpReceiver !== 'undefined' && RTCRtpReceiver.getCapabilities
        ? RTCRtpReceiver.getCapabilities(kind)
        : null;

    if (!browserCaps || !browserCaps.codecs || browserCaps.codecs.length === 0) {
      // Cannot determine browser capabilities — pass through unfiltered.
      return filtered;
    }

    const browserCodecs = browserCaps.codecs;

    // Build a set of retained primary payload types so we can prune orphaned RTX.
    const retainedPrimaryPts = new Set<number>();

    const compatibleCodecs = codecs.filter((codec: any) => {
      const mimeType = String(codec.mimeType || '').toLowerCase();

      // RTX codecs are handled separately (pruned if parent codec was removed).
      if (mimeType.endsWith('/rtx')) {
        return true; // Keep temporarily, prune in second pass.
      }

      const isSupported = browserCodecs.some((bc) => {
        const bcMime = String(bc.mimeType || '').toLowerCase();
        if (bcMime !== mimeType) return false;

        // For H.264: require matching packetization-mode AND profile-level-id.
        if (mimeType === 'video/h264') {
          const consumerPM = String(codec.parameters?.['packetization-mode'] ?? '0');
          const consumerPLID = String(
            codec.parameters?.['profile-level-id'] || ''
          ).toLowerCase();

          const bcFmtp = String(bc.sdpFmtpLine || '');
          const bcPM = this.extractFmtpParam(bcFmtp, 'packetization-mode') || '0';
          const bcPLID = this.extractFmtpParam(bcFmtp, 'profile-level-id').toLowerCase();

          if (consumerPM !== bcPM) return false;
          if (consumerPLID && bcPLID && consumerPLID !== bcPLID) return false;
        }

        return true;
      });

      if (isSupported) {
        retainedPrimaryPts.add(codec.payloadType);
      }

      return isSupported;
    });

    // Second pass: prune RTX codecs whose parent primary codec was removed.
    filtered.codecs = compatibleCodecs.filter((codec: any) => {
      const mimeType = String(codec.mimeType || '').toLowerCase();
      if (!mimeType.endsWith('/rtx')) return true;

      const apt = Number(codec.parameters?.apt);
      return Number.isFinite(apt) && retainedPrimaryPts.has(apt);
    });

    return filtered;
  }

  private async failJoin(error: WebRTCError): Promise<Result<MediaStream, WebRTCError>> {
    const leaveResult = await this.leave();
    if (!leaveResult.ok) {
      this.events.onError?.(leaveResult.error);
    }
    this.events.onConnectionStateChange?.('failed');
    return err(error);
  }
}

// ═══════════════════════════════════════════════════════════
// Convenience Export
// ═══════════════════════════════════════════════════════════

export { mungeSdp, forceEncoderBitrate } from './SdpMunger';
export { SignalingClient } from './SignalingClient';
export { BitrateController } from './BitrateController';
export type { QualityMetrics } from './BitrateController';
