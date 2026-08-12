/**
 * Strict media profile for HTQWeb conferencing.
 * Values are centralized to keep client SDP munging and runtime encoder
 * parameters synchronized.
 */

// 1.5 Мбит/с, а не 1.0: SFU и так провижнен именно под столько
// (VIDEO_BITRATE_BPS=1_500_000, maxIncomingBitrate=1.875 Мбит/с в
// sfu/src/config.ts), то есть клиент резал сам себя ниже разрешённого
// потолка. 720p30 на 1 Мбит/с выглядит мягко на любом кодеке — лишние
// 500 кбит/с не стоят ничего ни SFU, ни сети, а разница видна.
export const VIDEO_TARGET_BITRATE_BPS = 1_500_000;
export const VIDEO_TARGET_BITRATE_KBPS = 1_500;
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

// Профиль голоса, а не музыки — отсюда и все отличия от «студийного» набора,
// который тут стоял раньше (192 кбит/с, stereo, CBR):
//
//   • stereo=0 — речь моно. В стерео Opus делит бюджет на два канала, то есть
//     при том же потолке каждый получает вдвое меньше. Для одного говорящего
//     это платить качеством за канал, в котором нет никакой информации.
//   • cbr=0 — VBR даёт заметно лучшее качество на бит: на паузах и тихих
//     местах Opus тратит меньше, а на сложных участках речи — больше.
//     CBR нужен, когда важна ровная полоса, а не звук.
//   • maxaveragebitrate=64000 — согласовано с AUDIO_TARGET_BITRATE_BPS.
//     Раньше SDP объявлял 192 кбит/с, а SdpMunger тут же ставил senderу
//     maxBitrate=64000 — объявленное число было фикцией. Для моно-речи
//     64 кбит/с Opus — это уже с запасом.
//   • useinbandfec=1 — оставляем: восстановление потерянных пакетов слышно
//     сразу, особенно на мобильной сети.
//   • usedtx=0 — оставляем: DTX глушит паузы и подменяет их комфортным шумом,
//     что как раз даёт эффект «дыхания» и обрубленных первых слогов.
export const OPUS_REQUIRED_FMTP: Readonly<Record<string, string | number>> = {
  maxaveragebitrate: 64000,
  stereo: 0,
  cbr: 0,
  useinbandfec: 1,
  usedtx: 0,
  'sprop-stereo': 0,
};
