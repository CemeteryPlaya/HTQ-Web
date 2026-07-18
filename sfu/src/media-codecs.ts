/**
 * Медиа-кодеки Mediasoup — толерантный набор профилей для кроссплатформенности.
 *
 * Это центральный реестр кодеков, используемый при создании Mediasoup Router'ов.
 * Каждая комната получает собственный Router с этими возможностями.
 */

import type { types as mediasoupTypes } from 'mediasoup';

export const mediaCodecs: mediasoupTypes.RtpCodecCapability[] = [
  {
    kind: 'audio',
    mimeType: 'audio/opus',
    preferredPayloadType: 111,
    clockRate: 48000,
    channels: 2,
    parameters: {
      maxaveragebitrate: 192000,
      stereo: 1,
      cbr: 1,
      useinbandfec: 1,
      usedtx: 0,
      'sprop-stereo': 1,
      minptime: 10,
      maxptime: 40,
    },
    rtcpFeedback: [
      { type: 'nack' },
    ],
  },

  // Основной резервный кодек для десктопных/мобильных браузеров.
  {
    kind: 'video',
    mimeType: 'video/VP8',
    preferredPayloadType: 96,
    clockRate: 90000,
    parameters: {},
    rtcpFeedback: [
      { type: 'nack' },
      { type: 'nack', parameter: 'pli' },
      { type: 'ccm', parameter: 'fir' },
      { type: 'goog-remb' },
    ],
  },

  // H264 Constrained Baseline профиль (предпочтительное стабильное пересечение).
  {
    kind: 'video',
    mimeType: 'video/H264',
    preferredPayloadType: 102,
    clockRate: 90000,
    parameters: {
      'packetization-mode': '1',
      'profile-level-id': '42e01f',
      'level-asymmetry-allowed': '1',
    },
    rtcpFeedback: [
      { type: 'nack' },
      { type: 'nack', parameter: 'pli' },
      { type: 'ccm', parameter: 'fir' },
      { type: 'goog-remb' },
    ],
  },

  // Список кодеков намеренно строгий:
  // - только H264 Constrained Baseline (42e01f)
  // - без H264 Main/High профилей
  // - без H265/HEVC
];
