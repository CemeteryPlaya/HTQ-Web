"""Мост между старой моделью прав кадров и реестром ролей.

Существует ровно на время перехода: старые ключи (``apps.hr.permissions``)
раскладываются по узлам реестра функций и признакам глубины, и из этой
раскладки собираются четыре системные роли, заменяющие четыре старых
уровня. Когда параллельная модель будет снята целиком, файл уходит вместе
с ней.

Таблица — ДАННЫЕ, а не догадка: узлы в ``apps/hr/access_functions.py``
объявлялись как пара к старому каталогу прав (см. его докстринг), поэтому
перевод здесь — перенос, а не переизобретение. Каждое несовпадение, которое
пришлось решать, помечено комментарием на своей строке; сводка — в отчёте
задачи 1 (``.superpowers/sdd/2026-09-17-block-i-single-rbac/task-1-report.md``).

⚠️ Признаки глубины (``VIEW``/``CREATE``/``EDIT``/``DELETE`` ниже) заданы
СТРОКОВЫМИ ЛИТЕРАЛАМИ, а не импортом ``apps.access.depth.VIEW`` и т.д. Не
потому, что тип другой — значения буквально те же четыре строки, — а потому,
что ``apps.access`` для ``apps.hr`` СОСЕДНЯЯ аппка (не общий фундамент вроде
``apps.core``): прямой импорт её внутреннего модуля (``depth`` — не
``interface``) заваливает ``apps/core/tests/test_app_isolation.py`` ровно
так же, как заваливал бы прямой импорт чужих ``models``. Это тот же приём,
которым уже пользуется КАЖДЫЙ ``access_functions.py`` платформы (``apps/hr``,
``apps/contracts``, …): они тоже объявляют признаки строками ``"view"`` и
т.п., а не импортируя ``depth`` — по той же причине. Тесты (``apps/access/
tests/test_hr_level_roles.py``) вольны сверять эти строки с
``apps.access.depth.FLAGS`` напрямую: каталоги ``tests/`` сторож не проверяет.
"""

from __future__ import annotations

from typing import Literal

from apps.hr import permissions as legacy

HRLevel = Literal["junior", "middle", "senior", "lead"]

#: Признаки глубины — литералы ``apps.access.depth.VIEW/CREATE/EDIT/DELETE``
#: (см. докстринг модуля о том, почему не импортом).
VIEW: tuple[str, ...] = ("view",)
EDIT: tuple[str, ...] = ("view", "edit")
CREATE: tuple[str, ...] = ("view", "create")
FULL: tuple[str, ...] = ("view", "create", "edit")
DELETE: tuple[str, ...] = ("view", "create", "edit", "delete")
#: Только «может удалять», без «может редактировать» — ``apps.access.depth``
#: намеренно не включает EDIT в DELETE (докстринг ``depth.py``: «удалить» и
#: «переписать» — разные полномочия). Единственный по-настоящему «только
#: удаление» старый ключ — ``EMPLOYEES_DELETE`` (см. ниже).
PURGE: tuple[str, ...] = ("view", "delete")

#: ``старый ключ -> (узел реестра, признаки)``.
#:
#: Общее правило перевода: ``*.view`` -> ``VIEW``; ``*.edit`` -> ``EDIT``
#: (правит существующую запись, не создаёт и не удаляет — для полей карточки
#: и для отделов/должностей отдельного ключа на создание/удаление в старом
#: каталоге нет); ``*.create`` -> ``CREATE``. ``*.manage``/``ORG_EDIT`` —
#: РАЗБОР ПО МЕСТУ, а не одно правило: там, где сегодняшний
#: ``apps/hr/views.py`` реально гейтит DELETE-эндпойнт этим ключом
#: (``CALENDAR_MANAGE``, ``STAFFING_MANAGE``, ``ORG_EDIT`` — подтверждено по
#: use-сайтам, включая create+update+delete целых коллекций), признаки —
#: полный CRUD (``DELETE`` ниже, все четыре). Там, где ключ сегодня НИГДЕ не
#: подключён к вьюхам (``DOCUMENTS_MANAGE``, ``USERS_MANAGE`` — чистый
#: каталог для UI/``LEVEL_PRESETS``, без единого ``_require_permission``/
#: ``access.has`` по нему), подтвердить delete нечем — признаки ``FULL``
#: (без delete), см. комментарий на их строке.
KEY_TO_NODE: dict[str, tuple[str, tuple[str, ...]]] = {
    # ── Сотрудники ───────────────────────────────────────────────────────
    legacy.EMPLOYEES_VIEW: ("hr.employees", VIEW),
    # ⚠️ Решение 1 («view» против «view.all»): в реестре ОДИН узел
    # ``hr.employees`` — различать «свой отдел» и «все отделы» признаком
    # глубины негде, и придумывать второй узел под то же название значило бы
    # завести узел, которого не объявляла ни одна аппка (сам реестр строится
    # из ``access_functions.py``, а не с потолка). Разница «свой отдел» ->
    # «вся компания» в НОВОЙ модели — это ОБЛАСТЬ выдачи роли
    # (``ScopeKind.DEPARTMENT``/``COMPANY``), а не признак: у ``Role``/
    # ``RolePermission`` (``apps/access/models.py``) области нет вовсе, она
    # появляется только там, где роль ВЫДАЮТ — ``PositionRole``/
    # ``RoleAssignment``. Задача 1b того же блока дала штатной выдаче
    # (``PositionRole``) собственное поле ``scope_kind`` именно ради этой
    # пары уровней: «свой отдел» резолвится по ДЕРЖАТЕЛЮ должности
    # (``apps/access/services/resolve.py::_position_role_ids`` — из его же
    # кадровой карточки на каждый запрос), а не записывается конкретным id
    # при выдаче. Выразить «свой отдел» через ``RoleAssignment`` с пустым
    # ``scope_id`` НЕЛЬЗЯ — это запрещает ``CheckConstraint
    # assignment_scope_id_matches_kind`` (``apps/access/models.py``):
    # ``DEPARTMENT`` там обязан нести конкретный ``scope_id``, а «свой» — это
    # как раз ОТСУТСТВИЕ заранее известного id, поэтому личное назначение для
    # этого не подходит ни по конструкции. Само значение ``scope_kind`` для
    # каждой роли — ЗА ПРЕДЕЛАМИ задачи 1 (она сеет только ``Role``/
    # ``RolePermission``, без единой выдачи) — поэтому решение здесь: обе
    # клавиши ведут на один и тот же узел с одним и тем же признаком VIEW
    # (агрегат по узлу от этого не меняется — VIEW уже даёт EMPLOYEES_VIEW на
    # junior, EMPLOYEES_VIEW_ALL на senior ничего нового к признакам не
    # добавляет), а РЕКОМЕНДАЦИЯ по выдаче — задаче 2 того же блока:
    # ``hr-junior``/``hr-middle`` заводить
    # ``PositionRole(scope_kind=ScopeKind.DEPARTMENT)``, ``hr-senior``/
    # ``hr-lead`` — обычным ``PositionRole`` (область ``COMPANY`` по
    # умолчанию, как и раньше). Проверяется тем, что подмена не меняет
    # посчитанный по узлу набор признаков ни на одном уровне (см.
    # ``test_each_role_reproduces_the_level_it_replaces`` — сверяет
    # ГЕЙТ-УРОВЕНЬ, не область; область при ``scope_kind=DEPARTMENT``
    # проверяет отдельно ``apps/access/tests/test_position_role_scope.py`` —
    # и ``test_roles_grow_monotonically``).
    legacy.EMPLOYEES_VIEW_ALL: ("hr.employees", VIEW),
    legacy.EMPLOYEES_CREATE: ("hr.employees", CREATE),
    legacy.EMPLOYEES_EDIT: ("hr.employees", EDIT),
    # Только удаление, без «может редактировать» (см. PURGE выше) — на LEAD
    # это не сужает права: EDIT/CREATE туда уже приносят более младшие ключи
    # того же уровня (EMPLOYEES_EDIT с middle, EMPLOYEES_CREATE с senior),
    # объединение по узлу их не теряет.
    legacy.EMPLOYEES_DELETE: ("hr.employees", PURGE),
    # Решение 2 задачи 1 вело ``transfer`` на ``("hr.employees", EDIT)`` —
    # тот же узел и признак, что у ``EMPLOYEES_EDIT``, — и это оказалось
    # расширением: старая матрица давала перевод только с senior, а по
    # такой таблице ``has(TRANSFER) ≡ has(EDIT)`` и middle переводил бы,
    # увольнял и менял должность (§6 отчёта задачи 9, «Расхождение 1»).
    # Запрет задачи 1 «не выдумывать узлов» касался узлов ЧУЖОЙ аппки
    # (``contracts``), а реестр ``hr`` — наша зона, поэтому фикс-раунд 1
    # задачи 9 завёл под-узел ``hr.employees.transfer``
    # (``apps/hr/access_functions.py``): senior/lead несут на нём EDIT,
    # junior/middle — явную пустую строку (``access/migrations/0008``),
    # иначе middle унаследовал бы EDIT от ``hr.employees``.
    legacy.EMPLOYEES_TRANSFER: ("hr.employees.transfer", EDIT),

    # ── Отделы / должности / оргструктура ───────────────────────────────
    legacy.DEPARTMENTS_VIEW: ("hr.departments", VIEW),
    # Единственный write-ключ отделов в старом каталоге — отдельного
    # create/delete на отдел нет. Создание и снятие узлов оргструктуры
    # (в т.ч. отделов и должностей как позиций дерева) в старом коде идёт
    # через ORG_EDIT (см. ниже, подтверждено по use-sайтам в views.py:
    # add/remove/change_relation_type — реальный CRUD над рёбрами дерева).
    # EDIT здесь — правка полей уже существующего отдела/должности.
    legacy.DEPARTMENTS_EDIT: ("hr.departments", EDIT),
    legacy.POSITIONS_VIEW: ("hr.positions", VIEW),
    legacy.POSITIONS_EDIT: ("hr.positions", EDIT),
    # ORG_EDIT гейтит add_reporting_relation (POST)/remove_reporting_relation
    # (DELETE)/_change_relation_type (PATCH)/org_relation_superior (PUT) —
    # полный CRUD над рёбрами дерева подчинения, поэтому DELETE (все четыре
    # признака), а не просто EDIT.
    legacy.ORG_EDIT: ("hr.org", DELETE),

    # ── Документы ────────────────────────────────────────────────────────
    legacy.DOCUMENTS_VIEW: ("hr.documents", VIEW),
    # ⚠️ Решение под неопределённостью (4-е, сверх трёх поимённых из брифа —
    # см. отчёт задачи 1). В отличие от CALENDAR_MANAGE/STAFFING_MANAGE/
    # ORG_EDIT ниже, DOCUMENTS_MANAGE НИГДЕ не подключён в сегодняшнем
    # ``apps/hr/views.py`` — это чистый каталожный ключ без вызова
    # ``_require_permission``/``access.has`` по нему, то есть подтвердить его
    # объём по факту использования нельзя (в отличие от «управление»-ключей
    # ниже, где это сделано). Раз данных нет — берём МЕНЬШУЮ из двух
    # трактовок «manage»: FULL (создание+правка), БЕЗ delete. Заниженная
    # трактовка исправляется expand-миграцией на следующий уровень позже,
    # тогда как заниженная защита от завышенной (дать право удалять то, чего
    # старая система, возможно, не разрешала вовсе) сделать нельзя —
    # см. предупреждение брифа «дающая БОЛЬШЕ — откроет лишнее».
    legacy.DOCUMENTS_MANAGE: ("hr.documents", FULL),

    # ── Отчётность ───────────────────────────────────────────────────────
    legacy.REPORTS_VIEW: ("hr.reports", VIEW),

    # ── Учётные записи сотрудников ───────────────────────────────────────
    legacy.USERS_LIST: ("hr.accounts", VIEW),
    # Тот же 4-й случай, что и DOCUMENTS_MANAGE выше: USERS_MANAGE тоже нигде
    # не подключён в apps/hr/views.py сегодня — FULL, без delete, по той же
    # причине (не завышать при отсутствии подтверждения). Эффекта на итоговый
    # legacy_level роли ``lead`` это не меняет: EMPLOYEES_DELETE того же
    # уровня уже несёт признак delete в поддерево hr.
    legacy.USERS_MANAGE: ("hr.accounts", FULL),

    # ── Сверка идентичности (заявки) и прямая правка карточки ───────────
    # IDENTITY_VIEW/IDENTITY_MANAGE — это очередь ЗАЯВОК на изменение
    # идентичности (см. описание в apps/hr/views.py::_PERMISSION_CATALOG:
    # «Заявки на изменение — просмотр/управление», управление = «назначение
    # подтверждающего»), это узел hr.identity_requests, а не hr.employees.*.
    legacy.IDENTITY_VIEW: ("hr.identity_requests", VIEW),
    # «Управление» здесь — это назначение подтверждающего у уже созданной
    # заявки (сама заявка заводится владельцем аккаунта, не кадровиком),
    # поэтому EDIT, а не полный CRUD.
    legacy.IDENTITY_MANAGE: ("hr.identity_requests", EDIT),
    # IDENTITY_FORCE — отдельный узел: это прямая запись имени/телефона/фото
    # В КАРТОЧКУ СОТРУДНИКА в обход очереди подтверждений (см. использование
    # в apps/hr/views.py:1094, ``force_identity=access.has(...)``), а не
    # действие над самой заявкой. Смысл — «есть право писать поле идентичности
    # напрямую» -> EDIT на hr.employees.identity. Ключ намеренно НЕ входит ни
    # в один LEVEL_PRESETS (см. apps/hr/permissions.py) — поэтому он не
    # появится ни в одной из четырёх ролей ниже, что и должно быть: перенос
    # только раскладывает ключ по узлу на случай, если когда-нибудь понадобится
    # роль с этим правом, но само отсутствие в пресетах воспроизводится как
    # есть (см. test_every_legacy_key_is_mapped — ключ обязан быть замаплен,
    # но не обязан встречаться ни в одной роли).
    legacy.IDENTITY_FORCE: ("hr.employees.identity", EDIT),

    # ── Карточка сотрудника: финансы / личные данные / группы полей ─────
    legacy.CARD_FINANCIAL_VIEW: ("hr.employees.salary", VIEW),
    legacy.CARD_FINANCIAL_EDIT: ("hr.employees.salary", EDIT),
    legacy.CARD_PERSONAL_VIEW: ("hr.employees.passport", VIEW),
    legacy.CARD_PERSONAL_EDIT: ("hr.employees.passport", EDIT),
    legacy.CARD_GROUPS_VIEW: ("hr.employees.family", VIEW),
    legacy.CARD_GROUPS_EDIT: ("hr.employees.family", EDIT),

    # ── Производственный календарь ───────────────────────────────────────
    legacy.CALENDAR_VIEW: ("hr.production_calendar", VIEW),
    # Подтверждено по use-сайтам (apps/hr/views.py): create/update/delete
    # шаблонов недели, импорт года, смена шаблона по умолчанию, шаблоны
    # смен — всё под CALENDAR_MANAGE. Полный CRUD -> DELETE.
    legacy.CALENDAR_MANAGE: ("hr.production_calendar", DELETE),

    # ── Штатное расписание ───────────────────────────────────────────────
    legacy.STAFFING_VIEW: ("hr.staffing", VIEW),
    # Подтверждено по use-сайтам: _create_staffing_line/_update_staffing_line/
    # _delete_staffing_line — полный CRUD строк штатки под одним ключом.
    legacy.STAFFING_MANAGE: ("hr.staffing", DELETE),

    # ⚠️ Решение 3 (``contracts.advance_payment.record_payment``) —
    # СОЗНАТЕЛЬНО НЕ ЗАМАПЛЕН. Ключ принадлежит чужой аппке (``contracts``):
    # он лежит в кадровой матрице прав (должность «Бухгалтер» получает его
    # через ``Position.permissions``, а ``contracts`` проверяет через
    # ``apps.hr.interface`` — см. комментарий у константы в
    # ``apps/hr/permissions.py``), но УЗЕЛ под него объявляет и владеет им
    # ``apps.contracts`` (``apps/contracts/access_functions.py`` уже
    # содержит ближайший по смыслу ``contracts.payments`` — «Платежи и
    # предоплаты», но выдумывать соответствие вместо владельца аппки — не
    # моя роль на этой задаче: правила блока запрещают трогать
    # ``apps/contracts/**`` и «не выдумывай узлов чужой аппки»). Право
    # доедет до новой модели отдельно, когда ``contracts`` навесит гейт на
    # свои ручки (roadmap §6.2) — см. ``DEFERRED_KEYS`` ниже и отчёт задачи 1.
}

#: Ключи, СОЗНАТЕЛЬНО оставленные за рамками переноса (не забытые — решение,
#: объяснённое в комментарии у ``KEY_TO_NODE`` и в отчёте задачи 1). Ровно
#: один: чужой ключ аппки ``contracts``. Любой ДРУГОЙ ключ вне
#: ``KEY_TO_NODE`` обязан валить ``test_every_legacy_key_is_mapped`` — это
#: единственное явно разрешённое исключение.
DEFERRED_KEYS: frozenset[str] = frozenset({
    legacy.CONTRACTS_ADVANCE_PAYMENT_RECORD_PAYMENT,
})

#: Старый уровень -> код системной роли, которая его заменяет. Задача 2
#: берёт коды отсюда.
ROLE_CODES: dict[str, str] = {
    "junior": "hr-junior",
    "middle": "hr-middle",
    "senior": "hr-senior",
    "lead": "hr-lead",
}


def nodes_for_level(level: HRLevel) -> dict[str, frozenset[str]]:
    """Узлы и признаки роли для старого уровня — раскрыть пресет через таблицу.

    Пресет (``apps.hr.permissions.LEVEL_PRESETS``) — плоский набор старых
    ключей; у одного узла реестра их может сходиться несколько (например,
    ``EMPLOYEES_VIEW`` и ``EMPLOYEES_VIEW_ALL`` — оба на ``hr.employees``),
    и тогда их признаки СКЛАДЫВАЮТСЯ (объединение множеств), а не
    перезаписываются.
    """
    merged: dict[str, set[str]] = {}
    for key in legacy.LEVEL_PRESETS[level]:
        node, flags = KEY_TO_NODE[key]
        merged.setdefault(node, set()).update(flags)
    return {node: frozenset(flags) for node, flags in merged.items()}
