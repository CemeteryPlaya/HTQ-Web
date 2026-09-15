"""Локальный стенд группы: четыре компании документа 10.09.2026 одной командой.

Заводит компании (строка реестра + схема + миграции + сводки холдинга —
``lifecycle.provision_company``, идемпотентно), в каждой сеет утверждённую
оргструктуру (``seed_hr_demo --company``), заводит учётки
(``seed_employee_accounts --company``), выдаёт членства своим сотрудникам и
обслуживающим должностям холдинга (``serving_holders`` — блок C, членство
остаётся явным решением, здесь оно принимается за оператора стенда), и
наполняет задачи строительной компании (``seed_tasks_demo --company``).

Сиды соседних аппок вызываются через ``call_command`` — это композиция
CLI, как в shell-скрипте, а не обход правила «сосед только через
interface»: команда не импортирует ни моделей, ни сервисов hr/users/tasks,
а членства и реестр — её собственные сервисы.

ТОЛЬКО ДЛЯ ЛОКАЛЬНОЙ БАЗЫ (``_assert_local``): на бою в режиме перехода
одна компания, остальные заводятся отдельным шагом выкатки (roadmap §7).
Не атомарна как целое: заведение схем — DDL сотен таблиц вне транзакции;
каждый сид атомарен сам по себе.

Slug холдинга ``hi-tech-group`` — предварительный: какое юрлицо является
управляющей компанией, руководство не ответило (roadmap §8.1).
"""

from __future__ import annotations

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from apps.access.interface import serving_holders
from apps.companies.models import Company, CompanyStatus
from apps.companies.services import lifecycle, membership_service
from apps.hr.interface import list_employees_brief
from htqweb.tenancy.db import use_company

# (slug, имя, вид, slug родителя). Порядок — родитель раньше детей.
GROUP = (
    ("hi-tech-group", "Hi-Tech Group LTD", "holding", None),
    ("hi-tech-qazaqstan", "Hi-Tech Qazaqstan", "construction", "hi-tech-group"),
    ("hi-tech-systems", "Hi-Tech Systems", "it", "hi-tech-group"),
    ("kazakhstan-engineering-group", "Kazakhstan Engineering Group", "service", "hi-tech-group"),
)
TASKS_COMPANY = "hi-tech-qazaqstan"


def _own_staff_user_ids(slug: str) -> list[int]:
    """user_id сотрудников компании — из её схемы, через interface hr."""
    with use_company(slug):
        return [e["user_id"] for e in list_employees_brief() if e["user_id"]]


class Command(BaseCommand):
    help = ("Локальный стенд группы: четыре компании, их оргструктуры, учётки, "
            "членства, задачи HTQ. Идемпотентно. Только для локальной БД.")

    def add_arguments(self, parser):
        parser.add_argument("--skip-tasks", action="store_true",
                            help="Не наполнять домен задач строительной компании.")
        parser.add_argument("--password", default=None,
                            help="Пароль демо-учёток (по умолчанию — как у seed_employee_accounts).")
        parser.add_argument("--force-remote", action="store_true",
                            help="Снять защиту от неместной БД. Не используйте.")

    def _assert_local(self, force: bool, host: str | None = None) -> None:
        """Тот же сторож, что у seed_hr_demo: команда заводит схемы и пишет
        в десятки таблиц — не то, что стоит отправить на боевой адрес из
        корневого .env по опечатке."""
        if host is None:
            host = str(settings.DATABASES["default"].get("HOST", ""))
        if host in {"localhost", "127.0.0.1", "db", "::1", ""} or force:
            self.stdout.write(f"  БД: {host or '(по умолчанию)'}")
            return
        raise CommandError(
            f"DB_HOST={host!r} не похож на локальную БД. Команда заводит компании "
            f"и наполняет их демо-данными — только для локальной среды. "
            f"Если это осознанно — --force-remote."
        )

    def handle(self, *args, **opts):
        self._assert_local(opts["force_remote"])
        for slug, name, kind, parent in GROUP:
            self._ensure_company(slug, name, kind, parent)

        account_opts = {"password": opts["password"]} if opts["password"] else {}
        for slug, *_ in GROUP:
            self.stdout.write(f"\n== {slug} ==")
            call_command("seed_hr_demo", company=slug, verbosity=opts["verbosity"])
            call_command("seed_employee_accounts", company=slug,
                         verbosity=opts["verbosity"], **account_opts)
            self._grant(slug, _own_staff_user_ids(slug), "своим сотрудникам")

        # Второй проход отдельный и идёт ПОСЛЕ сида всех компаний:
        # serving_holders поднимается вверх по дереву владения и читает
        # кадровые карточки предка — до сида холдинга он вернул бы пусто.
        #
        # Обслуживающие должности холдинга дают членство только тогда, когда
        # должности НАЗНАЧЕНА роль: наследование несёт роли, а признак
        # serves_subsidiaries — лишь канал для них (apps/access/services/holders.py).
        # Демо-сид роли не назначает намеренно — раздача прав это решение
        # человека, а не демо-данные, — поэтому на свежем стенде здесь ноль.
        # Печатаем это явно: молчание читалось бы как «наследование сломано».
        granted_serving = 0
        for slug, *_ in GROUP:
            granted_serving += self._grant(slug, serving_holders(slug),
                                           "обслуживающим из вышестоящих")
        if granted_serving == 0:
            self.stdout.write(
                "\n  Обслуживающих держателей из вышестоящих компаний нет: "
                "должностям холдинга ещё не назначены роли, а без роли признак "
                "«обслуживает дочерние компании» ничего не выдаёт. Назначьте "
                "роль должности на экране должностей — членства доберёт "
                "`manage.py company_grant --company <slug> --serving`."
            )

        if not opts["skip_tasks"]:
            self.stdout.write(f"\n== задачи {TASKS_COMPANY} ==")
            call_command("seed_tasks_demo", company=TASKS_COMPANY, verbosity=opts["verbosity"])

        self.stdout.write(self.style.SUCCESS("\nСтенд группы готов."))

    def _ensure_company(self, slug: str, name: str, kind: str, parent: str | None) -> None:
        company = Company.objects.select_related("parent").filter(slug=slug).first()
        if company is None:
            try:
                lifecycle.provision_company(slug=slug, name=name, kind=kind, parent_slug=parent)
            except lifecycle.LifecycleError as exc:
                raise CommandError(exc.detail) from exc
            self.stdout.write(f"  {slug}: заведена")
            return
        if company.status != CompanyStatus.ACTIVE:
            raise CommandError(f"Компания {slug} в архиве — верните её: manage.py company_restore {slug}.")
        if parent and company.parent_id is None:
            # dev-база после tenancy_bootstrap: HTQ есть, родителя нет
            # (на бою его выставляет PATCH блока A — roadmap §7 шаг 5).
            company.parent = Company.objects.get(slug=parent)
            company.save(update_fields=["parent", "updated_at"])
            self.stdout.write(f"  {slug}: уже есть, родитель выставлен → {parent}")
            return
        if company.kind != kind:
            self.stdout.write(self.style.WARNING(
                f"  {slug}: уже есть с kind={company.kind!r} (в документе {kind!r}) — не меняю"))
            return
        self.stdout.write(f"  {slug}: уже есть")

    def _grant(self, slug: str, user_ids: list[int], label: str) -> int:
        if not user_ids:
            return 0
        company = Company.objects.get(slug=slug)
        granted = sum(1 for uid in user_ids if membership_service.grant_membership(company, uid))
        self.stdout.write(f"  членства {label}: новых {granted}, было {len(user_ids) - granted}")
        return granted
