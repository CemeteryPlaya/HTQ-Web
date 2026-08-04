# SSH-туннель до корпоративного почтового сервера.
#
# Собственный образ вместо стороннего autossh-образа: содержимое целиком
# видно в репозитории, а зависимость ровно одна — базовая alpine.
#
# autossh держит сессию живой: молча умерший SSH (оборванный NAT, перезагрузка
# почтового сервера) он замечает по пропаже эхо-пакетов на служебных портах и
# пересоздаёт туннель. Голый `ssh -N` в такой ситуации остаётся висеть, и
# backend получал бы "connection refused" до ручного рестарта контейнера.
FROM alpine:3.20

RUN apk add --no-cache openssh-client autossh

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Непривилегированный пользователь: туннелю не нужен root, а ключ читается
# только им.
RUN adduser -D -u 10001 tunnel
USER tunnel

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
