"""Демо-данные домена задач — вся пятиуровневая иерархия целиком.

Проект → площадка → блок → роудмап → задача, и поверх неё то, ради чего
иерархия заводилась: плановые объёмы на блоке, потребность в людях и технике
на пакете работ, именные назначения и **ежедневные отчёты с датой выполнения
работ**. Без отчётов план/факт нечем наполнить — прогноз, SPI и S-кривая
считаются от них, а не от ``progress_percent``.

Сотрудников и отделы команда НЕ создаёт: берёт уже засеянных через
``apps.hr.interface`` (прямой импорт моделей hr запрещён,
apps/core/tests/test_app_isolation.py). Если у сотрудников нет платформенных
учёток, задачи останутся без исполнителей — в домене задач исполнитель,
владелец проекта и автор отчёта это ``user_id``, а не PK строки ``Employee``.
Команда об этом предупредит и подскажет ``manage.py seed_employee_accounts``.

Три режима очистки, и разница между ними существенная:

* ``--purge`` / ``--purge-only`` — снести **только своё**, по именам из
  таблиц ниже. Чужие объекты и задачи переживают.
* ``--wipe`` — снести **весь домен**, TRUNCATE по всем таблицам аппки
  ``tasks``. Это то, что нужно, когда база накопила данные нескольких
  поколений схемы и «поправить» их дешевле, чем начать заново.

Идемпотентность: справочники — ``update_or_create`` по естественным ключам,
задачи опознаются по ``summary`` (ключ им выдаёт общий счётчик, сравнивать
иначе не с чем), отчёты — по тройке (задача, дата работ, вид работ). Тройка
это конвенция НАПОЛНЕНИЯ, а не инвариант модели: ``DailyReport`` намеренно
разрешает несколько отчётов за день (смены, бригадиры), и уникального
индекса на ней нет.

Цифры подобраны так, чтобы план/факт было на что смотреть: один роудмап идёт
с опережением, один в пределах нормы, один ниже критического порога SPI и
один встал совсем (последний отчёт полтора месяца назад — прогноз финиша
``None``, а не «успеем»). Один отчёт исправлен задним числом, иначе ленту
версий проверить глазами не на чем.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from importlib import import_module

from django.apps import apps as django_apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.models import Q

from apps.hr import interface as hr_interface
from apps.tasks.models import (
    BlockStatus,
    Contractor,
    ContractorEngagement,
    ContractorLevel,
    ContractorStatus,
    ContractorWorker,
    DailyReport,
    Equipment,
    EquipmentCategory,
    EquipmentOwnership,
    Priority,
    Project,
    ProjectSite,
    ProjectStaffReport,
    ProjectStatus,
    ResourceAllocation,
    ResourceKind,
    ResourceRequirement,
    Roadmap,
    RoadmapStatus,
    Site,
    SiteBlock,
    SiteBlockVolume,
    SiteStatus,
    Status,
    Task,
    TaskType,
    TaskVolume,
    WorkRole,
    WorkVolumeType,
    WorkVolumeUnit,
)
from apps.tasks.services import daily_report_service
from apps.tasks.services import staff_report_service
from apps.tasks.services.reference_service import generate_unique_slug
from apps.tasks.services.sequence_service import next_task_key

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "db", "::1", ""}

# Пять системных типов задач ставит миграция 0002, а ``--wipe`` их сносит:
# TRUNCATE не различает, кто строку положил. Миграции повторно не
# прогоняются, поэтому список берётся оттуда же и восстанавливается руками —
# копия здесь разошлась бы с миграцией при первой правке.
SYSTEM_TASK_TYPES = import_module(
    "apps.tasks.migrations.0002_seed_system_task_types").SEED_TYPES

TODAY = date.today()


def _d(offset: int) -> date:
    return TODAY + timedelta(days=offset)


# ── справочники ────────────────────────────────────────────────────────────

SITES = [
    {"name": "Алга", "code": "ALG", "region": "Актюбинская область",
     "address": "г. Алга, промзона", "color": "#0ea5e9",
     "status": SiteStatus.ACTIVE,
     "description": "Строительство подстанции 110/10 кВ"},
    {"name": "Сазаган", "code": "SZG", "region": "Туркестанская область",
     "address": "с. Сазаган", "color": "#22c55e",
     "status": SiteStatus.ACTIVE,
     "description": "Солнечная электростанция, вторая очередь"},
    {"name": "Кандыагаш", "code": "KND", "region": "Актюбинская область",
     "address": "г. Кандыагаш", "color": "#f59e0b",
     "status": SiteStatus.SUSPENDED,
     "description": "Реконструкция ЛЭП, работы приостановлены до весны"},
    {"name": "Жанаозен", "code": "JNZ", "region": "Мангистауская область",
     "address": "г. Жанаозен", "color": "#a855f7",
     "status": SiteStatus.CLOSED,
     "description": "Модернизация РП-3, объект сдан"},
]

# Блоки — физическое деление площадки, по которому реально ведут работы.
# (объект, имя, код, порядок, статус, старт, финиш)
BLOCKS = [
    ("Алга", "Блок А — ОРУ 110 кВ", "A", 1, BlockStatus.ACTIVE, -50, 20),
    ("Алга", "Блок Б — ЗРУ 10 кВ", "B", 2, BlockStatus.ACTIVE, -12, 60),
    ("Сазаган", "Блок I", "I", 1, BlockStatus.ACTIVE, -30, 35),
    ("Сазаган", "Блок II", "II", 2, BlockStatus.PLANNED, 5, 90),
    ("Сазаган", "Блок III", "III", 3, BlockStatus.PLANNED, 60, 150),
    ("Кандыагаш", "Участок 12–19", "12-19", 1, BlockStatus.SUSPENDED, -85, 35),
    ("Жанаозен", "РП-3", "RP3", 1, BlockStatus.DONE, -60, -40),
]

# Виды объёмов работ. Единица принадлежит ВИДУ, а не строке объёма: валы
# считают штуками всегда, иначе сложить их между блоками было бы нельзя.
VOLUME_TYPES = [
    ("Валы трекерных конструкций", WorkVolumeUnit.PIECE),
    ("Трекерные конструкции", WorkVolumeUnit.PIECE),
    ("Фотомодули", WorkVolumeUnit.PIECE),
    ("Фундаменты", WorkVolumeUnit.PIECE),
    ("Металлоконструкции", WorkVolumeUnit.TON),
    ("Кабель 10 кВ", WorkVolumeUnit.METER),
    ("Опоры ЛЭП", WorkVolumeUnit.PIECE),
]

# Роли в потребности. Не hr.Position: планируемая роль на объекте («нужен
# стропальщик») и штатная должность в кадрах совпадают не всегда.
WORK_ROLES = [
    "Монтажник", "Стропальщик", "Водитель погрузчика", "Электромонтажник",
    "Геодезист", "Сварщик", "Прораб",
]

# Плановые объёмы на блоках: (объект, блок, вид работ, количество).
BLOCK_VOLUMES = [
    ("Сазаган", "Блок I", "Валы трекерных конструкций", 250),
    ("Сазаган", "Блок I", "Трекерные конструкции", 120),
    ("Сазаган", "Блок I", "Фотомодули", 3000),
    ("Сазаган", "Блок II", "Валы трекерных конструкций", 250),
    ("Сазаган", "Блок III", "Валы трекерных конструкций", 300),
    ("Алга", "Блок А — ОРУ 110 кВ", "Фундаменты", 24),
    ("Алга", "Блок А — ОРУ 110 кВ", "Металлоконструкции", 86),
    ("Алга", "Блок Б — ЗРУ 10 кВ", "Кабель 10 кВ", 1800),
    ("Кандыагаш", "Участок 12–19", "Опоры ЛЭП", 34),
    ("Жанаозен", "РП-3", "Кабель 10 кВ", 400),
]

PROJECTS = [
    {"name": "Алга-2026: подстанция 110/10",
     "description": "Строительство и ввод подстанции на объекте Алга.",
     "status": ProjectStatus.ACTIVE, "color": "#2563eb",
     "department_path": "stroy",
     "sites": ["Алга"], "primary": "Алга",
     "start": _d(-60), "end": _d(120),
     # Стройка идёт 7/7 — календарные дни. Флаг ниже включён ровно у одного
     # проекта, чтобы обе меры длительности были видны рядом.
     "production_calendar": False},
    {"name": "Сазаган: СЭС, вторая очередь",
     "description": "Монтаж второй очереди солнечной электростанции.",
     "status": ProjectStatus.ACTIVE, "color": "#16a34a",
     "department_path": "stroy.elektro",
     "sites": ["Сазаган"], "primary": "Сазаган",
     "start": _d(-30), "end": _d(180),
     "production_calendar": False},
    {"name": "Западный контур: ЛЭП и РП",
     "description": "Сквозной проект по двум объектам западного контура.",
     "status": ProjectStatus.ACTIVE, "color": "#f97316",
     "department_path": "proekt",
     "sites": ["Кандыагаш", "Жанаозен"], "primary": "Кандыагаш",
     "start": _d(-120), "end": _d(60),
     # Проектный, а не монтажный: бюро действительно работает по
     # производственному календарю.
     "production_calendar": True},
    {"name": "Жанаозен: РП-3 (завершён)",
     "description": "Модернизация распределительного пункта. Объект сдан.",
     "status": ProjectStatus.COMPLETED, "color": "#64748b",
     "department_path": "stroy",
     "sites": ["Жанаозен"], "primary": "Жанаозен",
     "start": _d(-300), "end": _d(-40),
     "production_calendar": False},
]

# Роудмапы — пакеты работ на блоке. Ключ уникальности (проект, блок, имя),
# поэтому «Развозка валов» законно живёт и на блоке I, и на блоке II.
#
# (проект, объект, блок, имя, статус, старт, финиш, план рабочих дней,
#  потребности, именная техника)
ROADMAPS = [
    {"project": "Сазаган: СЭС, вторая очередь", "site": "Сазаган",
     "block": "Блок I", "name": "Развозка валов трекерных конструкций",
     "status": RoadmapStatus.ACTIVE, "color": "#22c55e", "order": 1,
     "start": -25, "end": 3, "working_days": 28,
     # Ровно план с доски: 4 недели, 2 человека, 2 кары.
     "requirements": [("human", "Монтажник", 2, "Бригада развозки"),
                      ("equipment", "Кара (вилопогрузчик)", 2, None)],
     "equipment": ["INV-0103", "INV-0104"]},
    {"project": "Сазаган: СЭС, вторая очередь", "site": "Сазаган",
     "block": "Блок I", "name": "Монтаж трекерных конструкций",
     "status": RoadmapStatus.ACTIVE, "color": "#0ea5e9", "order": 2,
     "start": 4, "end": 32, "working_days": 28,
     "requirements": [("human", "Монтажник", 4, None),
                      ("human", "Стропальщик", 1, None),
                      ("equipment", "Автокран", 1, None)],
     "equipment": []},
    {"project": "Сазаган: СЭС, вторая очередь", "site": "Сазаган",
     "block": "Блок II", "name": "Развозка валов трекерных конструкций",
     "status": RoadmapStatus.ACTIVE, "color": "#22c55e", "order": 3,
     "start": 5, "end": 33, "working_days": 28,
     "requirements": [("human", "Монтажник", 2, None),
                      ("equipment", "Кара (вилопогрузчик)", 2, None)],
     "equipment": []},
    {"project": "Алга-2026: подстанция 110/10", "site": "Алга",
     "block": "Блок А — ОРУ 110 кВ", "name": "Фундаменты под трансформаторы",
     "status": RoadmapStatus.COMPLETED, "color": "#64748b", "order": 1,
     "start": -47, "end": -20, "working_days": 20,
     "requirements": [("human", "Монтажник", 3, None),
                      ("equipment", "Экскаватор", 1, None)],
     "equipment": ["INV-0102"]},
    {"project": "Алга-2026: подстанция 110/10", "site": "Алга",
     "block": "Блок А — ОРУ 110 кВ", "name": "Монтаж металлоконструкций ОРУ",
     "status": RoadmapStatus.ACTIVE, "color": "#2563eb", "order": 2,
     "start": -19, "end": 15, "working_days": 25,
     "requirements": [("human", "Монтажник", 4, None),
                      ("human", "Сварщик", 2, None),
                      ("equipment", "Автокран", 1, None)],
     "equipment": ["INV-0101", "INV-0107"]},
    {"project": "Алга-2026: подстанция 110/10", "site": "Алга",
     "block": "Блок Б — ЗРУ 10 кВ", "name": "Кабельные линии 10 кВ",
     "status": RoadmapStatus.ACTIVE, "color": "#8b5cf6", "order": 3,
     "start": -10, "end": 25, "working_days": 26,
     "requirements": [("human", "Электромонтажник", 3, None),
                      ("equipment", "Автовышка", 1, None)],
     "equipment": ["SUB-0031"]},
    {"project": "Западный контур: ЛЭП и РП", "site": "Кандыагаш",
     "block": "Участок 12–19", "name": "Замена опор на участке 12–19",
     "status": RoadmapStatus.ACTIVE, "color": "#f97316", "order": 1,
     "start": -80, "end": 30, "working_days": 78,
     "requirements": [("human", "Монтажник", 4, None),
                      ("equipment", "Автокран", 1, None),
                      ("equipment", "Самосвал", 2, None)],
     "equipment": ["INV-0105"]},
    {"project": "Жанаозен: РП-3 (завершён)", "site": "Жанаозен",
     "block": "РП-3", "name": "Модернизация РП-3",
     "status": RoadmapStatus.COMPLETED, "color": "#64748b", "order": 1,
     "start": -60, "end": -40, "working_days": 15,
     "requirements": [("human", "Электромонтажник", 2, None)],
     "equipment": []},
]

CONTRACTORS = [
    {"name": "ТОО «Алга-Строй-Монтаж»", "short_name": "Алга-СМ",
     "bin_iin": "180340012345", "contact_person": "Ерлан Сериков",
     "phone": "+7 (701) 234-56-78", "email": "info@alga-sm.kz",
     "address": "г. Актобе, ул. Промышленная, 14",
     "status": ContractorStatus.ACTIVE,
     "notes": "Общестроительные работы, монтаж металлоконструкций.",
     "workers": [
         ("Тулегенов", "Марат", "Прораб", ContractorLevel.SENIOR),
         ("Сарсенов", "Данияр", "Бригадир монтажников", ContractorLevel.MIDDLE),
         ("Абенов", "Нурлан", "Монтажник", ContractorLevel.JUNIOR),
         ("Каиров", "Аскар", "Сварщик", ContractorLevel.JUNIOR),
     ]},
    {"name": "ТОО «ЭлектроМонтажСервис»", "short_name": "ЭМС",
     "bin_iin": "150240054321", "contact_person": "Виктор Ким",
     "phone": "+7 (702) 345-67-89", "email": "office@ems.kz",
     "address": "г. Шымкент, пр. Тауке хана, 5",
     "status": ContractorStatus.ACTIVE,
     "notes": "Электромонтаж, пусконаладка, кабельные линии.",
     "workers": [
         ("Ахметов", "Серик", "Главный энергетик", ContractorLevel.SENIOR),
         ("Мукашев", "Тимур", "Электромонтажник", ContractorLevel.MIDDLE),
         ("Жапаров", "Азамат", "Электромонтажник", ContractorLevel.JUNIOR),
     ]},
    {"name": "ИП «ГеоЛайн»", "short_name": "ГеоЛайн",
     "bin_iin": "910712300123", "contact_person": "Алия Нурпеисова",
     "phone": "+7 (705) 456-78-90", "email": "geoline.kz@mail.kz",
     "address": "г. Актобе, ул. Абая, 42",
     "status": ContractorStatus.ACTIVE,
     "notes": "Геодезия, разбивочные работы, исполнительные съёмки.",
     "workers": [
         ("Нурпеисова", "Алия", "Ведущий геодезист", ContractorLevel.SENIOR),
         ("Оспанов", "Ержан", "Геодезист", ContractorLevel.MIDDLE),
     ]},
    {"name": "ТОО «АвтоТрансЛогистик»", "short_name": "АТЛ",
     "bin_iin": "200140098765", "contact_person": "Руслан Досов",
     "phone": "+7 (708) 567-89-01", "email": "atl@transport.kz",
     "address": "г. Актау, промзона 3",
     "status": ContractorStatus.SUSPENDED,
     "notes": "Спецтехника и перевозки. Сотрудничество приостановлено "
              "до продления допусков.",
     "workers": [
         ("Досов", "Руслан", "Начальник колонны", ContractorLevel.SENIOR),
         ("Ищенко", "Павел", "Крановщик", ContractorLevel.MIDDLE),
     ]},
]

# (партнёр, проект, объект, номер договора, объём работ). Привлечение на
# площадке — это то, из чего задача без своего партнёра получает
# ЭФФЕКТИВНОГО (contractor_service.effective_contractors), поэтому Сазаган
# здесь обязателен: половина его задач партнёра не называет намеренно.
ENGAGEMENTS = [
    ("ТОО «Алга-Строй-Монтаж»", "Алга-2026: подстанция 110/10", "Алга",
     "ДП-2026/014", "Фундаменты, металлоконструкции, монтаж оборудования"),
    ("ТОО «ЭлектроМонтажСервис»", "Алга-2026: подстанция 110/10", "Алга",
     "ДП-2026/019", "Электромонтаж и пусконаладка"),
    ("ТОО «ЭлектроМонтажСервис»", "Сазаган: СЭС, вторая очередь", "Сазаган",
     "ДП-2026/021", "Монтаж инверторов, развозка и монтаж конструкций"),
    ("ИП «ГеоЛайн»", None, "Алга",
     "ДП-2026/007", "Геодезическое сопровождение по объекту"),
    ("ТОО «АвтоТрансЛогистик»", "Западный контур: ЛЭП и РП", "Кандыагаш",
     "ДП-2025/112", "Спецтехника и перевозки"),
]

EQUIPMENT = [
    ("Кран автомобильный КС-45717", "INV-0101", "Автокран",
     EquipmentOwnership.OWN, None),
    ("Экскаватор Hitachi ZX200", "INV-0102", "Экскаватор",
     EquipmentOwnership.OWN, None),
    # Две кары — ровно та пара, что стоит в плане роудмапа развозки валов.
    ("Вилопогрузчик Toyota 8FG25", "INV-0103", "Кара (вилопогрузчик)",
     EquipmentOwnership.OWN, None),
    ("Вилопогрузчик Komatsu FD25", "INV-0104", "Кара (вилопогрузчик)",
     EquipmentOwnership.OWN, None),
    ("Самосвал Shacman X3000", "INV-0105", "Самосвал",
     EquipmentOwnership.OWN, None),
    ("Сварочный аппарат Kemppi", "INV-0107", "Сварочное оборудование",
     EquipmentOwnership.OWN, None),
    ("Автовышка АГП-22", "SUB-0031", "Автовышка",
     EquipmentOwnership.CONTRACTOR, "ТОО «АвтоТрансЛогистик»"),
    ("Тахеометр Leica TS16", "SUB-0044", "Геодезическое оборудование",
     EquipmentOwnership.CONTRACTOR, "ИП «ГеоЛайн»"),
    ("Генератор дизельный 100 кВт", "RNT-0009", "Энергоснабжение",
     EquipmentOwnership.RENTED, None),
]

# Задачи. Проект, объект и блок у задачи с роудмапом НЕ дублируются — они
# берутся из него, как это делает roadmap_service.resolve_task_roadmap. Так
# наполнение физически не может создать тройку, которую API отвергло бы.
#
# reports: (день работ относительно сегодня, вид работ или None, количество,
#           человек на смене, комментарий). None в виде работ — тот самый
#           случай, когда его подставляет resolve_volume_type.
TASKS = [
    # ── Алга: блок А, фундаменты (пакет закрыт) ────────────────────────────
    {"summary": "Устройство фундаментов под трансформаторы",
     "roadmap": ("Алга-2026: подстанция 110/10", "Блок А — ОРУ 110 кВ",
                 "Фундаменты под трансформаторы"),
     "status": Status.DONE, "priority": Priority.CRITICAL, "progress": 100,
     "contractor": "ТОО «Алга-Строй-Монтаж»", "worker": "Тулегенов",
     "start": -47, "due": -20,
     "volumes": [("Фундаменты", 24)],
     "reports": [(-45, None, 4, 6, "Первый куст"),
                 (-38, None, 6, 6, ""),
                 (-31, None, 8, 8, ""),
                 (-23, None, 6, 6, "Закрыли пакет")]},

    # ── Алга: блок А, металлоконструкции (идёт с опережением) ──────────────
    {"summary": "Монтаж металлоконструкций ОРУ",
     "roadmap": ("Алга-2026: подстанция 110/10", "Блок А — ОРУ 110 кВ",
                 "Монтаж металлоконструкций ОРУ"),
     "status": Status.IN_PROGRESS, "priority": Priority.CRITICAL,
     "progress": 70,
     "contractor": "ТОО «Алга-Строй-Монтаж»", "worker": "Сарсенов",
     "start": -19, "due": 15,
     "volumes": [("Металлоконструкции", 86)],
     "reports": [(-17, None, 8, 6, ""), (-14, None, 10, 6, ""),
                 (-11, None, 9, 6, ""), (-8, None, 11, 8, ""),
                 (-5, None, 10, 8, ""), (-2, None, 12, 8, "Идём с запасом")]},

    # ── Алга: блок Б, кабель (в пределах нормы) ────────────────────────────
    {"summary": "Прокладка кабельных линий 10 кВ",
     "roadmap": ("Алга-2026: подстанция 110/10", "Блок Б — ЗРУ 10 кВ",
                 "Кабельные линии 10 кВ"),
     "status": Status.IN_PROGRESS, "priority": Priority.HIGH, "progress": 28,
     "contractor": "ТОО «ЭлектроМонтажСервис»", "worker": "Мукашев",
     "start": -10, "due": 25,
     "volumes": [("Кабель 10 кВ", 1800)],
     "reports": [(-9, None, 90, 3, ""), (-7, None, 120, 3, ""),
                 (-4, None, 140, 4, ""), (-1, None, 150, 4, "")]},

    # ── Алга: задачи вне роудмапа ──────────────────────────────────────────
    {"summary": "Разбивка осей и вынос в натуру",
     "type": "story",
     "project": "Алга-2026: подстанция 110/10", "site": "Алга",
     "block": "Блок А — ОРУ 110 кВ",
     "status": Status.DONE, "priority": Priority.HIGH, "progress": 100,
     "contractor": "ИП «ГеоЛайн»", "worker": "Оспанов",
     "start": -55, "due": -48},
    {"summary": "Согласование схемы РЗА с заказчиком",
     "type": "story",
     "project": "Алга-2026: подстанция 110/10", "site": "Алга",
     "status": Status.IN_REVIEW, "priority": Priority.HIGH, "progress": 90,
     "start": -8, "due": 5},
    {"summary": "Поставка ячеек КРУ",
     "project": "Алга-2026: подстанция 110/10", "site": "Алга",
     "status": Status.BLOCKED, "priority": Priority.CRITICAL, "progress": 20,
     "start": -30, "due": 10},
    {"summary": "Пусконаладочные работы",
     "project": "Алга-2026: подстанция 110/10", "site": "Алга",
     "status": Status.TODO, "priority": Priority.HIGH, "progress": 0,
     "contractor": "ТОО «ЭлектроМонтажСервис»", "worker": "Ахметов",
     "start": 20, "due": 60},
    {"summary": "Приёмо-сдаточные испытания",
     "type": "story",
     "project": "Алга-2026: подстанция 110/10", "site": "Алга",
     "status": Status.BACKLOG, "priority": Priority.MEDIUM, "progress": 0,
     "start": 60, "due": 95},

    # ── Сазаган: блок I, развозка валов ────────────────────────────────────
    # Четыре порции по рядам, в сумме ровно 250 валов планового объёма
    # блока. Пакет отстаёт: SPI ниже критического порога, прогноз финиша
    # выходит за плановую дату — то, ради чего дашборд и делался.
    {"summary": "Развезти валы: ряды 1–8",
     "roadmap": ("Сазаган: СЭС, вторая очередь", "Блок I",
                 "Развозка валов трекерных конструкций"),
     "status": Status.DONE, "priority": Priority.HIGH, "progress": 100,
     "contractor": "ТОО «ЭлектроМонтажСервис»", "worker": "Жапаров",
     "start": -25, "due": -22,
     "volumes": [("Валы трекерных конструкций", 70)],
     "reports": [(-25, None, 24, 2, "Заезд, разметка рядов"),
                 (-24, None, 26, 2, ""),
                 (-23, None, 20, 2, "")],
     "requirements": [("human", "Монтажник", 1),
                      ("equipment", "Кара (вилопогрузчик)", 1)],
     "equipment": ["INV-0103"]},
    {"summary": "Развезти валы: ряды 9–16",
     "roadmap": ("Сазаган: СЭС, вторая очередь", "Блок I",
                 "Развозка валов трекерных конструкций"),
     "status": Status.DONE, "priority": Priority.HIGH, "progress": 100,
     "contractor": "ТОО «ЭлектроМонтажСервис»", "worker": "Жапаров",
     "start": -21, "due": -18,
     "volumes": [("Валы трекерных конструкций", 60)],
     "reports": [(-21, None, 22, 2, ""), (-20, None, 18, 2, ""),
                 (-19, None, 20, 2, "")],
     "requirements": [("human", "Монтажник", 1),
                      ("equipment", "Кара (вилопогрузчик)", 1)],
     "equipment": ["INV-0103"]},
    # Партнёра намеренно НЕ называют: он должен подтянуться привлечением
    # на площадке (эффективный партнёр).
    {"summary": "Развезти валы: ряды 17–24",
     "roadmap": ("Сазаган: СЭС, вторая очередь", "Блок I",
                 "Развозка валов трекерных конструкций"),
     "status": Status.IN_PROGRESS, "priority": Priority.HIGH, "progress": 80,
     "start": -14, "due": -10,
     "volumes": [("Валы трекерных конструкций", 60)],
     "reports": [(-13, None, 18, 2, ""), (-12, None, 16, 2, ""),
                 (-10, None, 20, 2, "")],
     "requirements": [("human", "Монтажник", 1),
                      ("equipment", "Кара (вилопогрузчик)", 1)],
     "equipment": ["INV-0104"]},
    {"summary": "Развезти валы: ряды 25–32",
     "roadmap": ("Сазаган: СЭС, вторая очередь", "Блок I",
                 "Развозка валов трекерных конструкций"),
     "status": Status.IN_PROGRESS, "priority": Priority.HIGH, "progress": 37,
     "start": -6, "due": 3,
     "volumes": [("Валы трекерных конструкций", 60)],
     "reports": [(-5, None, 12, 1, "Одна кара в ремонте"),
                 (-3, None, 10, 1, "")],
     "requirements": [("human", "Монтажник", 1),
                      ("equipment", "Кара (вилопогрузчик)", 1)],
     "equipment": ["INV-0104"]},

    # ── Сазаган: блок I, монтаж конструкций (ещё не начинался) ─────────────
    {"summary": "Смонтировать трекерные конструкции: ряды 1–16",
     "roadmap": ("Сазаган: СЭС, вторая очередь", "Блок I",
                 "Монтаж трекерных конструкций"),
     "status": Status.TODO, "priority": Priority.HIGH, "progress": 0,
     "start": 4, "due": 18,
     "volumes": [("Трекерные конструкции", 60)]},
    {"summary": "Смонтировать трекерные конструкции: ряды 17–32",
     "roadmap": ("Сазаган: СЭС, вторая очередь", "Блок I",
                 "Монтаж трекерных конструкций"),
     "status": Status.BACKLOG, "priority": Priority.MEDIUM, "progress": 0,
     "start": 19, "due": 32,
     "volumes": [("Трекерные конструкции", 60)]},

    # ── Сазаган: блок II ───────────────────────────────────────────────────
    {"summary": "Развезти 250 валов на блок II",
     "roadmap": ("Сазаган: СЭС, вторая очередь", "Блок II",
                 "Развозка валов трекерных конструкций"),
     "status": Status.TODO, "priority": Priority.MEDIUM, "progress": 0,
     "start": 5, "due": 33,
     "volumes": [("Валы трекерных конструкций", 250)]},

    # ── Сазаган: вне роудмапа ──────────────────────────────────────────────
    {"summary": "Расчёт потерь и выработки",
     "type": "story",
     "project": "Сазаган: СЭС, вторая очередь", "site": "Сазаган",
     "status": Status.IN_REVIEW, "priority": Priority.MEDIUM, "progress": 80,
     "start": -12, "due": 3},
    {"summary": "Ограждение периметра",
     "project": "Сазаган: СЭС, вторая очередь", "site": "Сазаган",
     "status": Status.BACKLOG, "priority": Priority.LOW, "progress": 0,
     "start": 40, "due": 75},

    # ── Кандыагаш: работы встали ───────────────────────────────────────────
    # Последний отчёт полтора месяца назад. Темп за последнее окно нулевой,
    # значит forecast_end = None, а не выдуманная дата.
    {"summary": "Замена опор на участке 12–19",
     "roadmap": ("Западный контур: ЛЭП и РП", "Участок 12–19",
                 "Замена опор на участке 12–19"),
     "status": Status.BLOCKED, "priority": Priority.HIGH, "progress": 26,
     "contractor": "ТОО «АвтоТрансЛогистик»", "worker": "Ищенко",
     "start": -80, "due": 30,
     "volumes": [("Опоры ЛЭП", 34)],
     "reports": [(-75, None, 3, 5, ""), (-60, None, 4, 5, ""),
                 (-42, None, 2, 4, "Дальше без техники не идём")]},
    {"summary": "Обследование трассы ЛЭП",
     "type": "story",
     "project": "Западный контур: ЛЭП и РП", "site": "Кандыагаш",
     "status": Status.DONE, "priority": Priority.MEDIUM, "progress": 100,
     "contractor": "ИП «ГеоЛайн»", "worker": "Нурпеисова",
     "start": -110, "due": -90},
    {"summary": "Проект производства работ",
     "type": "story",
     "project": "Западный контур: ЛЭП и РП", "site": "Кандыагаш",
     "status": Status.IN_PROGRESS, "priority": Priority.MEDIUM,
     "progress": 45, "start": -40, "due": 20},
    {"summary": "Перенос сроков по зимнему периоду",
     "type": "story",
     "project": "Западный контур: ЛЭП и РП",
     "status": Status.CANCELLED, "priority": Priority.LOW, "progress": 0,
     "start": -70, "due": -50},

    # ── Жанаозен: объект сдан ──────────────────────────────────────────────
    {"summary": "Сдача РП-3 заказчику",
     "roadmap": ("Жанаозен: РП-3 (завершён)", "РП-3", "Модернизация РП-3"),
     "status": Status.DONE, "priority": Priority.CRITICAL, "progress": 100,
     "start": -60, "due": -40,
     "volumes": [("Кабель 10 кВ", 400)],
     "reports": [(-58, None, 120, 4, ""), (-52, None, 140, 4, ""),
                 (-45, None, 140, 4, "Сдали")]},
    {"summary": "Исполнительная документация РП-3",
     "type": "story",
     "project": "Жанаозен: РП-3 (завершён)", "site": "Жанаозен",
     "status": Status.DONE, "priority": Priority.MEDIUM, "progress": 100,
     "contractor": "ИП «ГеоЛайн»", "worker": "Нурпеисова",
     "start": -55, "due": -42},

    # ── Вне проекта: «Без проекта» это полноценная корзина ─────────────────
    {"summary": "Ревизия склада инструмента",
     "type": "story",
     "status": Status.TODO, "priority": Priority.LOW, "progress": 0,
     "start": 2, "due": 12},
    {"summary": "Обновление реестра допусков",
     "type": "story",
     "status": Status.IN_PROGRESS, "priority": Priority.MEDIUM,
     "progress": 30, "start": -5, "due": 14},
]

# Правки отчётов: (задача, день работ, новое количество, комментарий).
# Без хотя бы одной ленту версий не на чем посмотреть, а ради неё
# DailyReportRevision и заведена.
REPORT_EDITS = [
    ("Развезти валы: ряды 17–24", -10, 14,
     "Пересчёт по факту приёмки: 6 валов забракованы"),
]

# ── отчёты по персоналу ────────────────────────────────────────────────────
#
# Вторая ось факта: ежедневка выше отвечает «сколько сделано», эта — «какими
# силами». Дни здесь НЕ повторяются в пределах блока, и это инвариант модели,
# а не конвенция наполнения: у ``ProjectStaffReport`` есть
# UNIQUE(проект, блок, дата), потому что численность — состояние, а не сумма
# смен.
#
# Числа подобраны так, чтобы на доске было что сравнивать с планом
# (``ResourceRequirement`` роудмапов выше):
#   Блок А — ОРУ 110 кВ  план 6 (4 монтажника + 2 сварщика) → факт около 7,
#                        прораб идёт сверх плана: его в потребностях нет;
#   Блок Б — ЗРУ 10 кВ   план 3 электромонтажника          → факт скачет 2–4;
#   Блок I (Сазаган)     план 2 монтажника                 → факт 2–4;
#   Участок 12–19        план 4 монтажника, но работы встали три недели
#                        назад → на сегодня «не заполнено» и провал против
#                        плана. Ради этой строки блок и заведён SUSPENDED.
#
# Дни -4..0 — это Пн–Пт текущей недели, -8 и -7 — Чт и Пт прошлой.
STAFF_REPORTS = [
    {"project": "Алга-2026: подстанция 110/10", "site": "Алга",
     "block": "Блок А — ОРУ 110 кВ", "days": [
         (0, "", (("Монтажник", 4), ("Сварщик", 2), ("Прораб", 1))),
         (-1, "", (("Монтажник", 4), ("Сварщик", 2), ("Прораб", 1))),
         (-2, "", (("Монтажник", 4), ("Сварщик", 2), ("Прораб", 1))),
         (-3, "", (("Монтажник", 4), ("Сварщик", 2))),
         (-4, "Сварщик со второй смены переведён на Блок Б",
          (("Монтажник", 4), ("Сварщик", 1), ("Прораб", 1))),
         (-7, "", (("Монтажник", 4), ("Сварщик", 2), ("Прораб", 1))),
     ]},
    {"project": "Алга-2026: подстанция 110/10", "site": "Алга",
     "block": "Блок Б — ЗРУ 10 кВ", "days": [
         (0, "", (("Электромонтажник", 3),)),
         (-1, "Один электромонтажник на переаттестации по ПТБ",
          (("Электромонтажник", 2),)),
         (-2, "", (("Электромонтажник", 3),)),
         (-3, "Стропальщик на разгрузку барабанов с кабелем",
          (("Электромонтажник", 3), ("Стропальщик", 1))),
         (-4, "", (("Электромонтажник", 2),)),
     ]},
    {"project": "Сазаган: СЭС, вторая очередь", "site": "Сазаган",
     "block": "Блок I", "days": [
         (0, "", (("Монтажник", 2), ("Водитель погрузчика", 1))),
         (-1, "", (("Монтажник", 2), ("Водитель погрузчика", 1))),
         (-2, "", (("Монтажник", 2), ("Водитель погрузчика", 1))),
         (-3, "Кара на ТО, развозили вручную", (("Монтажник", 2),)),
         (-4, "Подтянули людей с Блока II под завершение развозки",
          (("Монтажник", 3), ("Водитель погрузчика", 1))),
     ]},
    {"project": "Западный контур: ЛЭП и РП", "site": "Кандыагаш",
     "block": "Участок 12–19", "days": [
         (-21, "Последний выход перед приостановкой работ",
          (("Монтажник", 4), ("Прораб", 1))),
         (-22, "", (("Монтажник", 4),)),
     ]},
]

# Правка отчёта по персоналу: (объект, блок, день, новый состав, комментарий).
# Ровно та же причина, что у REPORT_EDITS: без хотя бы одной правки ленту
# версий не на чем посмотреть, а ради неё ProjectStaffReportRevision и
# заведена. День -2 в спеке выше намеренно засеян четырьмя монтажниками —
# иначе правка совпала бы с исходным составом, и сервис (справедливо) не
# создал бы вторую версию.
STAFF_REPORT_EDITS = [
    ("Алга", "Блок А — ОРУ 110 кВ", -2,
     (("Монтажник", 3), ("Сварщик", 2), ("Прораб", 1)),
     "Уточнено по табелю: один монтажник ушёл на больничный с обеда"),
]


class Command(BaseCommand):
    help = (
        "Наполнить домен задач демо-данными: объекты, блоки, проекты, "
        "роудмапы, партнёров, технику, задачи с объёмами и "
        "ежедневными отчётами, а также ежедневные отчёты по персоналу "
        "проекта. Только для локальной среды."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--purge", action="store_true",
                            help="Снести засеянное перед наполнением.")
        parser.add_argument("--purge-only", action="store_true",
                            help="Только снести засеянное, не наполнять.")
        parser.add_argument("--wipe", action="store_true",
                            help="TRUNCATE всех таблиц домена задач перед "
                                 "наполнением — сносит и чужие строки.")
        parser.add_argument("--wipe-only", action="store_true",
                            help="Только полная очистка домена.")
        parser.add_argument("--force-remote", action="store_true",
                            help="Осознанно разрешить неместную БД.")

    # ── защита ─────────────────────────────────────────────────────────────

    def _assert_local(self, force: bool, host: str | None = None) -> None:
        """Отказ работать против чего-либо, кроме локальной базы.

        ``host`` передаётся только из тестов: иначе проверить правило можно
        было бы лишь подставив боевой адрес в живые настройки.
        """
        if host is None:
            host = str(settings.DATABASES["default"].get("HOST", ""))
        if host in _LOCAL_HOSTS or force:
            self.stdout.write(f"  БД: {host or '(по умолчанию)'}")
            return
        raise CommandError(
            f"DB_HOST={host!r} не похож на локальную БД. Команда наполняет "
            f"домен задач демо-данными и предназначена только для локальной "
            f"среды. Если это осознанно — --force-remote."
        )

    # ── справочники ────────────────────────────────────────────────────────

    def _seed_reference(self, model, names) -> dict:
        """Справочная строка по имени со свободным слагом.

        Один метод на три справочника: у ``WorkRole``, ``WorkVolumeType`` и
        ``EquipmentCategory`` одинаковая пара (slug, name), и три копии
        разошлись бы при первой же правке. ``names`` — либо имена, либо пары
        (имя, единица) для видов объёмов.
        """
        out = {}
        for entry in names:
            name, extra = entry if isinstance(entry, tuple) else (entry, None)
            defaults = {"is_active": True}
            if extra is not None:
                defaults["unit"] = extra
            row = model.objects.filter(name=name).first()
            if row is None:
                row = model.objects.create(
                    name=name, slug=generate_unique_slug(name, model),
                    **defaults)
            else:
                for field, value in defaults.items():
                    setattr(row, field, value)
                row.save()
            out[name] = row
        return out

    def _seed_sites(self) -> dict[str, Site]:
        out = {}
        for spec in SITES:
            site, _ = Site.objects.update_or_create(
                name=spec["name"],
                defaults={k: v for k, v in spec.items() if k != "name"},
            )
            out[site.name] = site
        self.stdout.write(f"  объектов: {len(out)}")
        return out

    def _seed_blocks(self, sites) -> dict[tuple[str, str], SiteBlock]:
        out = {}
        for site_name, name, code, order, status, start, end in BLOCKS:
            block, _ = SiteBlock.objects.update_or_create(
                site=sites[site_name], name=name,
                defaults={"code": code, "order": order, "status": status,
                          "start_date": _d(start), "end_date": _d(end)},
            )
            out[(site_name, name)] = block
        self.stdout.write(f"  блоков: {len(out)}")
        return out

    def _seed_block_volumes(self, blocks, volume_types) -> int:
        for site_name, block_name, type_name, quantity in BLOCK_VOLUMES:
            SiteBlockVolume.objects.update_or_create(
                block=blocks[(site_name, block_name)],
                volume_type=volume_types[type_name],
                defaults={"planned_quantity": Decimal(quantity)},
            )
        self.stdout.write(f"  плановых объёмов на блоках: {len(BLOCK_VOLUMES)}")
        return len(BLOCK_VOLUMES)

    def _seed_projects(self, sites: dict[str, Site],
                       departments: dict[str, int],
                       owner_ids: list[int]) -> dict[str, Project]:
        out = {}
        for index, spec in enumerate(PROJECTS):
            project, _ = Project.objects.update_or_create(
                name=spec["name"],
                defaults={
                    "description": spec["description"],
                    "status": spec["status"],
                    "color": spec["color"],
                    "start_date": spec["start"],
                    "end_date": spec["end"],
                    "use_production_calendar": spec["production_calendar"],
                    "department_id": departments.get(spec["department_path"]),
                    # Владельцы раскладываются по кругу: так в отчётах «по
                    # владельцу» больше одной строки.
                    "owner_id": owner_ids[index % len(owner_ids)] if owner_ids else None,
                },
            )
            # Набор объектов задаётся целиком — тот же контракт, что у
            # site_service.set_project_sites.
            ProjectSite.objects.filter(project=project).exclude(
                site__name__in=spec["sites"]).delete()
            for site_name in spec["sites"]:
                ProjectSite.objects.update_or_create(
                    project=project, site=sites[site_name],
                    defaults={"is_primary": site_name == spec["primary"],
                              "start_date": spec["start"],
                              "end_date": spec["end"]},
                )
            out[project.name] = project
        self.stdout.write(f"  проектов: {len(out)}")
        return out

    def _seed_roadmaps(self, projects, blocks,
                       owner_ids) -> dict[tuple[str, str, str], Roadmap]:
        out = {}
        for index, spec in enumerate(ROADMAPS):
            project = projects[spec["project"]]
            block = blocks[(spec["site"], spec["block"])]
            roadmap, _ = Roadmap.objects.update_or_create(
                project=project, site_block=block, name=spec["name"],
                defaults={
                    "status": spec["status"],
                    "color": spec["color"],
                    "order": spec["order"],
                    "planned_start_date": _d(spec["start"]),
                    "planned_end_date": _d(spec["end"]),
                    "planned_working_days": spec["working_days"],
                    "department_id": project.department_id,
                    "owner_id": owner_ids[index % len(owner_ids)] if owner_ids else None,
                },
            )
            out[(spec["project"], spec["block"], spec["name"])] = roadmap
        self.stdout.write(f"  роудмапов: {len(out)}")
        return out

    def _seed_contractors(self) -> tuple[dict[str, Contractor], dict[str, ContractorWorker]]:
        orgs: dict[str, Contractor] = {}
        workers: dict[str, ContractorWorker] = {}
        for spec in CONTRACTORS:
            contractor, _ = Contractor.objects.update_or_create(
                name=spec["name"],
                defaults={k: v for k, v in spec.items()
                          if k not in ("name", "workers")},
            )
            orgs[contractor.name] = contractor
            for last, first, position, level in spec["workers"]:
                worker, _ = ContractorWorker.objects.update_or_create(
                    contractor=contractor, last_name=last, first_name=first,
                    defaults={"position_title": position, "level": level,
                              "is_active": True},
                )
                workers[last] = worker
        self.stdout.write(
            f"  партнёров: {len(orgs)}, их работников: {len(workers)}")
        return orgs, workers

    def _seed_engagements(self, orgs, projects, sites) -> int:
        count = 0
        for org_name, project_name, site_name, contract_no, scope in ENGAGEMENTS:
            ContractorEngagement.objects.update_or_create(
                contractor=orgs[org_name],
                project=projects.get(project_name) if project_name else None,
                site=sites.get(site_name) if site_name else None,
                defaults={"contract_no": contract_no, "scope": scope,
                          "start_date": _d(-90), "is_active": True},
            )
            count += 1
        self.stdout.write(f"  привлечений: {count}")
        return count

    def _seed_equipment(self, orgs, categories) -> int:
        for name, inv, category, ownership, owner_name in EQUIPMENT:
            Equipment.objects.update_or_create(
                name=name,
                defaults={
                    "inventory_no": inv,
                    "category": categories[category],
                    "ownership": ownership,
                    # CHECK ck_equipment_contractor_owner: организация
                    # обязательна ровно для ownership='contractor'.
                    "contractor": orgs.get(owner_name) if owner_name else None,
                    "is_active": True,
                },
            )
        self.stdout.write(f"  техники: {len(EQUIPMENT)}")
        return len(EQUIPMENT)

    # ── ресурсы: потребность количеством и именные назначения ──────────────

    def _seed_requirements(self, *, target, specs, roles, categories,
                           start: date | None, end: date | None) -> int:
        """Строки ``ResourceRequirement`` на роудмапе ИЛИ на задаче.

        ``target`` — уже созданный объект; какое из двух полей заполнять,
        решается его типом, потому что CHECK
        ``ck_requirement_exactly_one_target`` требует ровно одного.
        """
        anchor = ({"roadmap": target} if isinstance(target, Roadmap)
                  else {"task": target})
        for spec in specs:
            kind, name, quantity = spec[0], spec[1], spec[2]
            note = spec[3] if len(spec) > 3 else None
            human = kind == ResourceKind.HUMAN
            ResourceRequirement.objects.update_or_create(
                **anchor,
                kind=kind,
                work_role=roles[name] if human else None,
                equipment_category=None if human else categories[name],
                defaults={"quantity": quantity, "note": note,
                          "start_date": start, "end_date": end},
            )
        return len(specs)

    def _seed_allocations(self, *, target, inventory_nos, equipment_by_inv,
                          employee_ids) -> int:
        """Именные назначения: конкретные машины и конкретные люди.

        Потребность отвечает на «сколько нужно», назначение — на «кто
        именно»; связь между ними здесь не проставляется намеренно, чтобы в
        демо был и тот случай, когда факт заведён без плана.
        """
        anchor = ({"roadmap": target} if isinstance(target, Roadmap)
                  else {"task": target})
        count = 0
        for inv in inventory_nos:
            ResourceAllocation.objects.get_or_create(
                **anchor, equipment=equipment_by_inv[inv], employee_id=None,
                defaults={"allocation": 100},
            )
            count += 1
        for user_id in employee_ids:
            ResourceAllocation.objects.get_or_create(
                **anchor, employee_id=user_id, equipment=None,
                defaults={"allocation": 100},
            )
            count += 1
        return count

    # ── задачи, объёмы и отчёты ────────────────────────────────────────────

    def _seed_tasks(self, *, projects, sites, blocks, roadmaps, orgs, workers,
                    volume_types, roles, categories, equipment_by_inv,
                    departments, assignees) -> dict[str, Task]:
        out: dict[str, Task] = {}
        created = 0
        task_types = {row.slug: row for row in TaskType.objects.all()}

        for index, spec in enumerate(TASKS):
            summary = spec["summary"]
            employee = assignees[index % len(assignees)] if assignees else None

            # Задача с роудмапом наследует от него проект, площадку и блок —
            # ровно как roadmap_service.resolve_task_roadmap. Дублировать их
            # в таблице выше значило бы дать наполнению шанс создать тройку,
            # которую API отвергло бы.
            roadmap = roadmaps[spec["roadmap"]] if spec.get("roadmap") else None
            if roadmap is not None:
                project = roadmap.project
                block = roadmap.site_block
                site = block.site
            else:
                project = projects.get(spec["project"]) if spec.get("project") else None
                site = sites.get(spec["site"]) if spec.get("site") else None
                block = (blocks[(spec["site"], spec["block"])]
                         if spec.get("block") else None)

            org_name = spec.get("contractor")
            worker_last = spec.get("worker")
            defaults = {
                # Тип по умолчанию «задача»; «история» стоит на бумажной
                # работе. Только два из пяти системных типов и используются:
                # «баг» и «эпик» в стройке значат не то, что в трекере, и
                # раскладывать по ним работы ради красивой диаграммы значило
                # бы выдумать данные. Без типа вовсе отчёт «по типу» рисует
                # один столбец `unknown` — так и было до этой строки.
                "task_type": task_types.get(spec.get("type", "task")),
                "description": f"Демо-задача наполнения. Объект: {site.name if site else '—'}.",
                "status": spec["status"],
                "priority": spec["priority"],
                "progress_percent": spec["progress"],
                "project": project,
                "roadmap": roadmap,
                "site": site,
                "site_block": block,
                "contractor": orgs.get(org_name) if org_name else None,
                "contractor_worker": workers.get(worker_last) if worker_last else None,
                "start_date": _d(spec["start"]),
                "due_date": _d(spec["due"]),
                "department_id": (project.department_id if project
                                  else departments.get("stroy")),
                "assignee_id": employee["user_id"] if employee else None,
                "reporter_id": employee["user_id"] if employee else None,
            }

            # Опознаём по summary: ключ выдаёт общий счётчик, и на повторном
            # запуске сравнивать было бы не с чем.
            task = Task.objects.filter(summary=summary).first()
            if task is None:
                task = Task.objects.create(key=next_task_key(),
                                           summary=summary, **defaults)
                created += 1
            else:
                for field, value in defaults.items():
                    setattr(task, field, value)
                task.is_deleted = False
                task.save()
            out[summary] = task

            for type_name, quantity in spec.get("volumes", ()):
                TaskVolume.objects.update_or_create(
                    task=task, volume_type=volume_types[type_name],
                    defaults={"planned_quantity": Decimal(quantity)},
                )
            if spec.get("requirements"):
                self._seed_requirements(
                    target=task, specs=spec["requirements"], roles=roles,
                    categories=categories, start=task.start_date,
                    end=task.due_date)
            if spec.get("equipment"):
                self._seed_allocations(
                    target=task, inventory_nos=spec["equipment"],
                    equipment_by_inv=equipment_by_inv, employee_ids=())

        self.stdout.write(f"  задач: {len(TASKS)} (новых {created})")
        return out

    def _seed_reports(self, tasks: dict[str, Task], volume_types,
                      assignees) -> int:
        """Ежедневные отчёты — единственный источник факта выполнения.

        Идут через ``daily_report_service``, а не прямым ``objects.create``:
        протокол ревизий (первая пишется вместе с отчётом) живёт там, и
        наполнение, которое его обошло бы, дало бы историю версий, какой
        через API не бывает.
        """
        author_ids = [e["user_id"] for e in assignees] or [None]
        created = 0

        for index, spec in enumerate(TASKS):
            task = tasks[spec["summary"]]
            for offset, type_name, quantity, headcount, comment in spec.get("reports", ()):
                work_date = _d(offset)
                type_id = (volume_types[type_name].id if type_name else None)
                # Тройка (задача, дата, вид) — конвенция наполнения, а не
                # инвариант модели: несколько отчётов за день это норма, и
                # уникального индекса на них нет намеренно.
                probe = DailyReport.objects.filter(task=task,
                                                   work_date=work_date)
                if type_id is not None:
                    probe = probe.filter(volume_type_id=type_id)
                if probe.exists():
                    continue
                daily_report_service.create_report(
                    task.id,
                    {"work_date": work_date, "quantity": Decimal(quantity),
                     "headcount": headcount, "comment": comment,
                     "volume_type_id": type_id},
                    author_id=author_ids[index % len(author_ids)],
                )
                created += 1

        edited = 0
        for summary, offset, quantity, comment in REPORT_EDITS:
            report = DailyReport.objects.filter(
                task=tasks[summary], work_date=_d(offset)).first()
            if report is None:
                continue
            # update_report на неизменившихся значениях ревизию не создаёт,
            # поэтому повторный прогон оставляет номер версии прежним.
            daily_report_service.update_report(
                report.id, {"quantity": Decimal(quantity), "comment": comment},
                editor_id=author_ids[0])
            edited += 1

        total = DailyReport.objects.filter(is_deleted=False).count()
        self.stdout.write(
            f"  ежедневных отчётов: {total} (новых {created}, "
            f"исправлено {edited})")
        return total

    def _seed_staff_reports(self, projects, blocks, roles, assignees) -> int:
        """Отчёты по персоналу — вторая ось факта, рядом с ежедневкой.

        Идут через ``staff_report_service``, а не прямым ``objects.create``,
        по той же причине, что и ежедневка: протокол ревизий (первая пишется
        вместе с отчётом) живёт в сервисе.

        Проба на существование здесь проверяет ИНВАРИАНТ модели, а не
        конвенцию наполнения: ``UNIQUE(проект, блок, дата)`` есть в базе, и
        повторный прогон без пробы упёрся бы в него, а не просто создал
        дубль.
        """
        author_ids = [e["user_id"] for e in assignees] or [None]
        created = 0

        for index, spec in enumerate(STAFF_REPORTS):
            project = projects[spec["project"]]
            block = blocks[(spec["site"], spec["block"])]
            for day, comment, crew in spec["days"]:
                work_date = _d(day)
                if ProjectStaffReport.objects.filter(
                        project=project, site_block=block,
                        work_date=work_date, is_deleted=False).exists():
                    continue
                staff_report_service.create_report(
                    project.id,
                    {"site_block_id": block.id, "work_date": work_date,
                     "comment": comment,
                     "lines": [{"work_role_id": roles[name].id,
                                "headcount": number} for name, number in crew]},
                    author_id=author_ids[index % len(author_ids)],
                )
                created += 1

        edited = 0
        for site_name, block_name, day, crew, comment in STAFF_REPORT_EDITS:
            report = ProjectStaffReport.objects.filter(
                site_block=blocks[(site_name, block_name)],
                work_date=_d(day), is_deleted=False).first()
            if report is None:
                continue
            # update_report на неизменившемся составе ревизию не создаёт,
            # поэтому повторный прогон оставляет номер версии прежним.
            staff_report_service.update_report(
                report.id,
                {"comment": comment,
                 "lines": [{"work_role_id": roles[name].id,
                            "headcount": number} for name, number in crew]},
                editor_id=author_ids[0])
            edited += 1

        total = ProjectStaffReport.objects.filter(is_deleted=False).count()
        self.stdout.write(
            f"  отчётов по персоналу: {total} (новых {created}, "
            f"исправлено {edited})")
        return total

    def _seed_roadmap_resources(self, roadmaps, roles, categories,
                                equipment_by_inv, assignees) -> None:
        """Потребности и именные назначения на пакетах работ.

        Своих чисел метод не печатает: у задач есть собственные потребности
        и назначения, и «18» рядом с 26 строками в базе вводило бы в
        заблуждение. Итог печатает ``handle``, когда посчитаны обе части.
        """
        user_ids = [e["user_id"] for e in assignees]
        for index, spec in enumerate(ROADMAPS):
            roadmap = roadmaps[(spec["project"], spec["block"], spec["name"])]
            self._seed_requirements(
                target=roadmap, specs=spec["requirements"], roles=roles,
                categories=categories, start=roadmap.planned_start_date,
                end=roadmap.planned_end_date)
            # По одному человеку на пакет: именные назначения в демо нужны
            # ресурсному Ганту, а не полноте штата.
            crew = user_ids[index % len(user_ids):][:1] if user_ids else []
            self._seed_allocations(
                target=roadmap, inventory_nos=spec["equipment"],
                equipment_by_inv=equipment_by_inv, employee_ids=crew)

    # ── очистка ────────────────────────────────────────────────────────────

    def _purge(self) -> None:
        """Снести засеянное. Порядок обратен зависимостям: ``Site`` и
        ``Contractor`` защищены PROTECT со стороны привлечений и техники,
        а ``SiteBlock`` — со стороны роудмапов."""
        names = {s["name"] for s in SITES}
        project_names = {p["name"] for p in PROJECTS}
        org_names = {c["name"] for c in CONTRACTORS}
        summaries = {t["summary"] for t in TASKS}

        # Задачи каскадят в свои объёмы, отчёты, потребности и назначения.
        tasks = Task.objects.filter(summary__in=summaries).delete()[0]
        eq = Equipment.objects.filter(
            name__in={e[0] for e in EQUIPMENT}).delete()[0]
        eng = ContractorEngagement.objects.filter(
            contractor__name__in=org_names).delete()[0]
        # Задачи, оставшиеся от чужих прогонов, тоже держат работников.
        Task.objects.filter(contractor__name__in=org_names).update(
            contractor=None, contractor_worker=None)
        workers = ContractorWorker.objects.filter(
            contractor__name__in=org_names).delete()[0]
        orgs = Contractor.objects.filter(name__in=org_names).delete()[0]

        # Отчёты по персоналу тоже держат блок через PROTECT. На проект у них
        # CASCADE, но проект сносится ПОЗЖЕ блока, так что дождаться каскада
        # нельзя — иначе удаление блоков упало бы с ProtectedError.
        staff = ProjectStaffReport.objects.filter(
            Q(project__name__in=project_names)
            | Q(site_block__site__name__in=names)).delete()[0]

        # Роудмап держит блок через PROTECT, поэтому он уходит первым.
        # Ссылки задач на оба обнуляет сам Django: у ``Task.roadmap`` и
        # ``Task.site_block`` стоит SET_NULL.
        roadmaps = Roadmap.objects.filter(
            project__name__in=project_names).delete()[0]
        blocks = SiteBlock.objects.filter(site__name__in=names).delete()[0]

        ProjectSite.objects.filter(project__name__in=project_names).delete()
        ProjectSite.objects.filter(site__name__in=names).delete()
        Task.objects.filter(site__name__in=names).update(site=None)
        projects = Project.objects.filter(name__in=project_names).delete()[0]
        sites = Site.objects.filter(name__in=names).delete()[0]

        self.stdout.write(
            f"  снесено: задач {tasks}, техники {eq}, привлечений {eng}, "
            f"работников {workers}, партнёров {orgs}, "
            f"отчётов по персоналу {staff}, роудмапов {roadmaps}, "
            f"блоков {blocks}, проектов {projects}, объектов {sites}"
        )

    def _tasks_tables(self) -> list[str]:
        """Таблицы аппки ``tasks``, включая автосозданную M2M меток."""
        config = django_apps.get_app_config("tasks")
        return sorted({model._meta.db_table for model
                       in config.get_models(include_auto_created=True)})

    def _assert_no_external_references(self, tables: list[str]) -> None:
        """Отказ, если в домен задач ссылается кто-то извне.

        ``TRUNCATE ... CASCADE`` вычищает и ссылающиеся таблицы, поэтому без
        этой проверки одна опечатка в чужой миграции превратила бы очистку
        домена в очистку половины базы. Кросс-доменных FK в проекте нет
        (apps/core/tests/test_app_isolation.py), так что в норме проверка
        ничего не находит — она и стоит ради того дня, когда найдёт.
        """
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT DISTINCT src.relname, tgt.relname
                FROM pg_constraint c
                JOIN pg_class src ON src.oid = c.conrelid
                JOIN pg_class tgt ON tgt.oid = c.confrelid
                WHERE c.contype = 'f'
                  AND tgt.relname = ANY(%s)
                  AND NOT (src.relname = ANY(%s))
                """,
                [tables, tables],
            )
            outside = cursor.fetchall()
        if outside:
            joined = ", ".join(f"{src} → {tgt}" for src, tgt in outside)
            raise CommandError(
                f"В таблицы домена задач ссылаются извне: {joined}. "
                f"TRUNCATE CASCADE снёс бы и их — очистка отменена."
            )

    def _wipe(self) -> None:
        """Полная очистка домена: TRUNCATE по всем таблицам аппки.

        Не ``Model.objects.all().delete()``: удаление гоняло бы каскады
        Django по строкам и спотыкалось бы о PROTECT (роудмап держит блок,
        привлечение — площадку). TRUNCATE одной командой к порядку
        безразличен, а ``RESTART IDENTITY`` заодно возвращает счётчики id к
        началу, чтобы демо-база выглядела свежей.
        """
        tables = self._tasks_tables()
        self._assert_no_external_references(tables)

        with connection.cursor() as cursor:
            # Django объявляет внешние ключи DEFERRABLE INITIALLY DEFERRED, а
            # Postgres отказывается делать TRUNCATE таблице, у которой в этой
            # же транзакции остались НЕОТРАБОТАННЫЕ отложенные триггеры FK
            # («cannot TRUNCATE ... because it has pending trigger events»).
            # Срабатывает всякий раз, когда до очистки в той же транзакции
            # что-то писали. Тот же приём и по той же причине, что в
            # миграции 0012_roadmap_on_block.
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")

            counts = {}
            for table in tables:
                cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
                counts[table] = cursor.fetchone()[0]
            quoted = ", ".join(f'"{t}"' for t in tables)
            cursor.execute(f"TRUNCATE {quoted} RESTART IDENTITY CASCADE")

        total = sum(counts.values())
        touched = {t: n for t, n in counts.items() if n}
        self.stdout.write(
            f"  очищено таблиц: {len(tables)}, удалено строк: {total}")
        for table, number in sorted(touched.items(), key=lambda kv: -kv[1]):
            self.stdout.write(f"    {table}: {number}")

        self._restore_system_rows()

    def _restore_system_rows(self) -> None:
        """Вернуть строки, которые в базу положила миграция, а не человек.

        Системные типы задач ставит 0002, и без них домен неполон: API
        отказывается их удалять, ``Task.task_type`` на них ссылается через
        SET_NULL, а фронт рисует по ним чипы. TRUNCATE о происхождении строк
        не знает, а повторно миграции не пойдут — значит восстанавливает их
        очистка, иначе ``--wipe`` оставлял бы базу в состоянии, которого
        никакая последовательность миграций не даёт.
        """
        for slug, name, color, icon in SYSTEM_TASK_TYPES:
            TaskType.objects.update_or_create(
                slug=slug,
                defaults={"name": name, "color": color, "icon": icon,
                          "is_system": True},
            )
        self.stdout.write(
            f"  восстановлено системных типов задач: {len(SYSTEM_TASK_TYPES)}")

    # ── точка входа ────────────────────────────────────────────────────────

    @transaction.atomic
    def handle(self, *args, **options):
        self._assert_local(options["force_remote"])

        if options["wipe"] or options["wipe_only"]:
            self.stdout.write("Полная очистка домена задач...")
            self._wipe()
        elif options["purge"] or options["purge_only"]:
            self.stdout.write("Очистка демо-данных домена задач...")
            self._purge()

        if options["purge_only"] or options["wipe_only"]:
            self.stdout.write(self.style.SUCCESS("Готово: только очистка."))
            return

        # Отделы и сотрудники — из hr, через интерфейс.
        departments = {d["path"]: d["id"]
                       for d in hr_interface.list_departments_brief()}
        if not departments:
            raise CommandError(
                "В базе нет отделов. Сначала: manage.py seed_hr_demo"
            )

        employees = hr_interface.list_employees_brief()
        with_accounts = [e for e in employees if e["user_id"]]
        if not with_accounts:
            self.stdout.write(self.style.WARNING(
                "  У сотрудников нет платформенных учёток — задачи останутся "
                "без исполнителей, проекты без владельцев, отчёты без "
                "авторов.\n"
                "  Исправляется командой: manage.py seed_employee_accounts"
            ))

        self.stdout.write("Наполнение домена задач...")
        volume_types = self._seed_reference(WorkVolumeType, VOLUME_TYPES)
        roles = self._seed_reference(WorkRole, WORK_ROLES)
        categories = self._seed_reference(
            EquipmentCategory, sorted({e[2] for e in EQUIPMENT}))
        self.stdout.write(
            f"  справочников: видов работ {len(volume_types)}, "
            f"ролей {len(roles)}, типов техники {len(categories)}")

        sites = self._seed_sites()
        blocks = self._seed_blocks(sites)
        self._seed_block_volumes(blocks, volume_types)
        owner_ids = [e["user_id"] for e in with_accounts]
        projects = self._seed_projects(sites, departments, owner_ids)
        roadmaps = self._seed_roadmaps(projects, blocks, owner_ids)
        orgs, workers = self._seed_contractors()
        self._seed_engagements(orgs, projects, sites)
        self._seed_equipment(orgs, categories)
        equipment_by_inv = {e.inventory_no: e for e in Equipment.objects.all()}

        self._seed_roadmap_resources(roadmaps, roles, categories,
                                     equipment_by_inv, with_accounts)
        tasks = self._seed_tasks(
            projects=projects, sites=sites, blocks=blocks, roadmaps=roadmaps,
            orgs=orgs, workers=workers, volume_types=volume_types,
            roles=roles, categories=categories,
            equipment_by_inv=equipment_by_inv, departments=departments,
            assignees=with_accounts)
        self.stdout.write(
            f"  потребностей в ресурсах: {ResourceRequirement.objects.count()}, "
            f"именных назначений: {ResourceAllocation.objects.count()}")
        self._seed_reports(tasks, volume_types, with_accounts)
        self._seed_staff_reports(projects, blocks, roles, with_accounts)

        self.stdout.write(self.style.SUCCESS(
            f"\nГотово: объектов {len(sites)}, блоков {len(blocks)}, "
            f"проектов {len(projects)}, роудмапов {len(roadmaps)}, "
            f"партнёров {len(orgs)} ({len(workers)} чел.), "
            f"техники {len(EQUIPMENT)}, задач {len(TASKS)}."
        ))
