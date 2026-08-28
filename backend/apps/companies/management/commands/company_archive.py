"""Перевести компанию в архив: статус + пересборка сводок холдинга.

До этой команды ``status`` был обычным редактируемым полем ``CompanyAdmin`` —
единственным способом заархивировать компанию, — но пересборку холдинга
(``apps.companies.services.holding_views.rebuild_holding_views``) вызывают
ровно три места: ``company_create``, ``migrate_companies``,
``tenancy_bootstrap``. Правки статуса через админку среди них не было.
Итог: оператор архивирует компанию, её трафик мгновенно 404-ится
(``CompanyContextMiddleware`` смотрит на ``is_active`` при каждом запросе —
это срабатывает само, без всякой команды), но строки компании остаются в
сводных ``UNION ALL``-представлениях схемы ``holding`` до следующего
``migrate_companies`` — цифры у директоров холдинга молча включают
архивную компанию. Поэтому теперь ``status`` в ``CompanyAdmin`` только для
чтения (см. ``apps/companies/admin.py``), а единственный путь архивации —
эта команда, которая меняет статус И пересобирает сводки одной операцией.

``active_company_slugs`` в ``apps.companies.interface`` и так фильтрует по
``CompanyStatus.ACTIVE`` — архивная компания выпадает из списка действующих
сама по себе; здесь нужно только дёрнуть ``rebuild_holding_views()``, чтобы
это отразилось на уже существующих представлениях СРАЗУ, а не при
следующем плановом прогоне миграций.

Идемпотентность: повторный вызов на уже архивной компании не падает и не
трогает ``archived_at`` — печатает внятное сообщение и завершается успешно
(тот же принцип, что у ``company_grant``: оператор может звать команду
вслепую из скрипта).

⚠️ **Адаптация под подпроект 4**: это временная мера. Полноценный жизненный
цикл компании — банкротство с передачей дел компании-преемнику
(``Company.successor``, уже объявлено в модели), перенос активов и данных —
решается там. Эта команда только переключает видимость (архив = не участвует
в сводках, трафик 404) и ничего не переносит и не преемствует; подпроект 4
её расширяет, а не переоткрывает.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import ProgrammingError
from django.utils import timezone

from apps.companies.models import Company, CompanyStatus
from apps.companies.services import holding_views


class Command(BaseCommand):
    help = "Перевести компанию в архив и пересобрать сводки холдинга."

    def add_arguments(self, parser):
        parser.add_argument("--company", required=True, dest="company_slug",
                            help="slug компании из реестра.")

    def handle(self, *args, **opts):
        slug = opts["company_slug"]
        company = Company.objects.filter(slug=slug).first()
        if company is None:
            raise CommandError(f"Компания {slug} не найдена.")

        if company.status == CompanyStatus.ARCHIVED:
            self.stdout.write(self.style.WARNING(
                f"Компания {slug} уже в архиве — повторный вызов ничего не меняет."
            ))
            return

        company.status = CompanyStatus.ARCHIVED
        company.archived_at = timezone.now()
        company.save(update_fields=["status", "archived_at", "updated_at"])

        try:
            holding_views.rebuild_holding_views()
        except ProgrammingError as exc:
            # Компания уже архивна — откатывать статус не за что (архивная
            # компания вне сводок и есть желаемое состояние). Падает СБОРКА
            # представлений из-за отставания ДРУГОЙ компании по миграциям —
            # тот же сценарий и тот же дух сообщения, что в migrate_companies
            # и company_create на симметричном месте.
            raise CommandError(
                f"Компания {slug} переведена в архив, но пересобрать сводки "
                "холдинга не удалось: состав столбцов разошёлся с другой "
                "компанией, отставшей по миграциям. Представления оставлены "
                "снесёнными: читатель получит громкую ошибку вместо цифр по "
                "полумигрированной группе. Доведите остальные компании — "
                f"`manage.py migrate_companies` без фильтров. Причина: {exc}"
            ) from exc

        self.stdout.write(self.style.SUCCESS(
            f"Компания {slug} переведена в архив. Сводки холдинга пересобраны."
        ))
