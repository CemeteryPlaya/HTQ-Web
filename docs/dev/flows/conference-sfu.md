# Сквозной сценарий: видеоконференция

От открытия комнаты до пошедшего медиа. Единственный сценарий, где браузер
разговаривает **не с Django**, а с отдельными сервисами: `sfu` (mediasoup) и
`webtransport` (мост QUIC).

Смежное: [domains/cms.md](../domains/cms.md) — откуда берётся конфиг;
[infra-ops.md](../infra-ops.md) — как это поднимается.

---

## Общая картина

```mermaid
sequenceDiagram
    participant B as Браузер
    participant N as nginx
    participant D as Django (cms)
    participant WT as webtransport (QUIC)
    participant S as sfu (mediasoup)

    B->>N: GET /api/cms/v1/conference/config
    N->>D: проксирует
    Note over D: базу НЕ читает;<br/>собирает конфиг из настроек
    D-->>B: {sfu url, ice servers, enabled,<br/>wt_signaling_url, wt_certificate_hashes}

    rect rgb(245,250,255)
    Note over B,S: Сигналинг — сначала QUIC, при неудаче WebSocket
    B->>WT: WebTransport + ?token=<access>
    alt QUIC не прошёл
        B->>S: WebSocket, подпротокол ['htqweb.jwt', <access>]
    end
    S->>S: проверить подпись, alg, exp, iss,<br/>token_type == "access"
    alt токен не прошёл
        S-->>B: 401 на upgrade
    end
    end

    rect rgb(255,250,245)
    Note over B,S: Медиа — мимо nginx, напрямую
    B-->>S: RTP/UDP :44444 (или TCP)
    end
```

---

## Шаг 1. Конфигурация

`GET /api/cms/v1/conference/config` — отдаёт домен `cms`
(`backend/apps/cms/services/conference_service.py`).

Ручка **не читает базу**: собирает статическую конфигурацию из настроек
Django. Но одну вещь делает обязательно — **нормализует адрес сигналинга
относительно хоста текущего запроса**. Без этого браузер, пришедший на
публичный адрес, получил бы внутренний адрес контейнера или `localhost`.

В ответе, помимо адресов и ICE-серверов:

- `enabled` — статус сервиса `conference` из реестра `apps.core`, чтобы фронт
  узнавал состояние из того же запроса;
- `wt_signaling_url` и `wt_certificate_hashes` — адрес QUIC-моста и отпечатки
  его самоподписанного сертификата.

Отпечатки нужны потому, что сертификат самоподписанный: браузер принимает его
только через `serverCertificateHashes`.

---

## Шаг 2. Сигналинг: два транспорта

Фронт сначала пробует **WebTransport (QUIC)**, при неудаче сам откатывается на
**WebSocket** — `WebRTCManager.buildSignalingAttempts`
(`frontend/src/lib/webrtc/WebRTCManager.ts:438`).

Токен передаётся по-разному, и это диктуется транспортом:

| Транспорт | Как передаётся токен |
|---|---|
| WebTransport | Параметром строки запроса `?token=<access>` |
| WebSocket | Подпротоколом `['htqweb.jwt', <access>]` |

WebSocket не позволяет ставить произвольные заголовки при upgrade, отсюда
приём с подпротоколом.

### SFU проверяет токен сам

`sfu/src/auth.ts` — **своя** реализация HS256, без npm-библиотеки: HS256 это
HMAC-SHA256 над `header.payload`, остальное — разбор claim'ов.

Проверяется ровно то же, что и в `decode_token` на бэкенде: подпись,
алгоритм, `exp`, `iss` — **плюс** `token_type == "access"`. Refresh-токен в
сигналинг не пускают.

Без валидного токена — **401 на upgrade**. Отключается только для локальной
отладки: `SFU_REQUIRE_AUTH=false`.

Обратите внимание: SFU и Django делят `JWT_SECRET`. Разъедется — сигналинг
перестанет принимать токены, хотя HTTP будет работать.

---

## Шаг 3. Медиа идёт мимо nginx

Браузер соединяется с SFU **напрямую** по UDP (или TCP) на порт `44444`.
Через HTTP-прокси медиа провести нельзя — это RTP, а не HTTP.

### `WEBRTC_ANNOUNCED_IP` обязателен

Адрес, который SFU кладёт в ICE-кандидаты. С wildcard `listenIp` и пустым
`announced` **SFU падает на старте намеренно** — иначе симптомом было бы
чёрное видео без единой ошибки в логах.

| Где | Что ставить |
|---|---|
| Локально, браузер на той же машине | `127.0.0.1` (подставляется в dev) |
| Проверка с другого устройства в сети | LAN-адрес хоста |
| Прод | Публичный IP |

---

## Проверка снаружи: два туннеля

Ни один HTTP-туннель не несёт UDP, поэтому сигналинг и медиа разводятся:

```
гость --https--> Cloudflare ----> localhost:3000 (Vite)
                                    /api/*   -> backend-web
                                    /ws/sfu/ -> sfu:4443
гость --tcp----> bore.pub --------> localhost:44444 (медиа)
```

mediasoup умеет ICE поверх TCP, что и позволяет провести медиа в обычный
TCP-туннель (`TCP_TUNNEL_MODE=true`).

Готовый скрипт — `scripts/start-public-test.ps1`, описание —
[docs/TUNNEL_SETUP.md](../../TUNNEL_SETUP.md).

⚠️ Туннель открывает наружу **весь стенд**, включая `/login` и
`/django-admin/`, где живёт сид-аккаунт `admin` / `admin12345`. Смените
пароль перед сеансом и гасите туннель сразу после.

---

## Что ломается чаще всего

**Забыт `VITE_SFU_WS_TARGET` в тестовом стеке.** Без него Vite шлёт `/ws/sfu`
на дефолтный `127.0.0.1:4443` — то есть **в сам контейнер фронта**, — и
сигналинг молча не находит SFU. Симптом (страница открывается, связь не
устанавливается) на причину не указывает совсем. В обоих
`docker-compose.test-*.yml` переменная задана; при заведении нового стека её
легко забыть.

**Пустой `WEBRTC_ANNOUNCED_IP`.** SFU не стартует — это лучше, чем чёрное
видео.

**Разъехавшийся `JWT_SECRET`.** HTTP работает, сигналинг отдаёт 401.

**Сервис `conference` выключен в реестре.** Гейт по префиксу `/ws/sfu/`.
Проверить и включить: `manage.py service conference --on`.

**WebTransport требует безопасного контекста.** С `http://localhost:3000`
работает, с `http://192.168.x.y:3000` браузер его не даст — нужен HTTPS.
Это не баг платформы; откат на WebSocket предусмотрен именно для таких
случаев.
