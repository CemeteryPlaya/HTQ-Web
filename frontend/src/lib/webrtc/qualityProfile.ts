/**
 * Strict media profile for HTQWeb conferencing.
 * Values are centralized to keep client SDP munging and runtime encoder
 * parameters synchronized.
 */

// 5 Мбит/с — потолок, а не расход. Это `maxBitrate` энкодера и `b=AS` в SDP:
// столько отправитель имеет ПРАВО занять, когда картинка того требует
// (движение, мелкий текст на демонстрации экрана). На статичной сцене VP8/H264
// отдадут те же 300–800 кбит/с, что и раньше, — верхняя граница на это не
// влияет.
//
// Держать эту константу в согласии с SFU обязательно: там тот же потолок
// задаётся VIDEO_BITRATE_BPS (sfu/src/config.ts), от него же считаются
// initialAvailableOutgoingBitrate и maxIncomingBitrate (×1.25 = 6.25 Мбит/с).
// Если клиент попросит больше, чем принимает SFU, транспорт молча срежет — и
// разбираться в этом придётся по графикам, а не по коду.
export const VIDEO_TARGET_BITRATE_BPS = 5_000_000;
export const VIDEO_TARGET_BITRATE_KBPS = 5_000;
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
