/**
 * WebRTC Module — Barrel Export
 *
 * Usage:
 *   import { MediaEngine, type QualityMetrics } from '@/lib/webrtc';
 *
 *   const engine = new MediaEngine({
 *     signalingUrl: 'wss://sfu.example.com:4443',
 *     roomId: 'meeting-123',
 *     displayName: 'Alice',
 *   }, {
 *     onRemoteStream: (stream) => { ... },
 *     onActiveSpeakers: (speakers) => { ... },
 *     onQualityMetrics: (metrics) => { ... },
 *   });
 *
 *   const localStream = await engine.join();
 *   // ... later
 *   await engine.leave();
 */

export { MediaEngine } from './MediaEngine';
export type {
  ConferenceOptions,
  RemoteStream,
  MediaEngineEvents,
  VideoCodecPolicy,
} from './MediaEngine';

export { SignalingClient } from './SignalingClient';
export { WebRTCManager } from './WebRTCManager';
export type { WebRTCManagerEvents, WebRTCManagerOptions } from './WebRTCManager';
export type { Result } from './result';
export type { WebRTCError, WebRTCErrorCode } from './WebRTCError';

export {
  assertHevcSupport,
  mungeSdp,
  mungeOpusParams,
  preferStableVideoCodecs,
  preferH265Codec,
  forceH265Params,
  forceVideoBitrate,
  forceEncoderBitrate,
} from './SdpMunger';

export { BitrateController } from './BitrateController';
export type { QualityMetrics, MetricsCallback } from './BitrateController';

export {
  AUDIO_TARGET_BITRATE_BPS,
  HEVC_REQUIRED_FMTP,
  OPUS_REQUIRED_FMTP,
  TARGET_FPS,
  VIDEO_MIN_FPS,
  VIDEO_MIN_HEIGHT,
  VIDEO_MIN_WIDTH,
  VIDEO_TARGET_BITRATE_BPS,
  VIDEO_TARGET_BITRATE_KBPS,
  VIDEO_TARGET_HEIGHT,
  VIDEO_TARGET_WIDTH,
} from './qualityProfile';
