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
полноценного жизненного цикла — восстановление снимает и преемника
(``lifecycle.restore_company``). Подпроект 4 расширяет эту пару команд, а не
переоткрывает вопрос заново.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.companies.services import lifecycle


class Command(BaseCommand):
    help = "Вернуть компанию из архива и пересобрать сводки холдинга."

    def add_arguments(self, parser):
        parser.add_argument("--company", required=True, dest="company_slug",
                            help="slug компании из реестра.")

    def handle(self, *args, **opts):
        slug = opts["company_slug"]
        try:
            _company, changed = lifecycle.restore_company(slug)
        except lifecycle.LifecycleError as exc:
            raise CommandError(exc.detail) from exc
        if not changed:
            self.stdout.write(self.style.WARNING(
                f"Компания {slug} уже действует — повторный вызов ничего не меняет."
            ))
            return
        self.stdout.write(self.style.SUCCESS(
            f"Компания {slug} возвращена из архива. Сводки холдинга пересобраны."
        ))
