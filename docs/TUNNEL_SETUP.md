# Открыть локальный стенд наружу (проверка конференции с чужой машины)

Задача: дать человеку извне ссылку на **локальный** dev-стек, чтобы он зашёл
в комнату и проверил звук и видео. Одной командой:

```powershell
.\scripts\start-public-test.ps1 -GuestEmail guest@example.com
```

Скрипт напечатает публичную ссылку и данные для входа. Ctrl+C возвращает
стенд в локальное состояние.

## Почему два туннеля, а не один

Cloudflare (как и любой HTTP-туннель) несёт только HTTP и WebSocket. Медиа
WebRTC — это RTP поверх UDP на порт 44444, и через такой туннель он не
пройдёт: проксирование UDP есть только в Cloudflare Spectrum на тарифе
Enterprise. Поэтому сигналинг и медиа разводятся:

```
[браузер гостя] ──https──► Cloudflare Edge ──► localhost:3000 (Vite)
                                                 /api/*    → backend-web
                                                 /ws/sfu/  → sfu:4443
[браузер гостя] ──tcp────► bore.pub ──────────► localhost:44444 (медиа SFU)
```

mediasoup умеет ICE поверх TCP, поэтому медиа уходит в обычный TCP-туннель.
Включается это переменной `TCP_TUNNEL_MODE=true`: она отключает UDP и
поднимает `WebRtcServer` только с TCP listenInfo
([sfu/src/config.ts](../sfu/src/config.ts)). Адрес, который SFU кладёт в
ICE-кандидаты, задаётся парой `WEBRTC_ANNOUNCED_IP` (IP bore.pub — hostname
mediasoup не резолвит) и `WEBRTC_ANNOUNCED_PORT` (внешний порт туннеля,
подменяется в ответе `createTransport`).

## Что делает скрипт

1. Проверяет Docker, контейнер `sfu` и Vite на `:3000`.
2. Докачивает `bore.exe` и `cloudflared.exe` в `%LOCALAPPDATA%\HTQWeb\tools`.
3. Поднимает `bore local 44444 --to bore.pub`, забирает внешний порт и
   резолвит `bore.pub` в IPv4.
4. Пишет в корневой `.env` управляемый блок между маркерами
   `# >>> public-test >>>` … `# <<< public-test <<<`:
   `WEBRTC_ANNOUNCED_IP`, `WEBRTC_ANNOUNCED_PORT`, `TCP_TUNNEL_MODE=true`,
   пустой `CONFERENCE_WT_URL`. С флагом `-WithTurn` добавляет публичный
   OpenRelay TURN.
5. Пересоздаёт `sfu` и `backend-web`.
6. Заводит гостевую учётку (`-GuestEmail`) через `manage.py create_user`.
7. Поднимает `cloudflared tunnel --url http://localhost:3000` и вытаскивает
   выданный `https://<random>.trycloudflare.com`.
8. По Ctrl+C гасит туннели, снимает блок из `.env` и пересоздаёт контейнеры.

## Почему гостю нужна учётка

Комната требует входа дважды: страница `/room/:id` закрыта `requiresAuth`, а
SFU режет WS-upgrade без платформенного JWT. Публичная регистрация создаёт
пользователя в статусе `PENDING`, и войти с ним нельзя, пока админ не
одобрит заявку. Поэтому учётка заводится заранее:

```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec backend-web `
  python manage.py create_user --email guest@example.com --name "Гость"
```

Команда создаёт пользователя сразу в статусе `active` и печатает пароль.

Скрипт зовёт её с `--reset-if-exists`: пароль генерируется и нигде не
сохраняется, поэтому со второго запуска учётка уже есть, а войти в неё
некому. С этим флагом существующей учётке сбрасывается пароль и
возвращается `status=active` — каждый запуск даёт рабочий вход.

## Проверка, что всё поехало

```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml logs sfu | Select-String "announced|TCP_TUNNEL"
```

Ожидается `TCP_TUNNEL_MODE=true → UDP отключён` и `announced as <IP bore.pub>`.

У гостя в `chrome://webrtc-internals` выбранная ICE-пара должна быть **tcp**
и вести на IP bore, а не на `127.0.0.1`. В логах SFU у продюсеров растёт
`keyframes`, у консюмеров — `отправлено`.

## Ограничения и риски

- **Качество.** TCP-only даёт заметную задержку и просадки при потерях
  (head-of-line blocking). Годится для ответа «работает или нет», не для
  оценки качества связи.
- **Публичность.** Туннель открывает наружу весь стенд, включая `/login` и
  `/django-admin/`. На стенде живёт сид-аккаунт `admin/admin12345` — смените
  пароль перед сеансом и гасите туннель сразу после проверки.
- **Комнаты не изолированы.** SFU проверяет подпись токена, но не
  принадлежность к комнате: любой валидный access-токен пускает в любую
  комнату по её ID.
- **Шифрование не страдает.** Медиа идёт DTLS-SRTP между браузером и SFU —
  публичный релей видит только байты.
- **Ссылка одноразовая.** У быстрого туннеля `trycloudflare` адрес меняется
  при каждом запуске. Постоянный адрес требует `cloudflared login` и
  DNS-записи на своём домене.
- **Аватары и файлы.** `S3_PUBLIC_ENDPOINT` указывает на `localhost:9000`,
  поэтому у гостя картинки из MinIO не загрузятся. На конференцию не влияет.

## Альтернатива: проверять на VPS

Если стенд уже развёрнут на сервере с публичным IP, туннели не нужны и
вредны: там достаточно открыть `44444/udp+tcp` в фаерволе и выставить
`WEBRTC_ANNOUNCED_IP=<публичный IP>`. Медиа пойдёт по UDP напрямую — это и
быстрее, и ближе к боевому сценарию.
