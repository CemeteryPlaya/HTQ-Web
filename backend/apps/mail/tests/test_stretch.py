"""Растяжки mail-core — отложенные куски контракта, которые эта под-задача
намеренно НЕ реализует (решение 4 брифа + Р2), потому что их зависимость ещё
не перенесена. Каждый тест здесь ПАДАЕТ ровно в момент появления
зависимости, заставляя раскрыть отложенную часть — тот же приём, что
apps/hr/tests/test_employees_api.py::test_user_options_endpoints_todo_is_tracked.
"""
import apps.mail.models as mail_models
from apps.mail.services import account_service


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


def test_unread_count_todo_is_tracked():
    """GET /accounts/ отдаёт unread_count=0 всегда (apps/mail/services/
    account_service.py::serialize) — исходник (accounts.py::list_accounts)
    считает его коррелированным подзапросом к EmailMessage (folder=inbox,
    is_read=false). EmailMessage — модель под-задачи messages, ещё не
    перенесена. Как только ``apps.mail.models.EmailMessage`` появится —
    раскройте подсчёт в account_service.list_accounts/serialize и снимите
    эту растяжку."""
    assert not hasattr(mail_models, "EmailMessage"), (
        "В apps.mail.models появился EmailMessage — раскройте реальный "
        "подсчёт unread_count в apps/mail/services/account_service.py "
        "(вместо захардкоженного 0) и снимите эту растяжку"
    )
    # account_service существует и правда хардкодит 0 — если кто-то уже
    # частично раскрыл подсчёт без модели (бага), пусть тест это тоже поймает.
    assert account_service.serialize.__kwdefaults__ == {"unread_count": 0}
