"""Sender-стратегии домена mail — порт ``services/email/app/services/sender/``
(mail-messages-brief.md п.5).

Каждый провайдер (Gmail API / Microsoft Graph / Mailcow SMTP) — свой класс
с общим контрактом ``base.SendResult``/``.send(account, message)``, выбор —
через ``factory.get_sender(provider)``. Единственный живой сетевой вызов на
класс обёрнут в module-level seam-функцию (``_post_send``/
``_send_via_smtp``) — тесты монkeypatch'ят именно её, без реальной сети.

НЕ портируется здесь: фактическая постановка в очередь через dramatiq
(``workers/actors.py::deliver_email``) — эти классы существуют и
тестируются как самостоятельный, готовый к переиспользованию модуль, но
``apps/mail/services/email_service.py::send_email`` (6-й эндпойнт) их пока
НЕ вызывает — актор, который бы их вызвал, сам является под-задачей workers
(Р2 брифа, см. TODO-комментарий в email_service.py::send_email)."""
