"""Наполнение HR демонстрационными данными: уровни, отделы, должности, люди.

ТОЛЬКО ДЛЯ ЛОКАЛЬНОЙ БАЗЫ. Команда отказывается работать, если ``DB_HOST``
похож на удалённый хост, — см. ``_assert_local``. Боевую схему наполняют
не так и не отсюда.

Зачем команда, а не разовый скрипт: наполнение должно быть повторяемым и
читаемым. Всё через ``update_or_create`` по естественному ключу, поэтому
второй запуск ничего не дублирует, а правит на месте.

**Порядок здесь не косметика.** Уровни идут первыми, потому что
``Position.level`` — кэш, который считается из ``LevelThreshold`` по весу
должности. Если порогов нет, каждая должность молча получает запасной
уровень 5 (``position_service._DEFAULT_LEVEL``), и вся иерархия
схлопывается в один ярус. Именно в таком состоянии и была локальная база:
22 должности, 0 порогов.

Отделы идут раньше должностей (FK), должности раньше сотрудников
(``Employee.department``/``position`` — оба ``PROTECT NOT NULL``), а
руководители отделов проставляются последними: ``Department.manager``
ссылается на ``Employee``, которого до этого шага ещё нет.
"""

from __future__ import annotations

import datetime as dt

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.hr.models import Department, Employee, LevelThreshold, Position

# ── уровни должностей ───────────────────────────────────────────────────
#
# Меньший вес = выше в иерархии (0 — верх). Диапазоны не пересекаются:
# LevelThreshold несёт CHECK на weight_from <= weight_to, а сервис
# дополнительно отвергает пересечения (ThresholdRangeOverlap).
LEVELS = [
    (1, 0, 99, "Руководство компании", "#7c3aed"),
    (2, 100, 299, "Руководители направлений", "#2563eb"),
    (3, 300, 599, "Руководители отделов", "#0891b2"),
    (4, 600, 899, "Ведущие специалисты", "#059669"),
    (5, 900, 1999, "Специалисты", "#64748b"),
]

# ── отделы ──────────────────────────────────────────────────────────────
#
# ``path`` — строковый путь, предки вычисляются как префиксы (см.
# interface.org_ancestors). Родитель обязан идти раньше ребёнка.
DEPARTMENTS = [
    ("Руководство", "upr", None),
    ("Строительство", "stroy", "Работы на объектах: земляные, общестроительные, монтаж."),
    ("Электромонтаж", "stroy.elektro", "DC/AC, подстанции и ВЛ."),
    ("Проектирование", "proekt", "Рабочая документация и авторский надзор."),
    ("Снабжение", "snab", "Закупки, склад, логистика на объекты."),
    ("Отдел кадров", "hr", "Кадровое администрирование и подбор."),
    ("Финансы", "fin", "Бухгалтерия и финансовое планирование."),
    ("ИТ", "it", "Инфраструктура и внутренние системы."),
]

# ── должности ───────────────────────────────────────────────────────────
#
# (название, путь отдела, вес, grade, hr_level)
# ``hr_level`` кладётся в ``Position.permissions`` — явная матрица приоритетнее
# эвристики по названию должности (apps/hr/access.py), поэтому кадровик
# получает свой доступ из данных, а не из того, что в названии угадалось
# слово «кадр».
POSITIONS = [
    ("Генеральный директор", "upr", 10, 10, "lead"),
    ("Заместитель генерального директора", "upr", 50, 9, "lead"),

    ("Директор по строительству", "stroy", 120, 9, "senior"),
    ("Начальник участка", "stroy", 320, 7, "middle"),
    ("Прораб", "stroy", 620, 6, "middle"),
    ("Мастер СМР", "stroy", 920, 5, "junior"),
    ("Инженер ПТО", "stroy", 940, 5, "junior"),

    ("Главный энергетик", "stroy.elektro", 340, 8, "middle"),
    ("Ведущий инженер-электрик", "stroy.elektro", 640, 6, "junior"),
    ("Электромонтажник", "stroy.elektro", 960, 4, "junior"),

    ("Главный инженер проекта", "proekt", 150, 9, "senior"),
    ("Ведущий проектировщик", "proekt", 660, 6, "junior"),
    ("Инженер-проектировщик", "proekt", 980, 5, "junior"),

    ("Начальник отдела снабжения", "snab", 360, 7, "middle"),
    ("Специалист по закупкам", "snab", 1000, 4, "junior"),

    ("Директор по персоналу", "hr", 160, 9, "lead"),
    ("Менеджер по персоналу", "hr", 380, 6, "senior"),
    ("Специалист отдела кадров", "hr", 1020, 4, "middle"),

    ("Финансовый директор", "fin", 170, 9, "senior"),
    ("Главный бухгалтер", "fin", 400, 8, "middle"),
    ("Бухгалтер", "fin", 1040, 4, "junior"),

    ("Руководитель ИТ", "it", 420, 7, "middle"),
    ("Системный администратор", "it", 1060, 5, "junior"),
]

# ── сотрудники ──────────────────────────────────────────────────────────
#
# (фамилия, имя, отчество, должность, телефон)
# Телефоны — ровно в формате, который отдаёт PhoneInput: +7 (7XX) XXX-XX-XX.
EMPLOYEES = [
    ("Абдрахманов", "Ерлан", "Серикович", "Генеральный директор", "+7 (700) 100-10-01"),
    ("Ким", "Виктор", "Андреевич", "Заместитель генерального директора", "+7 (700) 100-10-02"),

    ("Нурсеитов", "Данияр", "Маратович", "Директор по строительству", "+7 (701) 200-20-01"),
    ("Исаев", "Тимур", "Русланович", "Начальник участка", "+7 (701) 200-20-02"),
    ("Оспанов", "Бекзат", "Асхатович", "Прораб", "+7 (701) 200-20-03"),
    ("Жумабеков", "Асхат", "Нурланович", "Прораб", "+7 (701) 200-20-04"),
    ("Ткаченко", "Сергей", "Павлович", "Мастер СМР", "+7 (701) 200-20-05"),
    ("Садыков", "Арман", "Болатович", "Инженер ПТО", "+7 (701) 200-20-06"),

    ("Ли", "Александр", "Витальевич", "Главный энергетик", "+7 (702) 300-30-01"),
    ("Мукашев", "Нурлан", "Кайратович", "Ведущий инженер-электрик", "+7 (702) 300-30-02"),
    ("Петров", "Игорь", "Николаевич", "Электромонтажник", "+7 (702) 300-30-03"),

    ("Байжанов", "Кайрат", "Ерболович", "Главный инженер проекта", "+7 (705) 400-40-01"),
    ("Шевченко", "Ольга", "Ивановна", "Ведущий проектировщик", "+7 (705) 400-40-02"),
    ("Ахметова", "Айгуль", "Талгатовна", "Инженер-проектировщик", "+7 (705) 400-40-03"),

    ("Дюсенов", "Марат", "Жомартович", "Начальник отдела снабжения", "+7 (707) 500-50-01"),
    ("Копылова", "Наталья", "Сергеевна", "Специалист по закупкам", "+7 (707) 500-50-02"),

    ("Сулейменова", "Динара", "Кайратовна", "Директор по персоналу", "+7 (708) 600-60-01"),
    ("Ерсултанова", "Жанар", "Бахытовна", "Менеджер по персоналу", "+7 (708) 600-60-02"),
    ("Романова", "Елена", "Андреевна", "Специалист отдела кадров", "+7 (708) 600-60-03"),

    ("Тулегенов", "Аскар", "Муратович", "Финансовый директор", "+7 (747) 700-70-01"),
    ("Ким", "Светлана", "Юрьевна", "Главный бухгалтер", "+7 (747) 700-70-02"),
    ("Досжанова", "Аружан", "Ерлановна", "Бухгалтер", "+7 (747) 700-70-03"),

    ("Волков", "Дмитрий", "Олегович", "Руководитель ИТ", "+7 (771) 800-80-01"),
    ("Абишев", "Нурбол", "Талгатович", "Системный администратор", "+7 (771) 800-80-02"),
]

# Руководители отделов: путь отдела -> должность руководителя.
# Ставится последним шагом — Department.manager ссылается на Employee.
MANAGERS = {
    "upr": "Генеральный директор",
    "stroy": "Директор по строительству",
    "stroy.elektro": "Главный энергетик",
    "proekt": "Главный инженер проекта",
    "snab": "Начальник отдела снабжения",
    "hr": "Директор по персоналу",
    "fin": "Финансовый директор",
    "it": "Руководитель ИТ",
}


def _translit(text: str) -> str:
    """Фамилия -> латиница для служебного e-mail."""
    table = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
        "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
        "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
        "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
        "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    }
    return "".join(table.get(ch, ch if ch.isalnum() and ch.isascii() else "")
                   for ch in text.lower())


class Command(BaseCommand):
    help = ("Наполняет HR демо-данными: уровни должностей, отделы, должности, "
            "сотрудники. Идемпотентно. Только для локальной БД.")

    def add_arguments(self, parser):
        parser.add_argument(
            "--force-remote", action="store_true",
            help="Снять защиту от неместной БД. Не используйте.",
        )
        parser.add_argument(
            "--purge-e2e", action="store_true",
            help="Сначала удалить следы E2E-прогонов (префиксы «E2E » и «UI »).",
        )

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

    @transaction.atomic
    def handle(self, *args, **options):
        self._assert_local(options["force_remote"])
        if options["purge_e2e"]:
            self._purge_e2e()

        levels = self._seed_levels()
        departments = self._seed_departments()
        positions = self._seed_positions(departments)
        employees = self._seed_employees(positions)
        managers = self._seed_managers(departments, positions, employees)

        self.stdout.write(self.style.SUCCESS(
            f"\nГотово: уровней {levels}, отделов {departments and len(departments)}, "
            f"должностей {len(positions)}, сотрудников {len(employees)}, "
            f"руководителей отделов {managers}."
        ))

    # ── шаги ────────────────────────────────────────────────────────────

    def _seed_levels(self) -> int:
        self.stdout.write("Уровни должностей...")
        for number, w_from, w_to, label, color in LEVELS:
            LevelThreshold.objects.update_or_create(
                level_number=number,
                defaults={"weight_from": w_from, "weight_to": w_to,
                          "label": label, "color": color},
            )
        self.stdout.write(f"  {len(LEVELS)} порогов")
        return len(LEVELS)

    def _seed_departments(self) -> dict[str, Department]:
        self.stdout.write("Отделы...")
        out: dict[str, Department] = {}
        for name, path, description in DEPARTMENTS:
            dept, _ = Department.objects.update_or_create(
                path=path,
                defaults={"name": name, "description": description,
                          "is_active": True},
            )
            out[path] = dept
        self.stdout.write(f"  {len(out)} отделов")
        return out

    def _seed_positions(self, departments) -> dict[str, Position]:
        self.stdout.write("Должности...")
        out: dict[str, Position] = {}
        for title, dept_path, weight, grade, hr_level in POSITIONS:
            # level считаем сами, а не полагаемся на пересчёт при записи:
            # порог уже создан выше, и явное значение делает связь весов и
            # уровней видимой прямо здесь.
            level = next(
                (num for num, w_from, w_to, *_ in LEVELS
                 if w_from <= weight <= w_to),
                5,
            )
            position, _ = Position.objects.update_or_create(
                title=title,
                defaults={
                    "department": departments[dept_path],
                    "grade": grade,
                    "weight": weight,
                    "level": level,
                    "is_active": True,
                    # Явная матрица приоритетнее эвристики по названию —
                    # см. apps/hr/access.py.
                    "permissions": {"hr_level": hr_level, "permissions": []},
                },
            )
            out[title] = position
        self.stdout.write(f"  {len(out)} должностей")
        return out

    def _seed_employees(self, positions) -> dict[str, Employee]:
        self.stdout.write("Сотрудники...")
        out: dict[str, Employee] = {}
        hire_base = dt.date.today() - dt.timedelta(days=900)
        for index, (last, first, middle, title, phone) in enumerate(EMPLOYEES):
            position = positions[title]
            email = f"{_translit(last)}.{_translit(first)[:1]}@htq.kz"
            employee, _ = Employee.objects.update_or_create(
                email=email,
                defaults={
                    "first_name": first,
                    "last_name": last,
                    "middle_name": middle,
                    "phone": phone,
                    # Отдел берётся у должности — так связка «сотрудник →
                    # должность → отдел» не может разъехаться.
                    "department": position.department,
                    "position": position,
                    "hire_date": hire_base + dt.timedelta(days=index * 21),
                    "status": "active",
                    "is_deleted": False,
                },
            )
            out[f"{last} {first}"] = employee
        self.stdout.write(f"  {len(out)} сотрудников")
        return out

    def _seed_managers(self, departments, positions, employees) -> int:
        self.stdout.write("Руководители отделов...")
        count = 0
        by_position = {}
        for employee in employees.values():
            by_position.setdefault(employee.position.title, employee)

        for dept_path, position_title in MANAGERS.items():
            manager = by_position.get(position_title)
            dept = departments.get(dept_path)
            if manager is None or dept is None:
                continue
            dept.manager = manager
            dept.save(update_fields=["manager", "updated_at"])
            count += 1
        self.stdout.write(f"  {count} назначено")
        return count
