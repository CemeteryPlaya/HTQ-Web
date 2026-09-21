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

**Порядок шагов не косметика**: уровни → отделы → должности → роли
должностей → люди → руководители → подчинение → штатное расписание. Уровни
идут первыми,
потому что ``Position.level`` — кэш, который считается из
``LevelThreshold`` по весу должности; без порогов должность молча получает
запасной уровень (``position_service._DEFAULT_LEVEL``), и иерархия
схлопывается в один ярус. Отделы идут раньше должностей (FK), должности
раньше сотрудников (``Employee.department``/``position`` — оба ``PROTECT
NOT NULL``), а руководители отделов проставляются после сотрудников:
``Department.manager`` ссылается на ``Employee``, которого до этого шага
ещё нет.

**Роли должностей** (задача 11 блока I «Единая модель прав»). С задачи 9
сид не пишет ``Position.permissions`` — колонка мертва для кадровых прав, —
и ``Post.hr_level`` справочника структур раскладывается напрямую в
``PositionRole`` через ``apps.access.interface.ensure_position_role``:
ровно то, что администратор сделал бы руками после переноса
(``access_backfill_positions``), с тем же кодом роли
(``legacy_roles.ROLE_CODES``) и той же областью (``legacy_roles.
SCOPE_KINDS``: junior/middle → отдел держателя, senior/lead → компания).
Без этого свежий стенд после ``seed_group_demo`` получал бы директоров без
кадровых ролей — перенос без колонки угадывает уровень по названию, а
«директор» кадровиком не считается. Только с ``--company``: роль должности
живёт в ``public`` с ключом ``company_slug``, и в режиме перехода (без
компании) выдавать её некому — шаг пропускается с сообщением, а не
подставляет ``public`` за компанию.
"""

from __future__ import annotations

import datetime as dt

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.hr.management import group_structures as gs
from apps.hr.models import (
    Department, Employee, LevelThreshold, Position, ReportingRelation,
    StaffingPosition, Substitution,
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
            self._run(gs.structure_for("construction"), options, company_slug=None)
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
            self._run(structure, options, company_slug=slug)

    @transaction.atomic
    def _run(self, structure: gs.Structure, options, *, company_slug: str | None) -> None:
        if options["purge_e2e"]:
            self._purge_e2e()
        levels = self._seed_levels()
        units = self._seed_units(structure)
        positions = self._seed_positions(structure, units)
        roles = self._seed_position_roles(structure, positions, company_slug)
        employees = self._seed_employees(structure, positions)
        managers = self._seed_managers(structure, units, positions, employees)
        relations = self._seed_relations(structure, positions)
        substitutions = self._seed_substitutions(structure, positions)
        staffing = self._seed_staffing(positions)
        self.stdout.write(self.style.SUCCESS(
            f"\nГотово: уровней {levels}, подразделений {len(units)}, должностей "
            f"{len(positions)}, ролей должностей {roles}, сотрудников "
            f"{len(employees)}, руководителей {managers}, связей подчинения "
            f"{relations}, замещений {substitutions}, штатных единиц {staffing}."
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

    def _check_no_foreign_positions_on_our_weights(self, structure) -> None:
        """Отказ ПОНЯТНОЙ ошибкой, если вес будущей должности уже занят чужой.

        ``Position.weight`` уникален в пределах схемы, а апдейт в
        ``_seed_positions`` идёт по ``title`` — чужую должность на нужном
        весе он не снимает. Такое бывает на dev-базе, где раньше уже
        прогонялся ДРУГОЙ сид (например, старый пятиуровневый
        ``seed_hr_demo`` с «Генеральный директор» на весе 10, которого
        новая структура HTQ хочет для «Директор»): без этой проверки запись
        падает ``IntegrityError: duplicate key value violates unique
        constraint "hr_position_weight_key"``, и причина по этому сообщению
        не восстанавливается.

        Молча снести чужую должность здесь опаснее отказа: на ней могут
        висеть сотрудники, вакансии, штатные строки — все ``PROTECT``, и
        снос попал бы в ``ProtectedError`` в месте, которое тоже не укажет
        на настоящую причину.
        """
        wanted_titles = {post.title for post in structure.posts}
        wanted_weights = {post.weight: post.title for post in structure.posts}
        conflicts = list(
            Position.objects.filter(weight__in=wanted_weights)
            .exclude(title__in=wanted_titles)
            .values_list("weight", "title")
        )
        if not conflicts:
            return
        pairs = "; ".join(
            f"вес {weight} — чужая должность «{title}» (нужен «{wanted_weights[weight]}»)"
            for weight, title in conflicts
        )
        raise CommandError(
            f"В этой схеме уже есть должности на весах новой структуры: {pairs}. "
            f"Похоже на следы прежнего сида — используйте пустую схему "
            f"(--company <slug>) либо снесите прежние демо-данные вручную."
        )

    def _seed_positions(self, structure, units) -> dict[str, Position]:
        self.stdout.write("Должности...")
        self._check_no_foreign_positions_on_our_weights(structure)
        out: dict[str, Position] = {}

        # Системные должности заводит их сервис, а не upsert сида: на бою их
        # кладёт та же функция (hr_participant), и два пути к одной строке
        # разъехались бы. Сегодня системная должность одна — ОСУ.
        from apps.hr.services import participant_service

        for post in structure.posts:
            if not post.is_system:
                continue
            assert post.title == participant_service.PARTICIPANT_TITLE, post.title
            assert post.unit == participant_service.PARTICIPANT_UNIT_PATH, post.unit
            try:
                position, _ = participant_service.ensure_participant()
            except participant_service.ParticipantWeightTaken as exc:
                raise CommandError(exc.detail) from exc
            out[post.title] = position

        for post in structure.posts:
            if post.is_system:
                continue
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
                    # ``permissions`` больше НЕ проставляется (задача 9 блока
                    # I: колонка мертва для авторизации кадрового домена).
                    # ``post.hr_level`` раскладывается в роли apps.access
                    # (``PositionRole``) следующим шагом —
                    # ``_seed_position_roles`` (задача 11).
                },
            )
            out[post.title] = position
        self.stdout.write(f"  {len(out)}")
        return out

    def _seed_position_roles(self, structure, positions, company_slug: str | None) -> int:
        """``Post.hr_level`` → системная роль должности с областью по правилу
        переноса (см. докстринг модуля). Возвращает число должностей с ролью.

        Через ``apps.access.interface`` — ``apps.access`` для ``apps.hr``
        соседняя аппка, её модели отсюда не видны (сторож
        ``apps/core/tests/test_app_isolation.py``). Идемпотентность — на
        стороне ``ensure_position_role``: второй прогон ничего не дублирует и
        область, выставленную кадровиком руками, не переписывает.
        """
        self.stdout.write("Роли должностей...")
        if company_slug is None:
            self.stdout.write(
                "  пропущено: роль должности (PositionRole) ключуется по "
                "company_slug, а без --company компании нет; выдайте роли через "
                "manage.py access_backfill_positions после переноса."
            )
            return 0

        from apps.access import interface as access
        from apps.hr import legacy_roles

        granted = created = 0
        for post in structure.posts:
            level = post.hr_level
            if level not in legacy_roles.ROLE_CODES:
                continue
            if access.ensure_position_role(
                company_slug, positions[post.title].id,
                legacy_roles.ROLE_CODES[level], legacy_roles.SCOPE_KINDS[level],
            ):
                created += 1
            granted += 1
        self.stdout.write(f"  {granted} (создано сейчас {created})")
        return granted

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

    def _seed_substitutions(self, structure, positions) -> int:
        """Матрица замещения документа (HR-FRM-006).

        Через сервис, а не напрямую в модель: сервис проверяет пересечение
        периодов, и сид обязан проходить ту же проверку, что живой ввод, —
        иначе демо-данные окажутся тем состоянием, которого UI не допускает.

        Идемпотентность — по тройке (должность, вид, дата начала): повторный
        запуск не плодит строк и не падает на пересечении с самим собой.
        """
        from apps.hr.services import substitution_service as sub_svc

        if not structure.substitutions:
            return 0
        self.stdout.write("Замещение...")
        count = 0
        for row in structure.substitutions:
            existing = Substitution.objects.filter(
                position=positions[row.position], kind=row.kind,
                valid_from=STRUCTURE_EFFECTIVE_FROM,
            ).first()
            if existing is not None:
                existing.substitute_position = positions[row.substitute]
                existing.basis = row.basis
                existing.note = row.note or None
                existing.save(update_fields=["substitute_position", "basis",
                                             "note", "updated_at"])
            else:
                sub_svc.create(
                    position_id=positions[row.position].id,
                    substitute_position_id=positions[row.substitute].id,
                    kind=row.kind, basis=row.basis, note=row.note or None,
                    valid_from=STRUCTURE_EFFECTIVE_FROM, valid_to=None,
                )
            count += 1
        self.stdout.write(f"  {count}")
        self._warn_unmapped_substitutions(structure, positions)
        return count

    def _warn_unmapped_substitutions(self, structure, positions) -> None:
        """Строка документа, которую нельзя выразить должностью.

        HR-FRM-006 называет замещающим системного администратора
        «Внутригрупповой ИТ-подрядчика» — это не должность и не
        пользователь платформы. Молчать об этом нельзя: незакрытая строка
        утверждённого документа должна быть видна оператору стенда.
        """
        if structure.kind != "holding":
            return
        if "Специалист технической поддержки" not in positions:
            return
        self.stdout.write(self.style.WARNING(
            "  Строка HR-FRM-006 «Системный администратор (у нас — Специалист "
            "технической поддержки) → Внутригрупповой "
            "ИТ-подрядчик» не заведена: замещающий в документе — внешний "
            "подрядчик, а не должность. Вопрос руководству (roadmap §8)."
        ))

    def _seed_staffing(self, positions) -> int:
        """«1 шт. ед.» у каждой должности документа.

        Ключ upsert'а — только ``position``: модель не несёт уникального
        ограничения на пару ``(position, department)``, и ключ по обеим
        полям при переносе должности в другое подразделение оставлял бы
        старую штатную строку сиротой и заводил вторую — второй прогон на
        таких данных падал бы ``MultipleObjectsReturned``. Отдел поэтому
        только в ``defaults``: перенос обновляет существующую строку на
        месте, а не плодит новую.

        Системные должности (блок F: ОСУ) НЕ получают штатную единицу — это
        закреплено в документе: ОСУ нарисована без единицы и в счётчик
        «всего 12» не входит. Штатное расписание касается только обычных
        должностей (тех, что ``is_system=False``).
        """
        self.stdout.write("Штатное расписание...")
        staffed_count = 0
        for position in positions.values():
            # Системные должности пропускаем: они не носят в себе штатной единицы.
            if position.is_system:
                continue
            StaffingPosition.objects.update_or_create(
                position=position,
                defaults={"department": position.department, "headcount": 1},
            )
            staffed_count += 1
        self.stdout.write(f"  {staffed_count}")
        return staffed_count
