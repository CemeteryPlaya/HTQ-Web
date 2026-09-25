"""Перевести компанию в архив: статус + пересборка сводок холдинга.

До этой команды ``status`` был обычным редактируемым полем ``CompanyAdmin`` —
единственным способом заархивировать компанию, — но пересборку холдинга
(``apps.companies.services.holding_views.rebuild_holding_views``) вызывают
ровно три места: ``company_create``, ``migrate_companies``,
``tenancy_bootstrap``. Правки статуса через админку среди них не было.
Итог: оператор архивирует компанию, её режим мгновенно переключается на
«только чтение» — читает суперпользователь, запись закрыта всем
(``htqweb/tenancy/archive.py``, спека
``docs/plans/2026-09-25-archive-read-only-spec.md``; ``CompanyContextMiddleware``
смотрит на статус компании при каждом запросе — это срабатывает само, без
всякой команды), но строки компании остаются в
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

Банкротство с преемником — отдельная команда ``company_bankrupt``
(``lifecycle.bankrupt_company``): переносит членства и тоже заканчивается
архивом; эта команда только архивирует.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.companies.services import lifecycle


class Command(BaseCommand):
    help = "Перевести компанию в архив и пересобрать сводки холдинга."

    def add_arguments(self, parser):
        parser.add_argument("--company", required=True, dest="company_slug",
                            help="slug компании из реестра.")

    def handle(self, *args, **opts):
        slug = opts["company_slug"]
        try:
            _company, changed = lifecycle.archive_company(slug)
        except lifecycle.LifecycleError as exc:
            raise CommandError(exc.detail) from exc
        if not changed:
            self.stdout.write(self.style.WARNING(
                f"Компания {slug} уже в архиве — повторный вызов ничего не меняет."
            ))
            return
        self.stdout.write(self.style.SUCCESS(
            f"Компания {slug} переведена в архив. Сводки холдинга пересобраны."
        ))
