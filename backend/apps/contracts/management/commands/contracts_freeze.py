"""Заморозить раздел «Договоры» компании после переноса в БЗО (A6.2, D-S6-4).

    manage.py contracts_freeze --company <slug> [--comment "..."] [--actor <user_id>]
    manage.py contracts_freeze --company <slug> --undo [--comment "..."]

Шаг ранбука выкатки ПОСЛЕ проверок переноса (``bpp_migrate_contracts``):
морозит человек, когда ФД сверил сальдо, а не сама команда переноса.
После заморозки запись под ``/api/contracts/`` компании — 403
``contracts_frozen``, чтение и карточки «перенесён в …» остаются.

Идущие согласования документов раздела заморозку не пускают (команда
печатает список и завершается с ошибкой); ``--revoke-pending`` отзывает их
(документы возвращаются в черновик) и замораживает одной транзакцией.

Идемпотентна: повтор не сдвигает дату первой заморозки; ``--undo`` на
незамороженном разделе ничего не делает.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.companies import interface as companies
from apps.contracts.services import freeze
from htqweb.tenancy.db import use_company


class Command(BaseCommand):
    help = "Заморозить (или разморозить --undo) раздел «Договоры» компании."

    def add_arguments(self, parser):
        parser.add_argument("--company", required=True, help="slug компании")
        parser.add_argument("--undo", action="store_true",
                            help="снять заморозку — запись снова открыта")
        parser.add_argument("--comment", default="",
                            help="основание (уходит в GET contracts/v1/freeze)")
        parser.add_argument("--revoke-pending", action="store_true",
                            help="отозвать идущие согласования документов раздела "
                                 "(документы - в черновик) и заморозить")
        parser.add_argument("--actor", type=int, default=None,
                            help="user_id того, кто морозит (для журнала)")

    def handle(self, *args, company, undo, comment, actor, revoke_pending=False,
               **options):
        # Опечатка в слаге без этой проверки ушла бы в search_path
        # «co_<опечатка>, public» и тихо заморозила бы public.
        if companies.get_company(company) is None:
            raise CommandError(f"Компании «{company}» нет в реестре.")
        if not companies.schema_exists(company):
            raise CommandError(f"У компании «{company}» нет схемы — сначала migrate_companies.")

        with use_company(company):
            if undo:
                changed = freeze.unfreeze(actor_id=actor, comment=comment)
                self.stdout.write(f"{company}: заморозка снята" if changed
                                  else f"{company}: раздел и не был заморожен")
                return
            try:
                changed = freeze.freeze(actor_id=actor, comment=comment,
                                        revoke_pending=revoke_pending)
            except freeze.PendingApprovals as exc:
                lines = [f"  {d['subject_type']} #{d['id']}: {d['title']}"
                         for d in exc.documents]
                raise CommandError(
                    f"У «{company}» идут согласования документов раздела "
                    f"({len(exc.documents)}) - заморозка не выполнена:\n"
                    + "\n".join(lines) + "\n"
                    "Дождитесь решений или отзовите их: --revoke-pending.")
            state = freeze.info()
        when = f"{timezone.localtime(state['frozen_at']):%d.%m.%Y %H:%M}"
        self.stdout.write(f"{company}: раздел «Договоры» заморожен ({when})" if changed
                          else f"{company}: уже заморожен с {when} — ничего не изменено")
