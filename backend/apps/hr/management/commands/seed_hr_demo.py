"""Наполнение HR демонстрационными данными: одна из четырёх утверждённых
оргструктур группы (документ 10.09.2026, `apps/hr/management/group_structures.py`).

Без ``--company`` — структура HTQ (`construction`) в текущий ``search_path``
(режим перехода: пока единственная компания — HTQ). С ``--company SLUG`` —
команда входит в схему этой компании и сеет структуру, соответствующую её
``Company.kind`` (holding/construction/it/service).

ТОЛЬКО ДЛЯ ЛОКАЛЬНОЙ БАЗЫ. Команда отказывается работать, если ``DB_HOST``
похож на удалённый хост, — см. ``_assert_local``. Боевую схему наполняют
не так и не отсюда.

Зачем команда, а не разовый скрипт: наполнение должно быть повторяемым и
читаемым. Всё через ``update_or_create`` по естественному ключу, поэтому
второй запуск ничего не дублирует, а правит на месте.

**Порядок шагов не косметика**: уровни → отделы → должности → люди →
руководители → подчинение → штатное расписание. Уровни идут первыми,
потому что ``Position.level`` — кэш, который считается из
``LevelThreshold`` по весу должности; без порогов должность молча получает
запасной уровень (``position_service._DEFAULT_LEVEL``), и иерархия
схлопывается в один ярус. Отделы идут раньше должностей (FK), должности
раньше сотрудников (``Employee.department``/``position`` — оба ``PROTECT
NOT NULL``), а руководители отделов проставляются после сотрудников:
``Department.manager`` ссылается на ``Employee``, которого до этого шага
ещё нет.
"""

from __future__ import annotations

import datetime as dt

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.hr.management import group_structures as gs
from apps.hr.models import (
    Department, Employee, LevelThreshold, Position, ReportingRelation,
    StaffingPosition,
)
from apps.hr.services.position_service import _DEFAULT_LEVEL

# Дата документа: с неё «действуют» связи подчинения.
STRUCTURE_EFFECTIVE_FROM = dt.date(2026, 9, 10)


class Command(BaseCommand):
    help = ("Наполняет HR демо-данными одну из четырёх утверждённых оргструктур "
            "группы (документ 10.09.2026). Идемпотентно. Только для локальной БД.")

    def add_arguments(self, parser):
        parser.add_argument(
            "--company", dest="company", default=None,
            help="slug компании: войти в её схему и засеять структуру её вида "
                 "(holding/construction/it/service). Без флага — структура "
                 "HTQ в текущий search_path (режим перехода).",
        )
        parser.add_argument("--force-remote", action="store_true",
                            help="Снять защиту от неместной БД. Не используйте.")
        parser.add_argument("--purge-e2e", action="store_true",
                            help="Сначала удалить следы E2E-прогонов (префиксы «E2E » и «UI »).")

    def _assert_local(self, force: bool, host: str | None = None) -> None:
        """Отказ работать против чего-либо, кроме локальной базы.

        Дешёвая страховка от опечатки в окружении: ``DB_HOST`` по умолчанию
        приходит из корневого ``.env``, где стоит боевой адрес VPS. Команда
        пишет три десятка строк в четыре таблицы — не то, что стоит
        отправлять туда случайно.

        ``host`` передаётся только из тестов. Иначе проверить эту логику
        можно было бы лишь подменив ``settings.DATABASES``, а это значит
        подставить боевой адрес в живые настройки и понадеяться, что Django
        не переоткроет соединение. Параметр убирает такую возможность
        совсем: правило проверяется как обычная функция от строки.
        """
        if host is None:
            host = str(settings.DATABASES["default"].get("HOST", ""))
        local = {"localhost", "127.0.0.1", "db", "::1", ""}
        if host in local or force:
            self.stdout.write(f"  БД: {host or '(по умолчанию)'}")
            return
        raise CommandError(
            f"DB_HOST={host!r} не похож на локальную БД. Команда наполняет "
            f"HR демо-данными и предназначена только для локальной среды. "
            f"Если это осознанно — --force-remote."
        )

    def _purge_e2e(self) -> None:
        """Убрать следы E2E-прогонов.

        Спеки создают данные и после себя не подчищают — в базе для
        разработки это не страшно, но веса у тестовых должностей случайные
        и лежат вне всех порогов, поэтому они оседают в ярусе с запасным
        уровнем 5 и портят картину иерархии.

        Опознаём по двум следам, а не по одному: должности, отделы и
        вакансии тесты называют с префиксом «E2E »/«UI », а сотрудников
        заводят на служебные домены (@htq.test, @example.com). Прямые
        имена вроде «Сотрудников1785…» под префикс не попадают, а почта —
        попадает всегда.

        Порядок строго обратный зависимостям: ``Employee.position`` и
        ``Vacancy.position`` — ``PROTECT``, так что должность не удалить,
        пока на неё кто-то ссылается. По той же причине сначала снимается
        всё, что ссылается на самого сотрудника (документы, записи времени,
        членства в ОУП, кадровые события): у ``Document.employee`` и
        ``TimeEntry.employee`` тоже ``PROTECT``, и без этого шага удаление
        сотрудников падает с ``ProtectedError``.
        """
        from django.db.models import Q

        from apps.hr.models import (
            Application,
            Document,
            EmployeeDayOverride,
            EmployeeDocumentBlob,
            EmployeeShiftAssignment,
            EmployeeWeekTemplate,
            PersonnelHistory,
            PMO,
            PMOMember,
            ShareableLink,
            ShiftPattern,
            StaffingPosition,
            TimeEntry,
            Vacancy,
            WeekTemplate,
        )

        self.stdout.write("Очистка следов E2E...")

        def named(field: str) -> Q:
            return (Q(**{f"{field}__startswith": "E2E "})
                    | Q(**{f"{field}__startswith": "UI "}))

        # Сотрудники — по служебным доменам почты.
        test_employees = Employee.objects.filter(
            Q(email__endswith="@htq.test") | Q(email__endswith="@example.com")
        )
        emp_ids = list(test_employees.values_list("id", flat=True))

        # 1. Всё, что висит НА сотруднике. Считаем до удаления: delete()
        # возвращает суммарное число объектов вместе с каскадами, а знать
        # хочется по каждой сущности отдельно.
        attached = {
            "документов": Document.objects.filter(
                Q(employee_id__in=emp_ids) | Q(uploaded_by_id__in=emp_ids)
            ),
            "документов-блобов": EmployeeDocumentBlob.objects.filter(
                employee_id__in=emp_ids
            ),
            "записей времени": TimeEntry.objects.filter(employee_id__in=emp_ids),
            "членств в ОУП": PMOMember.objects.filter(employee_id__in=emp_ids),
            "кадровых событий": PersonnelHistory.objects.filter(
                employee_id__in=emp_ids
            ),
            "штатных строк": StaffingPosition.objects.filter(
                Q(position__title__startswith="E2E ")
                | Q(position__title__startswith="UI ")
            ),
            "личных дней": EmployeeDayOverride.objects.filter(
                employee_id__in=emp_ids
            ),
            "назначений смен": EmployeeShiftAssignment.objects.filter(
                employee_id__in=emp_ids
            ),
            "назначений недели": EmployeeWeekTemplate.objects.filter(
                employee_id__in=emp_ids
            ),
        }
        attached_counts = {label: qs.count() for label, qs in attached.items()}
        for qs in attached.values():
            qs.delete()

        # 2. Сами сотрудники. Руководителя нельзя оставить висеть на
        # удаляемом: Department.manager это SET_NULL, но снимаем явно,
        # чтобы порядок удаления не зависел от обхода коллектором.
        Department.objects.filter(manager__in=test_employees).update(manager=None)
        emp_count = test_employees.count()
        test_employees.delete()

        # 3. Отклики раньше вакансий, вакансии раньше должностей.
        app_count = Application.objects.filter(
            Q(candidate_email__endswith="@htq.test")
            | Q(candidate_email__endswith="@example.com")
            | named("candidate_name")
        ).delete()[0]
        vac_count = Vacancy.objects.filter(named("title")).delete()[0]

        pos_count = Position.objects.filter(named("title")).delete()[0]
        dept_count = Department.objects.filter(named("name")).delete()[0]

        # 4. Справочники, ни на кого не ссылающиеся, — по префиксу имени.
        # Публичные ссылки метятся label'ом; у них ещё висит журнал, но он
        # уходит каскадом вместе со ссылкой.
        pmo_count = PMO.objects.filter(named("name")).delete()[0]
        link_count = ShareableLink.objects.filter(named("label")).delete()[0]
        shift_count = ShiftPattern.objects.filter(named("name")).delete()[0]
        # Дефолтный шаблон недели не трогаем даже с тестовым именем: без
        # него резолюция дня свалится в запасную ветку для всей базы.
        tmpl_count = WeekTemplate.objects.filter(named("name")).filter(
            is_default=False
        ).delete()[0]

        detail = ", ".join(f"{k} {v}" for k, v in attached_counts.items() if v)
        self.stdout.write(
            f"  удалено: сотрудников {emp_count}, откликов {app_count}, "
            f"вакансий {vac_count}, должностей {pos_count}, "
            f"отделов {dept_count}, ОУП {pmo_count}, ссылок {link_count}, "
            f"сменных графиков {shift_count}, шаблонов недели {tmpl_count}"
            + (f"; связанное: {detail}" if detail else "")
        )

    def handle(self, *args, **options):
        self._assert_local(options["force_remote"])
        slug = options["company"]
        if slug is None:
            # Режим перехода (roadmap §3): единственная компания — HTQ, её
            # таблицы — там, куда указывает текущий search_path.
            self._run(gs.structure_for("construction"), options)
            return

        from apps.companies import interface as companies

        company = companies.get_company(slug)
        if company is None:
            raise CommandError(f"Компания {slug!r} не найдена в реестре.")
        if not companies.schema_exists(slug):
            raise CommandError(
                f"У компании {slug!r} нет схемы Postgres — SET search_path принял "
                f"бы её молча и данные ушли бы в public. Заведите схему: "
                f"manage.py company_create либо migrate_companies --company {slug}."
            )
        try:
            structure = gs.structure_for(company["kind"])
        except gs.UnknownStructure as exc:
            raise CommandError(str(exc)) from exc

        from htqweb.tenancy.db import use_company

        with use_company(slug):
            self.stdout.write(f"Компания {slug} ({company['kind']}): {structure.company_name}")
            self._run(structure, options)

    @transaction.atomic
    def _run(self, structure: gs.Structure, options) -> None:
        if options["purge_e2e"]:
            self._purge_e2e()
        levels = self._seed_levels()
        units = self._seed_units(structure)
        positions = self._seed_positions(structure, units)
        employees = self._seed_employees(structure, positions)
        managers = self._seed_managers(structure, units, positions, employees)
        relations = self._seed_relations(structure, positions)
        staffing = self._seed_staffing(positions)
        self.stdout.write(self.style.SUCCESS(
            f"\nГотово: уровней {levels}, подразделений {len(units)}, должностей "
            f"{len(positions)}, сотрудников {len(employees)}, руководителей "
            f"{managers}, связей подчинения {relations}, штатных единиц {staffing}."
        ))

    # ── шаги ────────────────────────────────────────────────────────────

    def _seed_levels(self) -> int:
        self.stdout.write("Уровни должностей...")
        for number, w_from, w_to, label, color in gs.LEVELS:
            LevelThreshold.objects.update_or_create(
                level_number=number,
                defaults={"weight_from": w_from, "weight_to": w_to,
                          "label": label, "color": color},
            )
        # Незаявленные уровни (например L5 старого сида, 900–1999) пересеклись
        # бы с N-4 и оставили бы кэш уровня у старых должностей стар.
        retired, _ = LevelThreshold.objects.exclude(
            level_number__in=[n for n, *_ in gs.LEVELS]).delete()
        recomputed = 0
        for pos in Position.objects.all():
            level = gs.level_for(pos.weight) or _DEFAULT_LEVEL
            if pos.level != level:
                Position.objects.filter(pk=pos.pk).update(level=level)
                recomputed += 1
        self.stdout.write(f"  {len(gs.LEVELS)} порогов; убрано чужих {retired}, "
                          f"пересчитано должностей {recomputed}")
        return len(gs.LEVELS)

    def _seed_units(self, structure) -> dict[str, Department]:
        self.stdout.write("Подразделения...")
        out: dict[str, Department] = {}
        for unit in structure.units:
            dept, _ = Department.objects.update_or_create(
                path=unit.path,
                defaults={"name": unit.name, "description": unit.description or None,
                          "unit_type": unit.unit_type, "is_active": True},
            )
            out[unit.path] = dept
        self.stdout.write(f"  {len(out)}")
        return out

    def _seed_positions(self, structure, units) -> dict[str, Position]:
        self.stdout.write("Должности...")
        out: dict[str, Position] = {}
        for post in structure.posts:
            level = gs.level_for(post.weight)
            assert level is not None, f"{post.title}: вес {post.weight} вне LEVELS"
            position, _ = Position.objects.update_or_create(
                title=post.title,
                defaults={
                    "department": units[post.unit],
                    "grade": post.grade,
                    "weight": post.weight,
                    "level": level,
                    "is_active": True,
                    "is_manager": post.is_manager,
                    "external_hierarchy": post.external_hierarchy,
                    "serves_subsidiaries": post.serves_subsidiaries,
                    # Явная матрица приоритетнее эвристики по названию —
                    # см. apps/hr/access.py.
                    "permissions": {"hr_level": post.hr_level, "permissions": []},
                },
            )
            out[post.title] = position
        self.stdout.write(f"  {len(out)}")
        return out

    def _seed_employees(self, structure, positions) -> dict[str, Employee]:
        self.stdout.write("Сотрудники...")
        out: dict[str, Employee] = {}
        hire_base = dt.date.today() - dt.timedelta(days=900)
        for index, person in enumerate(structure.people):
            position = positions[person.post]
            employee, _ = Employee.objects.update_or_create(
                email=gs.email_for(person),
                defaults={
                    "first_name": person.first, "last_name": person.last,
                    "middle_name": person.middle, "phone": person.phone,
                    # Отдел берётся у должности — связка «сотрудник → должность
                    # → отдел» не может разъехаться.
                    "department": position.department, "position": position,
                    "hire_date": hire_base + dt.timedelta(days=index * 21),
                    "status": "active", "is_deleted": False,
                },
            )
            out[person.post] = employee
        self.stdout.write(f"  {len(out)}")
        return out

    def _seed_managers(self, structure, units, positions, employees) -> int:
        self.stdout.write("Руководители подразделений...")
        count = 0
        for path, title in structure.managers.items():
            dept, holder = units[path], employees.get(title)
            if holder is None:
                continue
            dept.manager = holder
            dept.save(update_fields=["manager", "updated_at"])
            count += 1
        self.stdout.write(f"  {count}")
        return count

    def _seed_relations(self, structure, positions) -> int:
        """Вертикали документа — direct, пунктир — functional (по одной строке
        на пару, слева направо; модель направленная, документ — нет)."""
        self.stdout.write("Подчинение...")
        count = 0
        pairs = [(p.reports_to, p.title, "direct") for p in structure.posts if p.reports_to]
        pairs += [(a, b, "functional") for a, b in structure.functional_links]
        for superior, subordinate, kind in pairs:
            ReportingRelation.objects.update_or_create(
                superior_position=positions[superior],
                subordinate_position=positions[subordinate],
                relation_type=kind,
                defaults={"effective_from": STRUCTURE_EFFECTIVE_FROM, "effective_to": None},
            )
            count += 1
        self.stdout.write(f"  {count}")
        return count

    def _seed_staffing(self, positions) -> int:
        """«1 шт. ед.» у каждой должности документа."""
        self.stdout.write("Штатное расписание...")
        for position in positions.values():
            StaffingPosition.objects.update_or_create(
                position=position, department=position.department,
                defaults={"headcount": 1},
            )
        self.stdout.write(f"  {len(positions)}")
        return len(positions)
