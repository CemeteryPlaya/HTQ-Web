"""Перенос БАЗОВОГО доступа: роль ``employee-basic`` каждому участнику компании.

Блок I «Единая модель прав», задача 4, раунд правок 1. Соседняя половина
``access_backfill_positions``: та переносит кадровые УРОВНИ в роли
должностей, эта — то, что сегодня есть у человека просто потому, что
проверок нет вовсе.

**Зачем.** Роль ``employee-basic`` заведена миграцией ``access/0004`` как
шаблон дня приёма (профиль, мессенджер, конференции, почта, задачи,
ежедневка, новости, заявки) — и не выдавалась НИКОМУ: ни миграцией, ни
бэкфиллом должностей (тот пишет только ``hr-*``, а они не несут ни одного
узла ``users.*``). Пока гейтов не было, это ничего не значило: ручки не
спрашивали прав. С задачи 4 спрашивают — и без этой раздачи 403 получают
все, включая кадровиков с ``hr-senior``, у которых своя роль про ``hr``, а
не про профиль и подбор коллег. Перенос «как есть» для базового доступа —
это и есть выдать её всем, а не сузить молча.

**Кому.** Участникам компании (``CompanyMembership``) с ДЕЙСТВУЮЩЕЙ учёткой
— список приходит из ``apps.companies.interface.active_member_ids`` (состав
компании принадлежит соседу, ``apps/core/tests/test_app_isolation.py``).
Не «всем активным пользователям платформы», как ``company_grant
--all-users``: то членство, а это ПРАВА ВНУТРИ компании, и выдавать их
человеку, которого в компанию не пускают, значило бы засеять реестр
назначениями, не значащими ничего.

**Область — ``COMPANY``.** Базовая роль не про отдел: свой профиль, свои
задачи и своя ежедневка не сужаются подразделением, а ``DEPARTMENT``
потребовал бы ``scope_id`` и кадровой карточки у каждого — то есть отнял
бы базовый доступ у всех, у кого её нет.

**Почему отдельной командой, а не флагом в ``access_backfill_positions``.**
Там единица работы — ДОЛЖНОСТЬ, и вся сводка про уровни, конфликты и
расхождения держателей; здесь единица — ЧЕЛОВЕК, и сводка про выдачу. Одна
команда с двумя несвязанными сводками и двумя режимами отказа читается
хуже двух; кроме того, у них разный профиль повторного запуска — перенос
должностей делается один раз на выкатке, а базовую роль зовут ещё и после
приёма новых людей, пока выдача не переехала в интерфейс. Общий у них
только ``--company``/``--dry-run``, и это не повод их сращивать.

Идемпотентна: повторный запуск ничего не дублирует
(``RoleAssignment.objects.get_or_create`` по тому же ключу, что несут
частичные индексы модели) и печатает, скольким выдали и скольким уже было.

В отличие от переноса должностей, ``use_company`` здесь НЕ нужен: и
``RoleAssignment``, и ``CompanyMembership`` лежат в ``public`` — ни одной
таблицы из схемы компании команда не читает. Поэтому ей не нужна и
физическая схема: компания, у которой она ещё не создана, обслуживается
так же.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.core.management.base import BaseCommand, CommandError

from apps.access.models import Role, RoleAssignment, ScopeKind

#: Код роли из миграции ``access/0004_seed_employee_role.py``. Литерал, а не
#: импорт из миграции: миграции — история, их модули переписывать нельзя, но
#: и тянуть из них константы в рабочий код не стоит. Сверяется тестом.
ROLE_CODE = "employee-basic"


@dataclass
class _CompanyStats:
    slug: str
    members: int = 0
    created: int = 0
    already: int = 0


class Command(BaseCommand):
    help = (
        f"Выдать базовую роль {ROLE_CODE} всем участникам компании с "
        "действующей учёткой (RoleAssignment, область company). Идемпотентно."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--company", dest="company", default=None,
            help="slug одной компании. Без флага — все действующие компании "
                 "(apps.companies.interface.active_company_slugs).",
        )
        parser.add_argument(
            "--dry-run", dest="dry_run", action="store_true",
            help="Ничего не писать — только показать, что было бы сделано.",
        )

    def handle(self, *args, **options):
        from apps.companies import interface as companies_iface

        dry_run: bool = options["dry_run"]
        explicit_slug: str | None = options["company"]

        role = Role.objects.filter(code=ROLE_CODE).first()
        if role is None:
            raise CommandError(
                f"Роль {ROLE_CODE} не найдена в каталоге (миграция "
                f"access.0004 не применена?) — выдавать нечего."
            )

        if explicit_slug:
            if companies_iface.get_company(explicit_slug) is None:
                raise CommandError(f"Компания {explicit_slug!r} не найдена в реестре.")
            slugs = [explicit_slug]
        else:
            slugs = companies_iface.active_company_slugs()
            if not slugs:
                self.stdout.write(self.style.WARNING(
                    "Действующих компаний не найдено — выдавать некому."))
                return

        all_stats = [self._process_company(slug, role, dry_run) for slug in slugs]

        for stats in all_stats:
            self._print_company_summary(stats, dry_run)
        if len(all_stats) > 1:
            self._print_grand_summary(all_stats, dry_run)

    def _process_company(self, slug: str, role: Role, dry_run: bool) -> _CompanyStats:
        from apps.companies import interface as companies_iface

        stats = _CompanyStats(slug=slug)
        member_ids = companies_iface.active_member_ids(slug)
        stats.members = len(member_ids)
        if not member_ids:
            return stats

        # Одним запросом, а не get_or_create на каждого: у компании могут быть
        # тысячи участников, а сводка обязана различать «выдали» и «уже было»
        # ДО записи — иначе dry-run не смог бы её напечатать.
        existing = set(
            RoleAssignment.objects
            .filter(company_slug=slug, role=role, user_id__in=member_ids,
                    scope_kind=ScopeKind.COMPANY, scope_id=None)
            .values_list("user_id", flat=True)
        )
        for user_id in member_ids:
            if user_id in existing:
                stats.already += 1
                continue
            stats.created += 1
            if not dry_run:
                RoleAssignment.objects.get_or_create(
                    company_slug=slug, user_id=user_id, role=role,
                    scope_kind=ScopeKind.COMPANY, scope_id=None,
                )
        return stats

    def _print_company_summary(self, stats: _CompanyStats, dry_run: bool) -> None:
        prefix = "[dry-run] " if dry_run else ""
        self.stdout.write(self.style.SUCCESS(
            f"{prefix}Компания {stats.slug}: участников с действующей учёткой "
            f"{stats.members}, роль {ROLE_CODE} выдана сейчас {stats.created}, "
            f"уже была у {stats.already}."
        ))
        if not stats.members:
            self.stdout.write(self.style.WARNING(
                "  - участников с действующей учёткой нет: проверьте "
                "CompanyMembership (manage.py company_grant) — без членства "
                "токен на поддомен компании не выпускается вовсе."
            ))

    def _print_grand_summary(self, all_stats: list[_CompanyStats], dry_run: bool) -> None:
        prefix = "[dry-run] " if dry_run else ""
        members = sum(s.members for s in all_stats)
        created = sum(s.created for s in all_stats)
        already = sum(s.already for s in all_stats)
        self.stdout.write(self.style.SUCCESS(
            f"{prefix}ИТОГО по {len(all_stats)} компаниям: участников {members}, "
            f"выдано сейчас {created}, уже было {already}."
        ))
