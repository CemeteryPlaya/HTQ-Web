"""Растяжки mail-core — отложенные куски контракта, которые эта под-задача
намеренно НЕ реализует (решение 4 брифа + Р2), потому что их зависимость ещё
не перенесена. Каждый тест здесь ПАДАЕТ ровно в момент появления
зависимости, заставляя раскрыть отложенную часть — тот же приём, что
apps/hr/tests/test_employees_api.py::test_user_options_endpoints_todo_is_tracked.

``test_unread_count_todo_is_tracked`` (растяжка на ``EmailMessage``) снята
под-задачей mail-messages: ``apps.mail.models.EmailMessage`` перенесена,
``apps/mail/services/account_service.py::list_accounts`` теперь считает
реальный unread_count (см. test_accounts_api.py и test_messages_api.py) —
растяжка выполнила свою роль сторожа и больше не нужна.
"""
import apps.mail.models as mail_models


def test_mailbox_id_fk_todo_is_tracked():
    """EmailAccount.mailbox_id — голый int БЕЗ FK (решение 4 брифа mail-core):
    исходник ссылается на ``email.provisioned_mailboxes.id``
    (``ProvisionedMailbox``), модель которой создаётся под-задачей mailboxes,
    ещё не перенесена (вне зоны mail-core). Как только
    ``apps.mail.models.ProvisionedMailbox`` появится — замените
    ``EmailAccount.mailbox_id`` на настоящий ``ForeignKey`` (см. докстринг
    ``EmailAccount`` в apps/mail/models.py) и снимите эту растяжку."""
    assert not hasattr(mail_models, "ProvisionedMailbox"), (
        "В apps.mail.models появился ProvisionedMailbox — замените "
        "EmailAccount.mailbox_id (голый IntegerField) на настоящий FK "
        "(решение 4 брифа mail-core, см. apps/mail/models.py) и снимите "
        "эту растяжку"
    )
