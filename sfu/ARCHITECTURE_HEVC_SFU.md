# HTQWeb SFU (HEVC) — Roadmap и рефакторинг

## 1) Целевой профиль качества (Strict)

- Видео: `H.265/HEVC`, `profile-id=1`, `level-id=120`, `1080p@60`, цель `12_000_000 bps`.
- Аудио: `Opus 48kHz stereo`, `maxaveragebitrate=192000`, `stereo=1`, `cbr=1`, `useinbandfec=1`.
- Сигнализация: `WebSocket` с приоритетом `wss://`, бинарный формат через `Protobuf` (в этом репозитории сейчас действует JSON-совместимый слой и proto-схема для миграции).
- Безопасность: TLS 1.3 для сигнализации, DTLS-SRTP для медиа.

## 2) Roadmap разработки

### Фаза A. Базовый core SFU
1. Поднять `mediasoup`-воркеры и room lifecycle.
2. Зафиксировать `Router` codec capabilities под HEVC/Opus.
3. Принудить bitrate-профиль на уровне `rtpParameters.encodings`.

### Фаза B. Клиентский media profile
1. Вынести единый quality profile (константы bitrate/FPS/разрешение).
2. Включить SDP munging до `setLocalDescription`.
3. Проверять поддержку HEVC на старте (`RTCRtpSender.getCapabilities`).
4. Периодически переустанавливать `RTCRtpSender.setParameters`.

### Фаза C. Congestion Control override
1. Включить BWE override loop каждые `50ms`.
2. Генерировать RTCP feedback пакеты:
   - REMB (`PT=206/FMT=15`).
   - APP RemoteEstimate (`PT=204/subtype=13`).
3. Подключить fallback на `transport.setMaxIncomingBitrate`.
4. Ввести деградацию при PLR и плавное восстановление.

### Фаза D. Мультиплексирование потоков
1. AudioLevelObserver для active speaker.
2. Отправка `1080p` только top `1..3` активным спикерам.
3. Остальные video-consumers ставить на pause/thumbnail режим.

### Фаза E. Prod readiness
1. Региональная геораскладка SFU (Алматы/локальные DC Tier III).
2. SLO: RTT p95 < 30ms для РК-регионов.
3. Нагрузочные прогоны: 50/100/300 участников, failover и chaos.

## 3) Схема маршрутизации RTP

```text
Publisher Browser
  Camera/Mic -> RTP (HEVC/Opus)
  DTLS handshake -> SRTP media
         |
         v
     WebRtcTransport (Ingress, SFU)
         |
         +--> Producer(video/audio)
                |
                +--> AudioLevelObserver (active speaker ranking)
                |
                +--> BWE Override Loop
                      |- RTCP REMB
                      |- RTCP APP subtype=13 (RemoteEstimate)
                      |- setMaxIncomingBitrate fallback
                |
                +--> Consumer fan-out (selected peers only)
                         |
                         v
                    WebRtcTransport (Egress)
                         |
                         v
                    Subscriber Browser (SRTP -> decode -> render)
```

## 4) Примеры кода (в проекте)

### 4.1 RouterCapabilities/MediaEngine для HEVC

Файл: `sfu/src/media-codecs.ts`

```ts
{
  kind: 'video',
  mimeType: 'video/H265',
  clockRate: 90000,
  parameters: {
    'profile-id': 1,
    'level-id': 120,
  },
}
```

### 4.2 SDP munging (192 kbps audio + 12 Mbps video)

Файл: `frontend/src/lib/webrtc/SdpMunger.ts`

```ts
let munged = sdp;
munged = mungeOpusParams(munged);     // maxaveragebitrate=192000; stereo=1; cbr=1; useinbandfec=1
munged = preferH265Codec(munged);     // H.265 payload в приоритете
munged = forceH265Params(munged);     // profile-id=1; level-id=120
munged = forceVideoBitrate(munged);   // b=AS:12000 + b=TIAS:12000000
```

### 4.3 Генерация RTCP для удержания битрейта

Файл: `sfu/src/bwe-override.ts`

```ts
const rembPacket = buildRembPacket(senderSsrc, producerSsrc, estimateBps);
const appPacket = buildRemoteEstimateAppPacket(senderSsrc, estimateBps);

await feedbackSink.sendRtcp(rembPacket);
await feedbackSink.sendRtcp(appPacket);
await transport.setMaxIncomingBitrate(Math.floor(estimateBps * 1.15));
```

## 5) Что уже включено в этом рефакторинге

- Централизованный профиль качества клиента (`frontend/src/lib/webrtc/qualityProfile.ts`).
- Усиленный SDP munger + runtime bitrate enforcement.
- Проверка HEVC-поддержки до входа в конференцию.
- Канал `qualityReport` клиент -> SFU для RTT/PLR.
- Привязка quality report к серверному BWE adjustment.
- BWE-модуль с RTCP APP subtype=13 builder и strategy-style sink.
- Room-уровень active speaker observer для новых audio producers.

## 6) Важный operational note

Полная wire-миграция на бинарный Protobuf уже подготовлена схемой `sfu/src/protobuf/signaling.proto`, но в текущем runtime этого репозитория signalling-слой оставлен JSON-совместимым для обратной совместимости клиента. Следующий шаг — включить единый Protobuf codec на обеих сторонах (frontend + sfu) без dual-stack.
