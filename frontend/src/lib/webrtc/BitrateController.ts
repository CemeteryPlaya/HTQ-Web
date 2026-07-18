/**
 * Bitrate Controller — Runtime monitoring and enforcement of target bitrates
 *
 * Periodically reads RTCStatsReport and re-applies target bitrates via
 * RTCRtpSender.setParameters() to fight Chrome's automatic adjustments.
 * Also collects metrics for QualityReport messages to the SFU.
 *
 * Safety features:
 * - ICE connection state gating: never enforces when transport is not connected.
 * - Zero-bitrate backoff: delegates to GCC instead of slamming max bitrate
 *   into a dead/congested link.
 * - Exponential backoff probing when link recovers from starvation.
 */


import {
  AUDIO_TARGET_BITRATE_BPS,
  VIDEO_TARGET_BITRATE_BPS,
} from './qualityProfile';

export interface QualityMetrics {
  rttMs: number;
  packetLossRate: number;
  jitterMs: number;
  currentVideoBitrateBps: number;
  currentAudioBitrateBps: number;
  effectiveTargetVideoBitrateBps: number;
  nominalTargetVideoBitrateBps: number;
  starvationMode: boolean;
  codec: string;
  width: number;
  height: number;
  fps: number;
}

export type MetricsCallback = (metrics: QualityMetrics) => void;

/** ICE states where enforcement must be suppressed. */
const ICE_BLOCK_STATES: ReadonlySet<string> = new Set([
  'new',
  'checking',
  'disconnected',
  'failed',
  'closed',
]);

/** Minimum bitrate floor during slow probing after starvation (250 kbps). */
const PROBE_FLOOR_BPS = 250_000;

/** How many consecutive zero-throughput samples trigger starvation mode. */
const STARVATION_SAMPLE_THRESHOLD = 6;

/** Max backoff multiplier for exponential probing (caps at target). */
const MAX_BACKOFF_STEPS = 8;

/** Grace window after start where zero-throughput is ignored (encoder warm-up). */
const STARTUP_STARVATION_GRACE_MS = 10_000;

export class BitrateController {
  private pc: RTCPeerConnection;
  private monitorIntervalId: ReturnType<typeof setInterval> | null = null;
  private enforceIntervalId: ReturnType<typeof setInterval> | null = null;
  private metricsCallback: MetricsCallback | null = null;

  // Targets
  private readonly nominalTargetVideoBps: number;
  private readonly nominalTargetAudioBps: number;
  private currentTargetVideoBps: number;

  // Tracking previous stats for delta calculation
  private prevBytesSent: Map<string, number> = new Map();
  private prevTimestamp: Map<string, number> = new Map();

  // Enforcement interval (re-apply setParameters every N seconds)
  private enforceIntervalMs = 5000;
  private monitorIntervalMs = 2000;

  // ── Starvation / backoff state ──
  private consecutiveZeroSamples = 0;
  private inStarvationMode = false;
  private backoffStep = 0;
  private probeFloorBps = PROBE_FLOOR_BPS;
  private lastBlockedIceState: string | null = null;
  private startedAtMs = 0;
  private hasSeenPositiveVideoSample = false;

  private boundHandleIceStateChange: () => void;

  constructor(
    pc: RTCPeerConnection,
    targetVideoBps: number = VIDEO_TARGET_BITRATE_BPS,
    targetAudioBps: number = AUDIO_TARGET_BITRATE_BPS
  ) {
    this.pc = pc;
    this.nominalTargetVideoBps = targetVideoBps;
    this.nominalTargetAudioBps = targetAudioBps;
    this.currentTargetVideoBps = targetVideoBps;

    this.boundHandleIceStateChange = this.handleIceStateChange.bind(this);
  }

  private handleIceStateChange(): void {
    const state = this.pc.iceConnectionState;
    if (state === 'failed' || state === 'closed') {
      console.warn(`[BitrateCtrl] ICE state is ${state}, automatically stopping controller intervals.`);
      this.stop();
    }
  }

  /**
   * Start periodic monitoring and enforcement.
   */
  start(metricsCallback?: MetricsCallback): void {
    this.stop();
    this.metricsCallback = metricsCallback ?? null;

    // Reset starvation state on fresh start.
    this.consecutiveZeroSamples = 0;
    this.inStarvationMode = false;
    this.backoffStep = 0;
    this.probeFloorBps = PROBE_FLOOR_BPS;
    this.lastBlockedIceState = null;
    this.currentTargetVideoBps = this.nominalTargetVideoBps;
    this.startedAtMs = Date.now();
    this.hasSeenPositiveVideoSample = false;

    this.pc.removeEventListener('iceconnectionstatechange', this.boundHandleIceStateChange);
    this.pc.addEventListener('iceconnectionstatechange', this.boundHandleIceStateChange);

    // Monitor stats every 2 seconds
    this.monitorIntervalId = setInterval(() => {
      void this.collectMetrics();
    }, this.monitorIntervalMs);

    // Re-enforce sender parameters periodically to resist BWE throttling.
    this.enforceIntervalId = setInterval(() => {
      void this.enforceBitrate();
    }, this.enforceIntervalMs);

    // Also enforce bitrate immediately (only if transport is ready).
    void this.enforceBitrate();

    console.log(
      `[BitrateCtrl] Started: video=${(this.nominalTargetVideoBps / 1e6).toFixed(1)} Mbps, ` +
        `audio=${(this.nominalTargetAudioBps / 1000).toFixed(0)} kbps`
    );
  }

  /**
   * Stop monitoring.
   */
  stop(): void {
    if (this.monitorIntervalId) {
      clearInterval(this.monitorIntervalId);
      this.monitorIntervalId = null;
    }

    if (this.enforceIntervalId) {
      clearInterval(this.enforceIntervalId);
      this.enforceIntervalId = null;
    }

    this.pc.removeEventListener('iceconnectionstatechange', this.boundHandleIceStateChange);
  }

  /**
   * Check if the ICE transport is in a state where we can safely
   * manipulate encoder parameters.
   */
  private isTransportReady(): boolean {
    const iceState = this.pc.iceConnectionState;
    return !ICE_BLOCK_STATES.has(iceState);
  }

  /**
   * Force re-apply target bitrates via setParameters().
   * Gated by transport readiness to avoid flooding a dead link.
   */
  async enforceBitrate(): Promise<void> {
    if (!this.isTransportReady()) {
      return;
    }

    try {
      const senders = this.pc.getSenders();
      for (const sender of senders) {
        // Enforce bitrate only for video senders.
        if (sender.track?.kind !== 'video') {
          continue;
        }

        const parameters = sender.getParameters();
        if (!parameters.encodings) {
          parameters.encodings = [{}];
        }

        let changed = false;
        for (const encoding of parameters.encodings) {
          if (encoding.maxBitrate !== this.currentTargetVideoBps) {
            encoding.maxBitrate = this.currentTargetVideoBps;
            changed = true;
          }
        }

        if (changed) {
          await sender.setParameters(parameters);
        }
      }
    } catch (err) {
      console.warn('[BitrateCtrl] Failed to enforce bitrate:', err);
    }
  }

  /**
   * Handle zero-throughput detection: enter starvation mode and
   * delegate to GCC by dropping to a floor bitrate.
   */
  private enterStarvationMode(floorBps: number = PROBE_FLOOR_BPS): void {
    if (this.inStarvationMode) return;

    this.inStarvationMode = true;
    this.backoffStep = 0;
    this.probeFloorBps = Math.max(PROBE_FLOOR_BPS, floorBps);
    this.currentTargetVideoBps = this.probeFloorBps;

    console.warn(
      `[BitrateCtrl] Zero throughput detected — entering starvation mode. ` +
        `Target reduced to ${(this.probeFloorBps / 1000).toFixed(0)} kbps (exponential backoff probing)`
    );
  }

  /**
   * Exponential backoff probing: gradually increase target bitrate
   * when data starts flowing again after starvation.
   *
   * Each step doubles the target: 50k → 100k → 200k → 400k → … → nominal.
   */
  private probeHigher(): void {
    if (!this.inStarvationMode) return;

    this.backoffStep = Math.min(this.backoffStep + 1, MAX_BACKOFF_STEPS);
    const probeBps = Math.min(
      this.probeFloorBps * Math.pow(2, this.backoffStep),
      this.nominalTargetVideoBps
    );

    this.currentTargetVideoBps = probeBps;

    if (probeBps >= this.nominalTargetVideoBps) {
      // Fully recovered → exit starvation mode.
      this.inStarvationMode = false;
      this.backoffStep = 0;
      this.consecutiveZeroSamples = 0;
      console.log(
        `[BitrateCtrl] Recovered from starvation — nominal bitrate restored: ` +
          `${(this.nominalTargetVideoBps / 1e6).toFixed(1)} Mbps`
      );
    } else {
      console.log(
        `[BitrateCtrl] Probing: step=${this.backoffStep} target=${(probeBps / 1000).toFixed(0)} kbps`
      );
    }
  }

  /**
   * Collect WebRTC stats and compute quality metrics.
   */
  private async collectMetrics(): Promise<void> {
    // ── Hard gate: never collect or enforce on dead/failing connections ──
    // If the ICE transport is in new/checking/disconnected/failed/closed,
    // getStats() may return stale data that triggers false-positive re-enforcement.
    // The enforceBitrate path already checks isTransportReady(), but we must
    // also prevent the collection+analysis phase from running at all.
    if (!this.isTransportReady()) {
      const iceState = this.pc.iceConnectionState;
      if (this.lastBlockedIceState !== iceState) {
        console.warn(
          `[BitrateCtrl] ICE state '${iceState}'. Bitrate management paused until transport is connected.`
        );
        this.lastBlockedIceState = iceState;
      }
      return;
    }
    this.lastBlockedIceState = null;

    let stats: RTCStatsReport;
    try {
      stats = await this.pc.getStats();
    } catch {
      return;
    }

    const metrics: QualityMetrics = {
      rttMs: 0,
      packetLossRate: 0,
      jitterMs: 0,
      currentVideoBitrateBps: 0,
      currentAudioBitrateBps: 0,
      effectiveTargetVideoBitrateBps: this.currentTargetVideoBps,
      nominalTargetVideoBitrateBps: this.nominalTargetVideoBps,
      starvationMode: this.inStarvationMode,
      codec: 'unknown',
      width: 0,
      height: 0,
      fps: 0,
    };

    let hasVideoSample = false;
    let videoBytesDelta = 0;
    const codecById = new Map<string, string>();

    stats.forEach((report) => {
      const item = report as RTCStats & { mimeType?: string };
      if (item.type === 'codec' && typeof item.mimeType === 'string') {
        codecById.set(item.id, item.mimeType);
      }
    });

    stats.forEach((report) => {
      const item = report as RTCStats & Record<string, any>;

      // Outbound RTP (what we're sending)
      if (item.type === 'outbound-rtp') {
        const id = item.id;
        const bytesSent = item.bytesSent ?? 0;
        const timestamp = item.timestamp ?? 0;

        const prevBytes = this.prevBytesSent.get(id) ?? 0;
        const prevTs = this.prevTimestamp.get(id) ?? timestamp;
        const deltaMs = timestamp - prevTs;

        if (deltaMs > 0) {
          const bitrate = ((bytesSent - prevBytes) * 8 * 1000) / deltaMs;

          if (item.kind === 'video') {
            hasVideoSample = true;
            videoBytesDelta += (bytesSent - prevBytes);
            metrics.currentVideoBitrateBps = Math.round(
              Math.max(metrics.currentVideoBitrateBps, bitrate)
            );
            metrics.width = Math.max(metrics.width, item.frameWidth ?? 0);
            metrics.height = Math.max(metrics.height, item.frameHeight ?? 0);
            metrics.fps = Math.max(metrics.fps, item.framesPerSecond ?? 0);

            if (item.codecId && codecById.has(item.codecId)) {
              const fullMime = codecById.get(item.codecId) || '';
              metrics.codec = fullMime.includes('/')
                ? fullMime.split('/')[1]
                : fullMime;
            }
          } else if (item.kind === 'audio') {
            metrics.currentAudioBitrateBps = Math.round(
              Math.max(metrics.currentAudioBitrateBps, bitrate)
            );
          }
        }

        this.prevBytesSent.set(id, bytesSent);
        this.prevTimestamp.set(id, timestamp);
      }

      // Candidate pair (RTT)
      if (item.type === 'candidate-pair') {
        const isSelected =
          item.nominated === true ||
          item.selected === true ||
          item.state === 'succeeded';
        if (isSelected && typeof item.currentRoundTripTime === 'number') {
          metrics.rttMs = Math.round(item.currentRoundTripTime * 1000);
        }
      }

      // Remote inbound (packet loss, jitter)
      if (item.type === 'remote-inbound-rtp') {
        if (typeof item.fractionLost === 'number') {
          // Some implementations expose 0..1, others use RTCP-style 0..255.
          const normalizedLoss =
            item.fractionLost > 1 ? item.fractionLost / 256 : item.fractionLost;
          metrics.packetLossRate = Math.max(
            metrics.packetLossRate,
            Math.min(Math.max(normalizedLoss, 0), 1)
          );
        }

        if (typeof item.jitter === 'number') {
          metrics.jitterMs = Math.max(
            metrics.jitterMs,
            Math.round(item.jitter * 1000)
          );
        }
      }
    });

    const hasActiveVideoSender = this.hasLiveEnabledVideoSender();
    const startupInGraceWindow =
      Date.now() - this.startedAtMs < STARTUP_STARVATION_GRACE_MS;

    // ── Starvation / recovery logic ──
    if (hasVideoSample && hasActiveVideoSender && this.isTransportReady()) {
      const hasPositiveVideoSample =
        metrics.currentVideoBitrateBps > 0 || videoBytesDelta > 0;

      if (hasPositiveVideoSample) {
        this.hasSeenPositiveVideoSample = true;
      }

      // Avoid false starvation right after join while encoder/BWE warms up.
      if (startupInGraceWindow && !this.hasSeenPositiveVideoSample) {
        this.consecutiveZeroSamples = 0;
      } else {
      if (videoBytesDelta <= 0) {
        // No bytes flowing despite transport being "connected".
        this.consecutiveZeroSamples++;

        if (this.consecutiveZeroSamples >= STARVATION_SAMPLE_THRESHOLD) {
          this.enterStarvationMode();
        }
      } else {
        // Data is flowing.
        this.consecutiveZeroSamples = 0;

        if (this.inStarvationMode) {
          // Gradually ramp back up via exponential probing.
          this.probeHigher();
          await this.enforceBitrate();
        } else {
          // Normal mode: re-enforce if bitrate dropped below 80% of current target.
          // Skip this check for low-fps/static scenes — low bitrate can be normal there.
          const isLikelyStaticScene = metrics.fps > 0 && metrics.fps < 5;
          if (
            !isLikelyStaticScene &&
            metrics.currentVideoBitrateBps > 0 &&
            metrics.currentVideoBitrateBps < this.currentTargetVideoBps * 0.8
          ) {
            console.warn(
              `[BitrateCtrl] Bitrate at ` +
                `${(metrics.currentVideoBitrateBps / 1e6).toFixed(1)} Mbps, ` +
              `re-enforcing ${(this.currentTargetVideoBps / 1e6).toFixed(1)} Mbps`
            );
            await this.enforceBitrate();
          }
        }
      }
      }
    } else if (!hasActiveVideoSender) {
      // No live enabled video track to send: keep controller in nominal state
      // without raising starvation warnings.
      this.consecutiveZeroSamples = 0;
      this.inStarvationMode = false;
      this.backoffStep = 0;
      this.currentTargetVideoBps = this.nominalTargetVideoBps;
    }

    metrics.effectiveTargetVideoBitrateBps = this.currentTargetVideoBps;
    metrics.nominalTargetVideoBitrateBps = this.nominalTargetVideoBps;
    metrics.starvationMode = this.inStarvationMode;

    // Report metrics
    if (this.metricsCallback) {
      this.metricsCallback(metrics);
    }
  }

  private hasLiveEnabledVideoSender(): boolean {
    return this.pc.getSenders().some((sender) => {
      const track = sender.track;
      return (
        !!track &&
        track.kind === 'video' &&
        track.readyState === 'live' &&
        track.enabled
      );
    });
  }
}
