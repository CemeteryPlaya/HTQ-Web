/**
 * Strict media profile for HTQWeb conferencing.
 * Values are centralized to keep client SDP munging and runtime encoder
 * parameters synchronized.
 */

export const VIDEO_TARGET_BITRATE_BPS = 1_000_000;
export const VIDEO_TARGET_BITRATE_KBPS = 1_000;
export const AUDIO_TARGET_BITRATE_BPS = 64_000;
export const TARGET_FPS = 30;

export const VIDEO_MIN_WIDTH = 640;
export const VIDEO_MIN_HEIGHT = 480;
export const VIDEO_TARGET_WIDTH = 1280;
export const VIDEO_TARGET_HEIGHT = 720;
export const VIDEO_MIN_FPS = 15;

// Deprecated: HEVC/H265 is intentionally not negotiated in this project.
// Kept for backward-compatible imports.
export const HEVC_REQUIRED_FMTP: Readonly<Record<string, string | number>> = {};

export const OPUS_REQUIRED_FMTP: Readonly<Record<string, string | number>> = {
  maxaveragebitrate: 192000,
  stereo: 1,
  cbr: 1,
  useinbandfec: 1,
  usedtx: 0,
  'sprop-stereo': 1,
};
