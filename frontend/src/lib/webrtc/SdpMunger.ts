/**
 * SDP Munger — safety profile:
 * - Strictly keep only VP8 + stable H264 baseline profiles (42e01f, 42001f) in m=video.
 * - Explicitly avoid HEVC/H265 and non-baseline H264 profiles.
 * - Audio: Opus 192 kbps stereo CBR + FEC.
 */

import {
  AUDIO_TARGET_BITRATE_BPS,
  OPUS_REQUIRED_FMTP,
  TARGET_FPS,
  VIDEO_TARGET_BITRATE_BPS,
  VIDEO_TARGET_BITRATE_KBPS,
} from './qualityProfile';

type FmtpParams = Record<string, string | number>;

const OPUS_RTPMAP = /a=rtpmap:(\d+)\s+opus\/48000\/2/gi;

export function assertHevcSupport(): void {
  // Legacy function retained for backward compatibility.
  // We intentionally do not require HEVC support anymore.
}

export function mungeOpusParams(sdp: string): string {
  const opusPts = findPayloadTypes(sdp, OPUS_RTPMAP);
  if (opusPts.length === 0) return sdp;

  let result = sdp;
  for (const pt of opusPts) {
    result = upsertFmtpParams(result, pt, OPUS_REQUIRED_FMTP, {
      minptime: 10,
    });
  }
  return result;
}

export function preferStableVideoCodecs(sdp: string): string {
  // Enforce stable, cross-browser video codec set.
  const lines = sdp.split('\r\n');

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (!line.startsWith('m=video')) continue;

    const parts = line.trim().split(/\s+/);
    const header = parts.slice(0, 3);
    const payloadTypes = parts.slice(3);
    const preferredPayloads: string[] = [];

    for (const pt of payloadTypes) {
      const rtpmap = lines.find((entry) =>
        new RegExp(`^a=rtpmap:${pt}\\s+`, 'i').test(entry)
      );
      if (!rtpmap) continue;

      if (/^a=rtpmap:\d+\s+VP8\//i.test(rtpmap)) {
        preferredPayloads.push(pt);
        continue;
      }

      if (/^a=rtpmap:\d+\s+H264\//i.test(rtpmap)) {
        const fmtp = lines.find((entry) =>
          new RegExp(`^a=fmtp:${pt}\\s+`, 'i').test(entry)
        );
        const profileLevelId = extractFmtpParam(fmtp || '', 'profile-level-id').toLowerCase();
        if (profileLevelId === '42e01f' || profileLevelId === '42001f') {
          preferredPayloads.push(pt);
        }
      }
    }

    if (preferredPayloads.length > 0) {
      lines[i] = [...header, ...preferredPayloads].join(' ');
    }
  }

  return lines.join('\r\n');
}

export function preferH265Codec(sdp: string): string {
  // Deprecated API name. HEVC is not preferred anymore.
  return preferStableVideoCodecs(sdp);
}

export function forceH265Params(sdp: string): string {
  // Legacy API retained. HEVC coercion is intentionally disabled.
  return sdp;
}

export function forceVideoBitrate(
  sdp: string,
  bitrateKbps: number = VIDEO_TARGET_BITRATE_KBPS
): string {
  const lines = sdp.split('\r\n');
  const result: string[] = [];

  let inVideoSection = false;
  let insertedBandwidth = false;

  for (const line of lines) {
    if (line.startsWith('m=video')) {
      inVideoSection = true;
      insertedBandwidth = false;
      result.push(line);
      continue;
    }

    if (line.startsWith('m=')) {
      if (inVideoSection && !insertedBandwidth) {
        result.push(`b=AS:${bitrateKbps}`);
        result.push(`b=TIAS:${bitrateKbps * 1000}`);
      }
      inVideoSection = false;
      insertedBandwidth = false;
      result.push(line);
      continue;
    }

    if (
      inVideoSection &&
      (line.startsWith('b=AS:') || line.startsWith('b=TIAS:'))
    ) {
      continue;
    }

    if (inVideoSection && !insertedBandwidth && line.startsWith('c=')) {
      result.push(line);
      result.push(`b=AS:${bitrateKbps}`);
      result.push(`b=TIAS:${bitrateKbps * 1000}`);
      insertedBandwidth = true;
      continue;
    }

    result.push(line);
  }

  if (inVideoSection && !insertedBandwidth) {
    result.push(`b=AS:${bitrateKbps}`);
    result.push(`b=TIAS:${bitrateKbps * 1000}`);
  }

  return result.join('\r\n');
}

/**
 * Strip deprecated a=ssrc:SSRC msid:... lines.
 * In Unified Plan, stream/track identity is expressed via media-level a=msid.
 * Chrome 110+ rejects the legacy ssrc-level msid attribute during
 * setLocalDescription after codec filtering changes the SDP structure.
 */
function stripSsrcMsid(sdp: string): string {
  return sdp
    .split('\r\n')
    .filter((line) => !/^a=ssrc:\d+\s+msid:/i.test(line))
    .join('\r\n');
}

export function mungeSdp(sdp: string): string {
  let munged = sdp;
  munged = mungeOpusParams(munged);
  munged = preferStableVideoCodecs(munged);
  munged = forceH265Params(munged);
  munged = forceVideoBitrate(munged, VIDEO_TARGET_BITRATE_KBPS);
  munged = stripSsrcMsid(munged);
  return munged;
}

export async function forceEncoderBitrate(
  pc: RTCPeerConnection,
  targetVideoBitrate: number = VIDEO_TARGET_BITRATE_BPS,
  targetAudioBitrate: number = AUDIO_TARGET_BITRATE_BPS
): Promise<void> {
  if (pc.connectionState === 'closed') {
    return;
  }

  for (const sender of pc.getSenders()) {
    if (!sender.track || sender.track.readyState !== 'live') continue;

    const params = sender.getParameters();
    const senderCodecs = Array.isArray((params as any).codecs) ? (params as any).codecs : [];
    if (senderCodecs.length === 0) {
      continue;
    }

    if (!params.encodings || params.encodings.length === 0) {
      params.encodings = [{}];
    }

    if (sender.track.kind === 'video') {
      for (const encoding of params.encodings) {
        encoding.maxBitrate = targetVideoBitrate;
        encoding.maxFramerate = TARGET_FPS;
        if (typeof encoding.scaleResolutionDownBy !== 'number') {
          encoding.scaleResolutionDownBy = 1;
        }
      }

      const withPreference = params as RTCRtpSendParameters & {
        degradationPreference?: RTCDegradationPreference;
      };
      // Prefer balanced adaptation so browser can lower resolution first
      // instead of collapsing to very low FPS on constrained links.
      withPreference.degradationPreference = 'balanced';
    }

    if (sender.track.kind === 'audio') {
      for (const encoding of params.encodings) {
        encoding.maxBitrate = targetAudioBitrate;
      }
    }

    try {
      await sender.setParameters(params);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error ?? '');
      const isKnownTransient =
        /InvalidStateError/i.test(message) ||
        /getParameters\(\) has never been called/i.test(message);

      if (!isKnownTransient) {
        console.warn('[SdpMunger] setParameters failed for sender:', error);
      }
    }
  }
}

function findPayloadTypes(sdp: string, regexTemplate: RegExp): string[] {
  const flags = regexTemplate.flags.includes('g')
    ? regexTemplate.flags
    : `${regexTemplate.flags}g`;
  const regex = new RegExp(regexTemplate.source, flags);
  const payloadTypes = new Set<string>();

  let match: RegExpExecArray | null = null;
  while ((match = regex.exec(sdp)) !== null) {
    payloadTypes.add(match[1]);
  }

  return Array.from(payloadTypes);
}

function upsertFmtpParams(
  sdp: string,
  payloadType: string,
  requiredParams: FmtpParams,
  prependParams: FmtpParams = {}
): string {
  const lines = sdp.split('\r\n');
  const fmtpRegex = new RegExp(`^a=fmtp:${payloadType}\\s+(.+)$`, 'i');
  const rtpmapRegex = new RegExp(`^a=rtpmap:${payloadType}\\s+`, 'i');

  let fmtpLineIndex = -1;
  let rtpmapLineIndex = -1;

  for (let i = 0; i < lines.length; i++) {
    if (fmtpLineIndex < 0 && fmtpRegex.test(lines[i])) {
      fmtpLineIndex = i;
    }
    if (rtpmapLineIndex < 0 && rtpmapRegex.test(lines[i])) {
      rtpmapLineIndex = i;
    }
  }

  if (fmtpLineIndex >= 0) {
    const existingRaw = lines[fmtpLineIndex].replace(fmtpRegex, '$1');
    const existing = parseFmtpParams(existingRaw);
    const merged = { ...prependParams, ...existing, ...requiredParams };
    lines[fmtpLineIndex] = `a=fmtp:${payloadType} ${serializeFmtpParams(merged)}`;
  } else if (rtpmapLineIndex >= 0) {
    const merged = { ...prependParams, ...requiredParams };
    lines.splice(
      rtpmapLineIndex + 1,
      0,
      `a=fmtp:${payloadType} ${serializeFmtpParams(merged)}`
    );
  }

  return lines.join('\r\n');
}

function parseFmtpParams(paramStr: string): Record<string, string> {
  const result: Record<string, string> = {};
  for (const chunk of paramStr.split(';')) {
    const [key, ...valueParts] = chunk.trim().split('=');
    if (!key || valueParts.length === 0) continue;
    result[key.trim()] = valueParts.join('=').trim();
  }
  return result;
}

function serializeFmtpParams(params: FmtpParams): string {
  return Object.entries(params)
    .map(([key, value]) => `${key}=${value}`)
    .join(';');
}

function extractFmtpParam(fmtpLine: string, key: string): string {
  const chunks = fmtpLine.split(';').map((entry) => entry.trim());
  for (const chunk of chunks) {
    const [k, v] = chunk.split('=').map((entry) => entry.trim());
    if (k?.toLowerCase() === key.toLowerCase() && v) {
      return v;
    }
  }
  return '';
}
