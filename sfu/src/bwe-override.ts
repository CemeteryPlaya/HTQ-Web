/**
 * BWE (Bandwidth Estimation) Override Module
 *
 * Problem: Google Congestion Control (GCC) in Chrome aggressively reduces
 * bitrate at the slightest RTT fluctuation or packet loss. To maintain
 * 12 Mbps for H.265 1080p@60fps, we send custom RTCP REMB packets that
 * override Chrome's internal BWE estimator.
 *
 * Mechanism:
 * - RTCP Payload-specific feedback (PT=206, FMT=15)
 * - REMB (Receiver Estimated Maximum Bitrate)
 * - Sent every 50ms from SFU → Producer (browser)
 * - Target: 85% of max bitrate (safety headroom)
 *
 * Safety: When packet loss > 3%, estimate drops to 8 Mbps.
 *         When loss recovers < 1.5%, ramps up +1 Mbps per check.
 *
 * ☠️ WARNING: This is a hack that fights Chrome's congestion control.
 *    Use with caution. Always implement the safety degradation logic.
 */

import type { types as mediasoupTypes } from 'mediasoup';
import { config } from './config.js';

// ═══════════════════════════════════════════════════════════
// Constants
// ═══════════════════════════════════════════════════════════

const REMB_FMT = 15;       // REMB uses FMT=15 in RTCP PSFB
const RTCP_PSFB_PT = 206;  // Payload-specific feedback
const REMB_ID = Buffer.from('REMB');

const {
  intervalMs: BWE_INTERVAL_MS,
  safetyFactor: SAFETY_FACTOR,
  plrThreshold: PLR_THRESHOLD,
  degradedBitrateBps: DEGRADED_BPS,
} = config.bwe;

const TARGET_BPS = config.bitrate.videoBps;
const RTCP_APP_PT = 204;
const RTCP_APP_REMOTE_ESTIMATE_SUBTYPE = 13;
const RTCP_APP_NAME = Buffer.from('REST');

// ═══════════════════════════════════════════════════════════
// State per active override session
// ═══════════════════════════════════════════════════════════

export interface BweFeedbackSink {
  sendRtcp(packet: Buffer): Promise<void>;
}

export interface BweOverrideOptions {
  feedbackSink?: BweFeedbackSink;
}

interface BweSession {
  intervalId: NodeJS.Timeout | null;
  currentEstimateBps: number;
  isDegraded: boolean;
  producerSsrc: number;
  senderSsrc: number;
  transport: mediasoupTypes.WebRtcTransport;
  feedbackSink: BweFeedbackSink | null;
}

const sessions = new Map<string, BweSession>();

// ═══════════════════════════════════════════════════════════
// REMB Packet Builder
// ═══════════════════════════════════════════════════════════

/**
 * Build a REMB RTCP packet.
 *
 * Format (draft-alvestrand-rmcat-remb):
 *
 *  0                   1                   2                   3
 *  0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
 * +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
 * |V=2|P| FMT=15  |   PT=206      |          length               |
 * +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
 * |                  SSRC of packet sender                        |
 * +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
 * |                  SSRC of media source (0)                     |
 * +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
 * |  Unique identifier 'R' 'E' 'M' 'B'                           |
 * +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
 * | Num SSRC=1  | BR Exp    |  BR Mantissa (18 bits)              |
 * +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
 * |   SSRC feedback (producer)                                    |
 * +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
 */
export function buildRembPacket(
  senderSsrc: number,
  mediaSsrc: number,
  bitrateBps: number
): Buffer {
  // Encode bitrate: mantissa × 2^exp, mantissa fits in 18 bits
  let exp = 0;
  let mantissa = Math.floor(bitrateBps);
  while (mantissa > 0x3ffff) {
    mantissa >>= 1;
    exp++;
  }
  if (exp > 63) exp = 63; // 6-bit field

  const buf = Buffer.alloc(24);
  let off = 0;

  // Byte 0: V=2, P=0, FMT=15
  buf.writeUInt8((2 << 6) | (REMB_FMT & 0x1f), off++);

  // Byte 1: PT=206
  buf.writeUInt8(RTCP_PSFB_PT, off++);

  // Bytes 2-3: length in 32-bit words minus 1 → (24/4 - 1) = 5
  buf.writeUInt16BE(5, off);
  off += 2;

  // Bytes 4-7: sender SSRC (SFU)
  buf.writeUInt32BE(senderSsrc >>> 0, off);
  off += 4;

  // Bytes 8-11: media source SSRC (unused → 0)
  buf.writeUInt32BE(0, off);
  off += 4;

  // Bytes 12-15: "REMB"
  REMB_ID.copy(buf, off);
  off += 4;

  // Byte 16: num SSRC = 1
  buf.writeUInt8(1, off++);

  // Bytes 17-19: BR exp (6 bits) + BR mantissa (18 bits)
  const brField = ((exp & 0x3f) << 18) | (mantissa & 0x3ffff);
  buf.writeUInt8((brField >> 16) & 0xff, off++);
  buf.writeUInt16BE(brField & 0xffff, off);
  off += 2;

  // Bytes 20-23: target SSRC (producer's media SSRC)
  buf.writeUInt32BE(mediaSsrc >>> 0, off);

  return buf;
}

/**
 * Build RTCP APP feedback packet (PT=204, subtype=13) that carries
 * a compact remote bitrate estimate payload.
 *
 * Payload:
 * - uint32 target bitrate bps
 * - uint32 timestamp seconds
 * - uint32 flags/reserved
 */
export function buildRemoteEstimateAppPacket(
  senderSsrc: number,
  bitrateBps: number,
  flags: number = 0
): Buffer {
  const appPayload = Buffer.alloc(12);
  appPayload.writeUInt32BE(Math.max(0, bitrateBps) >>> 0, 0);
  appPayload.writeUInt32BE(Math.floor(Date.now() / 1000) >>> 0, 4);
  appPayload.writeUInt32BE(flags >>> 0, 8);

  const totalBytes = 4 + 4 + 4 + appPayload.length;
  const packet = Buffer.alloc(totalBytes);
  let offset = 0;

  packet.writeUInt8(
    (2 << 6) | (RTCP_APP_REMOTE_ESTIMATE_SUBTYPE & 0x1f),
    offset++
  );
  packet.writeUInt8(RTCP_APP_PT, offset++);
  packet.writeUInt16BE(totalBytes / 4 - 1, offset);
  offset += 2;

  packet.writeUInt32BE(senderSsrc >>> 0, offset);
  offset += 4;

  RTCP_APP_NAME.copy(packet, offset);
  offset += 4;

  appPayload.copy(packet, offset);
  return packet;
}

// ═══════════════════════════════════════════════════════════
// Session Management
// ═══════════════════════════════════════════════════════════

/**
 * Start periodic REMB injection for a producer.
 *
 * NOTE: Mediasoup v3 does not expose a public sendRtcp() on WebRtcTransport.
 * Two viable approaches:
 *
 * A) Use a DirectTransport pipe to inject raw RTCP.
 * B) Use producer.enableTraceEvent(['bwe']) and react to BWE events,
 *    adjusting Consumer priority/preferred layers instead.
 *
 * Approach B is more idiomatic for Mediasoup and is what we implement here.
 * The REMB packet builder is kept for reference and for raw transport use.
 */
export function startBweOverride(
  transport: mediasoupTypes.WebRtcTransport,
  producerSsrc: number,
  producerId: string,
  options: BweOverrideOptions = {}
): void {
  if (sessions.has(producerId)) {
    console.warn(`[BWE] Override already active for ${producerId}`);
    return;
  }

  const targetBps = Math.floor(TARGET_BPS * SAFETY_FACTOR);
  const senderSsrc = stableHashToUint32(`sfu-${producerId}`);

  const session: BweSession = {
    intervalId: null,
    currentEstimateBps: targetBps,
    isDegraded: false,
    producerSsrc,
    senderSsrc,
    transport,
    feedbackSink: options.feedbackSink ?? null,
  };

  // Default path: periodically push transport cap.
  // Optional path: emit RTCP feedback via injected sink (e.g. DirectTransport).
  session.intervalId = setInterval(async () => {
    try {
      if (session.feedbackSink) {
        const rembPacket = buildRembPacket(
          session.senderSsrc,
          session.producerSsrc,
          session.currentEstimateBps
        );
        const appPacket = buildRemoteEstimateAppPacket(
          session.senderSsrc,
          session.currentEstimateBps
        );

        await session.feedbackSink.sendRtcp(rembPacket);
        await session.feedbackSink.sendRtcp(appPacket);
      }

      // Ensure the transport allows our target bitrate
      await transport.setMaxIncomingBitrate(
        Math.floor(session.currentEstimateBps * 1.15)
      );
    } catch (error) {
      // Transport may have closed, or sink may have been detached.
      console.warn(
        `[BWE] Tick failed for producer=${producerId}:`,
        (error as Error)?.message || error
      );
    }
  }, BWE_INTERVAL_MS);

  sessions.set(producerId, session);

  console.log(
    `[BWE] Override started: producer=${producerId}, ` +
      `SSRC=${producerSsrc}, target=${(targetBps / 1e6).toFixed(1)} Mbps`
  );
}

/**
 * Adjust BWE estimate based on network metrics.
 * Called when RTCP stats indicate changes in network quality.
 */
export function adjustBweEstimate(
  producerId: string,
  packetLossRate: number,
  _roundTripTimeMs: number
): void {
  const s = sessions.get(producerId);
  if (!s) return;

  const targetBps = Math.floor(TARGET_BPS * SAFETY_FACTOR);

  if (packetLossRate > PLR_THRESHOLD) {
    // ── Degrade ──
    s.currentEstimateBps = DEGRADED_BPS;
    s.isDegraded = true;
    console.warn(
      `[BWE] DEGRADED: producer=${producerId}, ` +
        `PLR=${(packetLossRate * 100).toFixed(1)}%, ` +
        `estimate=${(s.currentEstimateBps / 1e6).toFixed(1)} Mbps`
    );
  } else if (s.isDegraded && packetLossRate < PLR_THRESHOLD * 0.5) {
    // ── Recover: ramp +1 Mbps per check ──
    s.currentEstimateBps = Math.min(
      s.currentEstimateBps + 1_000_000,
      targetBps
    );
    if (s.currentEstimateBps >= targetBps) {
      s.isDegraded = false;
    }
    console.log(
      `[BWE] RECOVERING: producer=${producerId}, ` +
        `estimate=${(s.currentEstimateBps / 1e6).toFixed(1)} Mbps`
    );
  }
}

/**
 * Stop BWE override for a producer.
 */
export function stopBweOverride(producerId: string): void {
  const s = sessions.get(producerId);
  if (!s) return;

  if (s.intervalId) clearInterval(s.intervalId);
  sessions.delete(producerId);
  console.log(`[BWE] Stopped: producer=${producerId}`);
}

/**
 * Stop all active sessions. Call on server shutdown.
 */
export function stopAllBweOverrides(): void {
  for (const [id] of sessions) {
    stopBweOverride(id);
  }
}

function stableHashToUint32(text: string): number {
  let hash = 2166136261;
  for (let i = 0; i < text.length; i++) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}
