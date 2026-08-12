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
    // Голосовой профиль: моно + VBR, 64 кбит/с. Раньше здесь стоял
    // «студийный» набор (192 кбит/с, stereo, CBR), из-за которого Opus делил
    // бюджет на два канала при том же реальном потолке отправителя.
    // Разбор — в frontend/src/lib/webrtc/qualityProfile.ts; значения должны
    // совпадать с клиентскими, иначе роутер объявляет одно, а клиент шлёт
    // другое. `channels: 2` остаётся: это формат RTP-полезной нагрузки opus,
    // он всегда /48000/2, моно задаётся именно параметром stereo=0.
    parameters: {
      maxaveragebitrate: 64000,
      stereo: 0,
      cbr: 0,
      useinbandfec: 1,
      usedtx: 0,
      'sprop-stereo': 0,
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
