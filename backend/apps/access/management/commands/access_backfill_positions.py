"""Перенос кадровых уровней в роли должностей (блок I, задача 2).

Задача 1 того же блока завела четыре системные роли (``hr-junior``,
``hr-middle``, ``hr-senior``, ``hr-lead``, миграция ``access/0005``) взамен
четырёх старых кадровых уровней. Задача 1b дала штатной выдаче
(``PositionRole``) поле ``scope_kind``. Ни одна из них не тронула ДАННЫЕ —
``PositionRole`` в базе пуст, и включение гейтов новой модели (задачи 4–7
того же блока) отняло бы права у каждого, кому сегодня назначен уровень.
Эта команда переносит их: каждая должность получает роль, соответствующую
тому, что её держатель имеет СЕГОДНЯ — не больше и не меньше.

Уровень должности определяется ТЕМ ЖЕ порядком, каким ``resolve_hr_access``
(``apps/hr/access.py``) резолвил его для живого JWT-токена ДО задачи 9 того
же блока, снявшей резолвер вместе со старой моделью прав — этот порядок
сохранён здесь буквально, ради переноса:

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

⚠️ Раунд правок 1: должность с НЕСКОЛЬКИМИ держателями могла (до задачи 9,
пока резолвер ещё жил на каждый запрос) давать им РАЗНЫЙ уровень
(``Employee.department`` — независимый FK, эвристика
``classify_hr_level`` смотрит в т.ч. на отдел держателя). Правило выбора роли
для такой должности не меняется (по-прежнему первый держатель по ``id`` —
``apps.hr.interface.list_positions_hr_levels``), но расхождение печатается
ОТДЕЛЬНОЙ категорией сводки, рядом с конфликтом: человек на бою обязан
увидеть, что для этой должности перенос выбирал МЕЖДУ уровнями, а не
подтверждённое согласие всех держателей. Разбор — руками, не автоматикой.

⚠️ Явный список ключей должности (финальная волна блока I, рулинг K).
Старый резолвер знал ТРИ источника, а не два: непустой
``Position.permissions["permissions"]`` ЗАМЕНЯЛ пресет уровня целиком
(``1f69716:backend/apps/hr/access.py::resolve_hr_access``) — права держателя
были ровно ``список ∩ ALL_KEYS``. Роль уровня такую должность не переносит:
без ``hr_level`` она осталась бы без роли (сужение), с уровнем и суженным
руками списком получила бы полный пресет (расширение). Поэтому должность с
непустым списком получает ИМЕННУЮ роль ``hr-custom-<slug>-<position_id>``
(``is_system=False``, «Кадры: должность <название> (<slug>)»): узлы —
объединение ``KEY_TO_NODE`` по ключам списка (``apps.hr.interface.
legacy_key_nodes``), плюс явный ЗАПРЕТ на каждом «ключевом» под-узле
выданного узла, которого список не даёт, — иначе под-узел унаследовал бы
признаки предка (``hr.employees: view`` открыл бы зарплату и паспорт), то
самое расширение, которое для ролей уровней закрыла ``access/0008``.
Область — ``COMPANY``, если в списке ``hr.employees.view.all`` (ровно так
старая модель считала ``can_read_all``), иначе ``DEPARTMENT``.

Слаг компании в коде роли — не украшение: каталог ролей общий на всю группу
(``public``), а id должностей нумеруются в каждой схеме заново — у двух
компаний есть «должность 5», и ``hr-custom-5`` второй компании досталась бы
роль первой.

Если вычисленные узлы и область ДОСЛОВНО совпадают с одной из ролей уровня
(список = пресет уровня — так форма должности и сохраняла список: выбор
уровня в ней заполнял галочки пресетом), должность получает эту роль
уровня: выдача та же самая, а каталог не зарастает копиями системных ролей.
Совпадение сверяется со строками роли в БД, а не с названием уровня.

Ключи вне таблицы (``DEFERRED_KEYS`` — чужой ключ ``contracts``) в роль не
идут и печатаются: ``contracts`` читает их из колонки сам. Список, в котором
кадровых ключей нет вовсе, роли не даёт — печатается отдельной строкой.
Каждая именная роль печатается строкой сводки (должность, ключи, узлы,
область), в ``--dry-run`` тоже; после переноса их нужно просмотреть.
Повторный запуск роль не пересоздаёт и её узлы не переписывает (человек мог
поправить роль в каталоге) — расхождение с вычисленным печатается.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.access.models import PositionRole, Role, RolePermission, ScopeKind

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


#: Ключ, по которому старая модель давала «всю компанию» (``can_read_all``).
VIEW_ALL_KEY = "hr.employees.view.all"

_FLAG_COLUMNS = {"view": "can_view", "create": "can_create",
                 "edit": "can_edit", "delete": "can_delete"}
_FLAG_ORDER = ("view", "create", "edit", "delete")


def custom_role_code(slug: str, position_id: int) -> str:
    return f"hr-custom-{slug}-{position_id}"


def custom_role_nodes(
    keys, key_to_node: dict[str, tuple[str, tuple[str, ...]]],
) -> tuple[dict[str, frozenset[str]], list[str]]:
    """Узлы именной роли по явному списку ключей + ключи вне таблицы.

    Узлы — объединение признаков ``key_to_node`` по ключам списка. Затем
    каждый узел таблицы, лежащий СТРОГО ниже выданного и списком не
    выданный, получает пустой набор — запрет: глубина наследуется вниз
    (``resolve._nearest``), и без него ``hr.employees: view`` дал бы
    ``hr.employees.salary``. Правило то же, что у ролей уровней после
    ``access/0008`` — сверяет
    ``test_backfill_positions.py::test_custom_nodes_of_each_preset_equal_the_level_role``.
    Ключи вне таблицы (отложенные) — второй элемент ответа, в роль не идут.
    """
    granted: dict[str, set[str]] = {}
    deferred: list[str] = []
    for key in sorted(set(keys)):
        if key not in key_to_node:
            deferred.append(key)
            continue
        node, flags = key_to_node[key]
        granted.setdefault(node, set()).update(flags)
    table_nodes = {node for node, _flags in key_to_node.values()}
    nodes = {node: frozenset(flags) for node, flags in granted.items()}
    for node in sorted(table_nodes - set(granted)):
        if any(node.startswith(parent + ".") for parent in granted):
            nodes[node] = frozenset()
    return nodes, deferred


def _format_nodes(nodes: dict[str, frozenset[str]]) -> str:
    return ", ".join(
        f"{node}={'+'.join(f for f in _FLAG_ORDER if f in flags) or 'запрет'}"
        for node, flags in sorted(nodes.items())
    )


@dataclass
class _Custom:
    position_id: int
    title: str
    code: str
    keys: tuple[str, ...]
    deferred: tuple[str, ...]
    nodes: dict[str, frozenset[str]]
    scope_kind: str
    #: "создаётся" | "уже есть" | "узлы отличаются" | "конфликт"
    status: str
    existing_codes: tuple[str, ...] = ()


@dataclass
class _NoHrKeys:
    position_id: int
    title: str
    keys: tuple[str, ...]


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
    custom: list[_Custom] = field(default_factory=list)
    no_hr_keys: list[_NoHrKeys] = field(default_factory=list)

    @property
    def granted(self) -> int:
        return self.created + self.already_correct

    @property
    def skipped(self) -> int:
        custom_conflicts = sum(1 for c in self.custom if c.status == "конфликт")
        return (self.skipped_no_level + len(self.conflicts) + custom_conflicts
                + len(self.no_hr_keys))


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
        # Строки ролей уровней — эталон, с которым сравнивается именная роль:
        # совпали узлы и область — та же выдача, роль уровня вместо копии.
        codes_by_id = {role.id: code for code, role in roles_by_code.items()}
        level_rows: dict[str, dict[str, frozenset[str]]] = {
            code: {} for code in roles_by_code
        }
        for row in RolePermission.objects.filter(role_id__in=hr_role_ids):
            level_rows[codes_by_id[row.role_id]][row.node] = row.flags

        all_stats = [
            self._process_company(slug, roles_by_code, hr_role_ids, level_rows, dry_run)
            for slug in slugs
        ]

        for stats in all_stats:
            self._print_company_summary(stats, dry_run)
        if len(all_stats) > 1:
            self._print_grand_summary(all_stats, dry_run)

    def _process_company(self, slug, roles_by_code, hr_role_ids, level_rows,
                         dry_run) -> _CompanyStats:
        from apps.hr import interface as hr
        from htqweb.tenancy.db import use_company

        stats = _CompanyStats(slug=slug)
        with use_company(slug):
            positions = hr.list_positions_hr_levels()
            key_to_node = hr.legacy_key_nodes()
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

                if position["explicit_list"]:
                    # Явный список заменял пресет уровня целиком (рулинг K):
                    # уровень — и разногласие держателей о нём — для прав
                    # такой должности не значил ничего, поэтому расхождение
                    # здесь не печатается.
                    level = self._explicit_list(
                        slug, position, key_to_node, level_rows, roles_by_code,
                        existing_by_position, stats, dry_run,
                    )
                    if level is None:
                        continue
                elif position["divergent"]:
                    # Расхождение печатается НЕЗАВИСИМО от того, что случится
                    # с ролью дальше (создана/уже верна/конфликт/пропуск):
                    # если первый держатель не даёт уровня (level is None), а
                    # другой держатель этой же должности его даёт, должность
                    # будет пропущена ниже — и это ЕЩЁ важнее увидеть в
                    # сводке, не только сам факт разногласия.
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

    def _explicit_list(self, slug, position, key_to_node, level_rows,
                       roles_by_code, existing_by_position, stats,
                       dry_run) -> str | None:
        """Должность с непустым явным списком ключей (рулинг K).

        Уровень — если вычисленная роль дословно (узлы и область) совпала с
        ролью уровня: дальше должность идёт обычным путём уровня. ``None`` —
        должность обработана здесь: именная роль либо строка «кадровых
        ключей в списке нет».
        """
        keys = tuple(position["explicit_keys"])
        nodes, deferred = custom_role_nodes(keys, key_to_node)
        if not nodes:
            stats.no_hr_keys.append(_NoHrKeys(
                position_id=position["id"], title=position["title"], keys=keys,
            ))
            return None

        scope_kind = ScopeKind.COMPANY if VIEW_ALL_KEY in keys else ScopeKind.DEPARTMENT
        for level, code in ROLE_CODE_BY_LEVEL.items():
            if level_rows.get(code) == nodes and SCOPE_KIND_BY_LEVEL[level] == scope_kind:
                return level

        entry = _Custom(
            position_id=position["id"], title=position["title"],
            code=custom_role_code(slug, position["id"]), keys=keys,
            deferred=tuple(deferred), nodes=nodes, scope_kind=scope_kind,
            status="создаётся",
        )
        stats.custom.append(entry)

        existing_level_ids = existing_by_position.get(position["id"], set())
        if existing_level_ids:
            # Роль уровня уже стоит (кадровик или прежний прогон) — решение
            # человека не отменяем, как и у конфликта ролей уровней.
            entry.status = "конфликт"
            entry.existing_codes = tuple(sorted(
                code for code, role in roles_by_code.items()
                if role.id in existing_level_ids
            ))
            return None

        role = Role.objects.filter(code=entry.code).first()
        if role is not None:
            current = {row.node: row.flags for row in RolePermission.objects.filter(role=role)}
            entry.status = "уже есть" if current == nodes else "узлы отличаются"
            if PositionRole.objects.filter(
                company_slug=slug, position_id=position["id"], role=role,
            ).exists():
                stats.already_correct += 1
                return None

        stats.created += 1
        if dry_run:
            return None
        with transaction.atomic():
            if role is None:
                title = f"Кадры: должность {position['title']}"[:230]
                role = Role.objects.create(
                    code=entry.code, title=f"{title} ({slug})", is_system=False,
                )
                RolePermission.objects.bulk_create([
                    RolePermission(role=role, node=node, **{
                        column: flag in flags for flag, column in _FLAG_COLUMNS.items()
                    })
                    for node, flags in sorted(nodes.items())
                ])
            PositionRole.objects.get_or_create(
                company_slug=slug, position_id=position["id"], role=role,
                defaults={"scope_kind": scope_kind},
            )
        return None

    def _print_company_summary(self, stats: _CompanyStats, dry_run: bool) -> None:
        prefix = "[dry-run] " if dry_run else ""
        divergent_note = (
            f", расхождений по держателям {len(stats.divergent)}"
            if stats.divergent else ""
        )
        custom_note = (
            f", именных ролей по явному списку ключей {len(stats.custom)}"
            if stats.custom else ""
        )
        self.stdout.write(self.style.SUCCESS(
            f"{prefix}Компания {stats.slug}: должностей всего {stats.total}, "
            f"роль назначена {stats.granted} (создано сейчас {stats.created}, "
            f"уже было верно {stats.already_correct}), пропущено {stats.skipped}"
            f"{divergent_note}{custom_note}."
        ))
        for custom in stats.custom:
            deferred = (
                f"; не перенесены (чужие ключи, модуль читает их из колонки "
                f"сам): {', '.join(custom.deferred)}" if custom.deferred else ""
            )
            if custom.status == "конфликт":
                tail = (f" — должность уже несёт {', '.join(custom.existing_codes)}: "
                        f"не тронуто, решите вручную")
                style = self.style.WARNING
            elif custom.status == "узлы отличаются":
                tail = " — роль уже есть, но её узлы отличаются от вычисленных: не переписана"
                style = self.style.WARNING
            else:
                tail = f" — роль {custom.status}"
                style = self.style.NOTICE
            self.stdout.write(style(
                f"  - явный список ключей: должность #{custom.position_id} "
                f"«{custom.title}» → именная роль {custom.code}; "
                f"ключи: {', '.join(custom.keys)}; узлы: {_format_nodes(custom.nodes)}; "
                f"область: {custom.scope_kind}{deferred}{tail}."
            ))
        for entry in stats.no_hr_keys:
            self.stdout.write(self.style.WARNING(
                f"  - явный список без кадровых ключей: должность "
                f"#{entry.position_id} «{entry.title}» "
                f"({', '.join(entry.keys) or 'ни одного известного ключа'}) — "
                f"кадровой роли нет (список заменял пресет уровня); "
                f"проверьте вручную."
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
