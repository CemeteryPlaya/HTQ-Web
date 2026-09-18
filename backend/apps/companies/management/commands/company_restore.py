"""Вернуть компанию из архива: статус + пересборка сводок холдинга.

Симметрична ``company_archive`` (см. её докстринг за полным разбором
проблемы) — тот же аргумент против правки ``status`` руками через
``CompanyAdmin``: без пересборки холдинга восстановленная компания
осталась бы невидимой в сводках до следующего ``migrate_companies``, хотя
её трафик уже снова обслуживается (``CompanyContextMiddleware`` пускает её
обратно сразу, как только ``status`` вернулся в ``ACTIVE``).

Идемпотентность: повторный вызов на уже действующей компании не падает —
печатает внятное сообщение и завершается успешно.

⚠️ **Адаптация под подпроект 4**: как и ``company_archive``, это временная
мера — обратная сторона той же переключалки видимости, а не часть
полноценного жизненного цикла (банкротство/преемник — см. докстринг
``company_archive``). Подпроект 4 расширяет эту пару команд, а не
переоткрывает вопрос заново.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import ProgrammingError

from apps.companies.models import Company, CompanyStatus
from apps.companies.services import holding_views


class Command(BaseCommand):
    help = "Вернуть компанию из архива и пересобрать сводки холдинга."

    def add_arguments(self, parser):
        parser.add_argument("--company", required=True, dest="company_slug",
                            help="slug компании из реестра.")

    def handle(self, *args, **opts):
        slug = opts["company_slug"]
        company = Company.objects.filter(slug=slug).first()
        if company is None:
            raise CommandError(f"Компания {slug} не найдена.")

        if company.status == CompanyStatus.ACTIVE:
            self.stdout.write(self.style.WARNING(
                f"Компания {slug} уже действует — повторный вызов ничего не меняет."
            ))
            return

        company.status = CompanyStatus.ACTIVE
        company.archived_at = None
        company.save(update_fields=["status", "archived_at", "updated_at"])

        try:
            holding_views.rebuild_holding_views()
        except ProgrammingError as exc:
            raise CommandError(
                f"Компания {slug} возвращена из архива, но пересобрать сводки "
                "холдинга не удалось: состав столбцов разошёлся с другой "
                "компанией, отставшей по миграциям. Представления оставлены "
                "снесёнными: читатель получит громкую ошибку вместо цифр по "
                "полумигрированной группе. Доведите остальные компании — "
                f"`manage.py migrate_companies` без фильтров. Причина: {exc}"
            ) from exc

        self.stdout.write(self.style.SUCCESS(
            f"Компания {slug} возвращена из архива. Сводки холдинга пересобраны."
        ))
