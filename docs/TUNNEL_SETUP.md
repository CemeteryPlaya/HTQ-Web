# Exposing Mediasoup SFU via Free Tunnels (Cloudflare + Bore)

> **Цель**: Выставить локальный SFU в интернет для P2P-тестирования, **абсолютно бесплатно**, без кредитных карт.  
> Решение: Разделить Signaling и Media. Cloudflare Tunnel маршрутизирует HTTP/WS сигналинг, а утилита Bore маршрутизирует "сырой" TCP (медиа-трафик WebRTC).

---

## Архитектура

```
[Браузер клиента]
       │
       │  WSS (WebSocket/HTTPS)
       ▼
[Cloudflare Edge] ── tunnel (trycloudflare) ──► [localhost:4443] SFU Signaling
       │
       │  TCP (ICE / DTLS / SRTP)
       ▼
  [bore.pub] ── tcp tunnel (bore.exe) ──► [localhost:44444] SFU WebRtcServer
```

---

## Требования

Никаких ручных установок не требуется. Оркестратор сам скачает встроенные компактные бинарники (`cloudflared.exe` и `bore.exe`) в папку `tools/`.

Вам нужен только **Node.js ≥ 20** и **PowerShell**.

---

## Запуск (всё в одном скрипте)

Откройте PowerShell в корне проекта и выполните:

```powershell
.\scripts\start-sfu-tunnel.ps1
```

**Скрипт автоматически:**
1. Скачает туннельные утилиты (если их ещё нет).
2. Запустит Cloudflare Tunnel (HTTP) и сгенерирует публичный URL.
3. Запустит Bore Tunnel (TCP) и сгенерирует публичный IP / Port.
4. Внедрит переменные `WEBRTC_ANNOUNCED_IP`, `WEBRTC_SERVER_PORT`, и включит режим `TCP_TUNNEL_MODE`.
5. Запустит Mediasoup SFU.

**Пример успешного вывода:**

```
[4/5] Injecting SFU environment variables...
   WEBRTC_ANNOUNCED_IP = 144.202.62.247
   WEBRTC_SERVER_PORT  = 38192 (Bore remote port)
   TCP_TUNNEL_MODE     = true (UDP disabled)

[5/5] Starting Mediasoup SFU...
  Clients should connect to:
    WS signaling : https://xxx-xxx.trycloudflare.com/ws/sfu
    ICE media    : 144.202.62.247:38192 (TCP)
```

---

## Настройка Frontend

Скопируйте `Signaling URL` из консоли и обновите ваш фронтенд:

```env
# Вставьте это в .env вашего React/Vite приложения:
VITE_SFU_WSS_URL=wss://xxx-xxx.trycloudflare.com/ws/sfu
```

(Либо передайте это через настройки вашего приложения).

После подключения убедитесь в DevTools, что `iceCandidates` содержат **только** этот объявленный IP и порт с протоколом `tcp`.

---

## Troubleshooting

| Проблема | Решение |
|---|---|
| `Failed to extract Cloudflare URL` | Cloudflare не смог выдать временный адрес. Попробуйте перезапустить скрипт. |
| Клиент не видит видео | Убедитесь, что вы скопировали правильный `wss://` URL во фронтенд и обновили страницу. |
| Ошибка порта: `EADDRINUSE: 44444` | Процесс SFU остался висеть. Найдите его через Диспетчер задач (Node.js) и завершите. |
| `Bore: connection timed out` | Нода bore.pub может быть перегружена. Подождите пару минут или смените ноду, если у вас есть собственный сервер. |
