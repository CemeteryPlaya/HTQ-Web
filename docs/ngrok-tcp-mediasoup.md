# TCP-only SFU через ngrok (Mediasoup)

Этот режим нужен, когда SFU работает локально за NAT и медиатрафик WebRTC
должен идти только через `ngrok tcp`.

## 1) Запуск ngrok TCP tunnel

Быстрый запуск:

```bash
ngrok tcp 44444
```

Через конфиг:

```bash
cd d:\HTQWeb1\sfu
ngrok start sfu-media --config .\ngrok.tcp.yml
```

Файл конфига: `sfu/ngrok.tcp.yml`.

## 2) Запуск SFU через wrapper

```bash
cd d:\HTQWeb1\sfu
npm run start:ngrok-tcp
```

Wrapper (`sfu/scripts/start-mediasoup-ngrok-tcp.mjs`) делает:

1. Ожидает tunnel в `http://127.0.0.1:4040/api/tunnels`.
2. Берет `public_url` формата `tcp://X.tcp.ngrok.io:PORT`.
3. Резолвит `X.tcp.ngrok.io` в IPv4.
4. Стартует SFU с env:
   - `WEBRTC_ENABLE_UDP=false`
   - `WEBRTC_ENABLE_TCP=true`
   - `WEBRTC_PREFER_TCP=true`
   - `WEBRTC_EXPOSE_INTERNAL_IP=false`
   - `NGROK_PUBLIC_IP=<resolved-ip>`
   - `NGROK_PUBLIC_PORT=<external-port>`
5. По умолчанию запускает `npm run start` (не `dev`), чтобы избежать проблем
   `tsx/esbuild spawn EPERM` в ограниченных Windows-средах.

Примечание: даже если SFU запущен обычным `npm run dev`, сервер теперь
пытается авто-обнаружить ngrok endpoint из `http://127.0.0.1:4040/api/tunnels`
и переписать ICE-кандидат. Wrapper всё равно рекомендуется как основной способ.

## 3) Что делает сервер Mediasoup

В `sfu/src/server.ts`:

1. `createWorkers()` собирает `listenInfos` только из разрешенных протоколов.
2. В `listenInfos` прокидывается `exposeInternalIp` из `WEBRTC_EXPOSE_INTERNAL_IP`.
3. На `createTransport` ICE-кандидаты переписываются функцией
   `rewriteIceCandidatesForNgrok()` в один TCP candidate с внешним ngrok
   `IP:port`.

Итог: клиенту не отправляются локальные `192.168.x.x` кандидаты в tunnel-режиме.

Если нужен прямой transport без `webRtcServer`, TCP-only snippet:

```ts
const transport = await router.createWebRtcTransport({
  listenInfos: [
    {
      protocol: 'tcp',
      ip: '0.0.0.0',
      announcedAddress: process.env.NGROK_PUBLIC_IP,
      exposeInternalIp: false,
      port: Number(process.env.WEBRTC_SERVER_PORT || 44444),
    },
  ],
  enableUdp: false,
  enableTcp: true,
  preferTcp: true,
});
```

## 4) Порядок запуска процессов

1. Терминал A: `ngrok tcp 44444` (или `ngrok start ...`).
2. Терминал B: `npm run start:ngrok-tcp` в `d:\HTQWeb1\sfu`.
3. Затем backend/frontend как обычно.

## 5) Проверка

1. Проверить ngrok API:

```bash
curl http://127.0.0.1:4040/api/tunnels
```

Ожидается `public_url: tcp://...`.

2. Проверить логи SFU:
   - UDP выключен, TCP включен.
   - Показан resolved ngrok IP.

3. Проверить signaling `createTransport`:
   - В ответе один TCP ICE candidate.
   - `ip/address` равен ngrok resolved IP.
   - `port` равен ngrok external port.

## 6) LiveKit reference

Пример конфига TCP-only: `docs/livekit.tcp-only.ngrok.reference.yml`.

Запуск:

```bash
livekit-server --config ./livekit.tcp-only.ngrok.reference.yml --node-ip 203.0.113.10
```

Ограничение: при динамическом `ngrok tcp` внешний порт меняется. Без сигнального
rewrite или статического ngrok TCP address candidate-port может расходиться с
реальным внешним портом tunnel.
