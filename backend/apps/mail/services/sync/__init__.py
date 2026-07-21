"""Sync-мапперы домена mail — порт ``services/email/app/services/sync/``.

Область mail-messages-brief.md п.6: переносятся ЧИСТЫЕ функции — маппинг
провайдерских ответов (gmail/microsoft/mailcow) в параметры ``EmailMessage``/
``EmailAttachment`` (``mapper.py``) и парсинг сырых payload'ов (``gmail.py``::
``_ingest_message_payload``, ``microsoft.py``::``_ingest``,
``mailcow_imap.py``::``_parse_eml``) — БЕЗ живых HTTP/IMAP-вызовов. Живые
sync-драйверы (``initial_backfill``/``incremental``/``register_push`` —
httpx-опросы Gmail/Graph API, IMAP-подключение через ``aioimaplib``) — под-
задача workers (Celery-периодика в этом Django-порту, см. CLAUDE.md); их тело
здесь НЕ портируется (Р2 брифа).

``ensure_fresh_token`` (в ``gmail.py``/``microsoft.py``) — единственная часть
исходных sync-модулей, которая ДЕЛАЕТ сетевой вызов (refresh token у
провайдера, только если он истёк) — переносится синхронно (``httpx.Client``,
как и ``apps/mail/services/oauth_clients.py``), используется и здесь
(не портируется), и в ``apps/mail/services/sender/{gmail,graph}.py`` (реюз
токена для отправки — тот же путь, что и в исходнике: ``sender/gmail.py``
импортирует ``_ensure_fresh_token`` из ``sync/gmail.py``)."""
