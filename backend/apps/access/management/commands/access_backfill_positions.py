"""Перенос кадровых уровней в роли должностей (блок I, задача 2).

Задача 1 того же блока завела четыре системные роли (``hr-junior``,
``hr-middle``, ``hr-senior``, ``hr-lead``, миграция ``access/0005``) взамен
четырёх старых кадровых уровней. Задача 1b дала штатной выдаче
(``PositionRole``) поле ``scope_kind``. Ни одна из них не тронула ДАННЫЕ —
``PositionRole`` в базе пуст, и включение гейтов новой модели (задачи 4–7
того же блока) отняло бы права у каждого, кому сегодня назначен уровень.
Эта команда переносит их: каждая должность получает роль, соответствующую
тому, что её держатель имеет СЕГОДНЯ — не больше и не меньше.

Уровень должности определяется ТЕМ ЖЕ порядком, что ``resolve_hr_access``
(``apps/hr/access.py``) резолвит его для живого JWT-токена:

1. Явный ``Position.permissions["hr_level"]``.
2. Иначе — эвристика ``classify_hr_level`` по держателю должности (название
   должности/отдела).

Своей эвристики команда не пишет и не может: сама реализация — HR-домен,
доступный ей только через новую точку ``apps.hr.interface.
list_positions_hr_levels`` (см. её докстринг). ``apps.hr`` для ``apps.access``
соседняя аппка (``apps/core/tests/test_app_isolation.py``), и до этой задачи
у ``apps.hr.interface`` не было функции, отдающей уровень должности разом по
всей компании — ``get_employee_brief`` резолвит его по ОДНОМУ user_id из
токена, а бэкфиллу нужны ВСЕ должности сразу. Постановка функции в
``apps.hr.interface``, а не перенос всей команды в ``apps/hr``, — потому что
результат переноса (``PositionRole``) принадлежит ``apps.access``: команда,
живущая в ``apps/hr``, столкнулась бы с ЗЕРКАЛЬНОЙ проблемой (прямой импорт
чужой модели ``apps.access.models.PositionRole``) вместо решённой.

``scope_kind`` — решение контроллера этой задачи, а не брифа (задача 1b
появилась уже после того, как бриф был написан): старая модель сужала
список сотрудников до СВОЕГО ОТДЕЛА для junior/middle
(``apps/hr/views.py``: ``if not access.can_read_all``), а senior/lead несли
``hr.employees.view.all`` — то есть видели всю компанию. Перенос без разбора
в ``COMPANY`` (умолчание модели) молча расширил бы junior/middle до всей
компании — то самое расширение доступа, которого перенос не должен делать.

``PositionRole`` живёт в ``public`` (``apps.access`` не в
``settings.TENANT_APPS``), а сама должность — в схеме компании. Команда тем
не менее пишет ``PositionRole`` НЕ выходя из ``use_company(slug)``: он ставит
``search_path`` в ``co_<slug>, public`` (``htqweb/tenancy/db.py``), и
``public`` остаётся виден — тем же приёмом, что и ``apps.access.services.
resolve._position_role_ids`` читает ``PositionRole`` на каждом боевом
запросе, уже находясь внутри контекста компании (см. отчёт задачи, раздел
про проверку search_path).

Штатный API выдачи (``apps.access.services.assignment.set_position_roles``)
``scope_kind`` не принимает и, что важнее, ЗАМЕНЯЕТ набор ролей должности
целиком — для переноса, который обязан не трогать вручную назначенные роли,
не подходит вовсе. Эта команда пишет ``PositionRole`` напрямую через ORM.

Идемпотентна: повторный запуск не создаёт вторых связей и не меняет уже
выставленную (в т.ч. вручную кадровиком) роль или её область. Должность, у
которой ЕСТЬ ``PositionRole`` на роль ИЗ ЭТОГО ЖЕ набора (hr-*), но ДРУГУЮ,
чем вычислено сейчас, — не трогается вовсе, только упоминается в сводке:
кадровик мог назначить её раньше, и молча заменить его решение — не задача
переноса. Должность без какого-либо сигнала об уровне (нет ни явного
``hr_level``, ни держателя, по которому угадать) роли не получает: перенос
не выдумывает прав.

⚠️ Раунд правок 1: должность с НЕСКОЛЬКИМИ держателями может сегодня давать
им РАЗНЫЙ уровень (``Employee.department`` — независимый FK, эвристика
``classify_hr_level`` смотрит в т.ч. на отдел держателя). Правило выбора роли
для такой должности не меняется (по-прежнему первый держатель по ``id`` —
``apps.hr.interface.list_positions_hr_levels``), но расхождение печатается
ОТДЕЛЬНОЙ категорией сводки, рядом с конфликтом: человек на бою обязан
увидеть, что для этой должности перенос выбирал МЕЖДУ уровнями, а не
подтверждённое согласие всех держателей. Разбор — руками, не автоматикой.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.core.management.base import BaseCommand, CommandError

from apps.access.models import PositionRole, Role, ScopeKind

#: Тот же код, что ``apps.hr.legacy_roles.ROLE_CODES`` (задача 1) — сюда
#: НЕ импортируется напрямую: ``apps.hr`` для ``apps.access`` соседняя аппка,
#: и прямой импорт неё-модуля-не-interface ловит
#: ``apps/core/tests/test_app_isolation.py`` (тот же приём и та же причина,
#: что уже применены в ``apps/access/migrations/0005_seed_hr_level_roles.py``
#: — см. его докстринг). Заморожено здесь и сверяется тестом
#: ``test_backfill_positions.py::test_role_codes_match_legacy_source`` —
#: тесты исключены из сторожа и вольны импортировать ``apps.hr.legacy_roles``
#: напрямую ради сверки.
ROLE_CODE_BY_LEVEL: dict[str, str] = {
    "junior": "hr-junior",
    "middle": "hr-middle",
    "senior": "hr-senior",
    "lead": "hr-lead",
}

#: Область роли по уровню — решение КОНТРОЛЛЕРА этой задачи (см. докстринг
#: модуля выше): junior/middle сужались до своего отдела старой моделью,
#: senior/lead несли ``hr.employees.view.all`` (вся компания).
SCOPE_KIND_BY_LEVEL: dict[str, str] = {
    "junior": ScopeKind.DEPARTMENT,
    "middle": ScopeKind.DEPARTMENT,
    "senior": ScopeKind.COMPANY,
    "lead": ScopeKind.COMPANY,
}


@dataclass
class _Conflict:
    position_id: int
    title: str
    existing_codes: tuple[str, ...]
    target_code: str


@dataclass
class _Divergence:
    position_id: int
    title: str
    holder_levels: tuple[str | None, ...]
    chosen_level: str | None


@dataclass
class _CompanyStats:
    slug: str
    total: int = 0
    created: int = 0
    already_correct: int = 0
    skipped_no_level: int = 0
    conflicts: list[_Conflict] = field(default_factory=list)
    divergent: list[_Divergence] = field(default_factory=list)

    @property
    def granted(self) -> int:
        return self.created + self.already_correct

    @property
    def skipped(self) -> int:
        return self.skipped_no_level + len(self.conflicts)


class Command(BaseCommand):
    help = (
        "Перенос кадровых уровней (junior/middle/senior/lead) в роли "
        "должностей (PositionRole) — блок I, задача 2. Идемпотентно."
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

        if explicit_slug:
            if companies_iface.get_company(explicit_slug) is None:
                raise CommandError(f"Компания {explicit_slug!r} не найдена в реестре.")
            if not companies_iface.schema_exists(explicit_slug):
                raise CommandError(
                    f"У компании {explicit_slug!r} нет схемы Postgres — SET "
                    f"search_path принял бы её молча, и запись ушла бы в public."
                )
            slugs = [explicit_slug]
        else:
            slugs = companies_iface.active_company_slugs()
            if not slugs:
                self.stdout.write(self.style.WARNING(
                    "Действующих компаний не найдено — переносить некуда."))
                return

        roles_by_code = {
            role.code: role
            for role in Role.objects.filter(code__in=ROLE_CODE_BY_LEVEL.values())
        }
        missing = set(ROLE_CODE_BY_LEVEL.values()) - set(roles_by_code)
        if missing:
            raise CommandError(
                "Роли не засеяны в реестре (миграция access.0005 не "
                "применена?): " + ", ".join(sorted(missing))
            )
        hr_role_ids = {role.id for role in roles_by_code.values()}

        all_stats = [
            self._process_company(slug, roles_by_code, hr_role_ids, dry_run)
            for slug in slugs
        ]

        for stats in all_stats:
            self._print_company_summary(stats, dry_run)
        if len(all_stats) > 1:
            self._print_grand_summary(all_stats, dry_run)

    def _process_company(self, slug, roles_by_code, hr_role_ids, dry_run) -> _CompanyStats:
        from apps.hr import interface as hr
        from htqweb.tenancy.db import use_company

        stats = _CompanyStats(slug=slug)
        with use_company(slug):
            positions = hr.list_positions_hr_levels()
            stats.total = len(positions)

            existing_by_position: dict[int, set[int]] = {}
            for row in (
                PositionRole.objects
                .filter(company_slug=slug, role_id__in=hr_role_ids)
                .values("position_id", "role_id")
            ):
                existing_by_position.setdefault(row["position_id"], set()).add(row["role_id"])

            for position in positions:
                level = position["hr_level"]

                # Расхождение печатается НЕЗАВИСИМО от того, что случится с
                # ролью дальше (создана/уже верна/конфликт/пропуск): если
                # первый держатель не даёт уровня (level is None), а другой
                # держатель этой же должности его даёт, должность будет
                # пропущена ниже — и это ЕЩЁ важнее увидеть в сводке, не
                # только сам факт разногласия.
                if position["divergent"]:
                    stats.divergent.append(_Divergence(
                        position_id=position["id"], title=position["title"],
                        holder_levels=position["holder_levels"], chosen_level=level,
                    ))

                if level is None:
                    stats.skipped_no_level += 1
                    continue

                target_code = ROLE_CODE_BY_LEVEL[level]
                target_role = roles_by_code[target_code]
                scope_kind = SCOPE_KIND_BY_LEVEL[level]
                existing_ids = existing_by_position.get(position["id"], set())

                if target_role.id in existing_ids:
                    stats.already_correct += 1
                    continue
                if existing_ids:
                    other_codes = tuple(sorted(
                        code for code, role in roles_by_code.items()
                        if role.id in existing_ids
                    ))
                    stats.conflicts.append(_Conflict(
                        position_id=position["id"], title=position["title"],
                        existing_codes=other_codes, target_code=target_code,
                    ))
                    continue

                stats.created += 1
                if not dry_run:
                    PositionRole.objects.get_or_create(
                        company_slug=slug, position_id=position["id"],
                        role=target_role, defaults={"scope_kind": scope_kind},
                    )

        return stats

    def _print_company_summary(self, stats: _CompanyStats, dry_run: bool) -> None:
        prefix = "[dry-run] " if dry_run else ""
        divergent_note = (
            f", расхождений по держателям {len(stats.divergent)}"
            if stats.divergent else ""
        )
        self.stdout.write(self.style.SUCCESS(
            f"{prefix}Компания {stats.slug}: должностей всего {stats.total}, "
            f"роль назначена {stats.granted} (создано сейчас {stats.created}, "
            f"уже было верно {stats.already_correct}), пропущено {stats.skipped}"
            f"{divergent_note}."
        ))
        if stats.skipped_no_level:
            self.stdout.write(
                f"  - без сигнала об уровне (не HR-профиль и нет явного "
                f"hr_level): {stats.skipped_no_level}"
            )
        for conflict in stats.conflicts:
            self.stdout.write(self.style.WARNING(
                f"  - конфликт: должность #{conflict.position_id} "
                f"«{conflict.title}» уже несёт {', '.join(conflict.existing_codes)}, "
                f"перенос вычислил {conflict.target_code} — не тронуто, решите вручную."
            ))
        for divergence in stats.divergent:
            levels = ", ".join(level or "нет уровня" for level in divergence.holder_levels)
            chosen = divergence.chosen_level or "нет уровня (должность пропущена)"
            self.stdout.write(self.style.WARNING(
                f"  - расхождение по держателям: должность #{divergence.position_id} "
                f"«{divergence.title}» — держатели дают разные уровни: {levels}; "
                f"для роли взят {chosen} (первый держатель по id) — проверьте вручную."
            ))

    def _print_grand_summary(self, all_stats: list[_CompanyStats], dry_run: bool) -> None:
        prefix = "[dry-run] " if dry_run else ""
        total = sum(s.total for s in all_stats)
        granted = sum(s.granted for s in all_stats)
        skipped = sum(s.skipped for s in all_stats)
        divergent = sum(len(s.divergent) for s in all_stats)
        divergent_note = f", расхождений по держателям {divergent}" if divergent else ""
        self.stdout.write(self.style.SUCCESS(
            f"{prefix}ИТОГО по {len(all_stats)} компаниям: должностей {total}, "
            f"роль назначена {granted}, пропущено {skipped}{divergent_note}."
        ))
