#!/bin/sh
# Поднять SSH-туннель до корпоративного почтового сервера и держать его живым.
#
# Пробрасываются два порта: IMAP (чтение почты) и SMTP submission (отправка).
# Слушаем на 0.0.0.0, потому что клиент — соседний контейнер (backend-*), а не
# процесс внутри этого. Наружу хоста порты НЕ публикуются (см. docker-compose:
# у сервиса нет секции ports) — туннель доступен только внутри сети compose.
set -eu

: "${MAIL_TUNNEL_SSH_HOST:?MAIL_TUNNEL_SSH_HOST is required}"
: "${MAIL_TUNNEL_SSH_USER:?MAIL_TUNNEL_SSH_USER is required}"

SSH_PORT="${MAIL_TUNNEL_SSH_PORT:-22}"
KEY="${MAIL_TUNNEL_SSH_KEY:-/ssh/id_ed25519}"

# Адреса, как их видит САМ почтовый сервер (обычно он же и есть, отсюда
# 127.0.0.1). Если ssh-хост — отдельная шлюзовая машина, укажите внутренний
# адрес почтового сервера.
REMOTE_IMAP_HOST="${MAIL_TUNNEL_REMOTE_IMAP_HOST:-127.0.0.1}"
REMOTE_IMAP_PORT="${MAIL_TUNNEL_REMOTE_IMAP_PORT:-993}"
REMOTE_SMTP_HOST="${MAIL_TUNNEL_REMOTE_SMTP_HOST:-$REMOTE_IMAP_HOST}"
REMOTE_SMTP_PORT="${MAIL_TUNNEL_REMOTE_SMTP_PORT:-587}"

LOCAL_IMAP_PORT="${MAIL_TUNNEL_LOCAL_IMAP_PORT:-1143}"
LOCAL_SMTP_PORT="${MAIL_TUNNEL_LOCAL_SMTP_PORT:-1587}"

if [ ! -r "$KEY" ]; then
    echo "mail-tunnel: приватный ключ $KEY недоступен для чтения." >&2
    echo "  Положите его в infra/mail-tunnel/ssh/ и убедитесь, что он читается uid 10001." >&2
    exit 1
fi

# Проверка ключа хоста включена намеренно: туннель несёт почтовые пароли, а
# StrictHostKeyChecking=no открыл бы дорогу man-in-the-middle. Заполните
# infra/mail-tunnel/ssh/known_hosts:
#   ssh-keyscan -p <порт> <хост> > infra/mail-tunnel/ssh/known_hosts
KNOWN_HOSTS="${MAIL_TUNNEL_KNOWN_HOSTS:-/ssh/known_hosts}"
if [ ! -r "$KNOWN_HOSTS" ]; then
    echo "mail-tunnel: нет $KNOWN_HOSTS — соберите его командой" >&2
    echo "  ssh-keyscan -p $SSH_PORT $MAIL_TUNNEL_SSH_HOST > infra/mail-tunnel/ssh/known_hosts" >&2
    exit 1
fi

echo "mail-tunnel: ${MAIL_TUNNEL_SSH_USER}@${MAIL_TUNNEL_SSH_HOST}:${SSH_PORT}"
echo "  IMAP  0.0.0.0:${LOCAL_IMAP_PORT} → ${REMOTE_IMAP_HOST}:${REMOTE_IMAP_PORT}"
echo "  SMTP  0.0.0.0:${LOCAL_SMTP_PORT} → ${REMOTE_SMTP_HOST}:${REMOTE_SMTP_PORT}"

# AUTOSSH_GATETIME=0 — считать успешной даже сессию, упавшую сразу: иначе при
# недоступном сервере autossh сдаётся после первой же попытки и контейнер
# уходит в рестарт-луп вместо тихого ожидания.
export AUTOSSH_GATETIME=0
export AUTOSSH_PORT=0          # heartbeat через ServerAliveInterval, без доп. порта

exec autossh -M 0 -N \
    -o "ExitOnForwardFailure=yes" \
    -o "ServerAliveInterval=30" \
    -o "ServerAliveCountMax=3" \
    -o "StrictHostKeyChecking=yes" \
    -o "UserKnownHostsFile=${KNOWN_HOSTS}" \
    -o "IdentitiesOnly=yes" \
    -i "$KEY" \
    -p "$SSH_PORT" \
    -L "0.0.0.0:${LOCAL_IMAP_PORT}:${REMOTE_IMAP_HOST}:${REMOTE_IMAP_PORT}" \
    -L "0.0.0.0:${LOCAL_SMTP_PORT}:${REMOTE_SMTP_HOST}:${REMOTE_SMTP_PORT}" \
    "${MAIL_TUNNEL_SSH_USER}@${MAIL_TUNNEL_SSH_HOST}"
