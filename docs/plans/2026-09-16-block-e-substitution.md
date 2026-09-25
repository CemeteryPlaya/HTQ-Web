# Блок E «Замещение ключевых должностей» (HR-FRM-006) — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Матрица замещения ключевых должностей перестаёт быть бумагой: кто кого замещает, на каком основании и в какой период — хранится в платформе, правится на карточке должности и отдаётся соседнему домену одной функцией `hr.interface.substitutes_for(position_id, on_date)`, которую ждёт разработчик signoff.

**Architecture:** Одна новая модель в тенантной аппке `hr` — `Substitution(position, substitute_position, kind, basis, note, valid_from, valid_to)`. Замещающий — **должность**, а не человек: документ руководства составлен по должностям, и только так правило переживает смену держателя. Логика в `apps/hr/services/substitution_service.py` по образцу `org_service` (связи должностей), HTTP — вложенный ресурс `positions/<id>/substitutions` рядом с прочими ручками должностей, контракт наружу — единственная функция в `apps/hr/interface.py`. Демо-стенд получает матрицу документа в схеме холдинга.

**Tech Stack:** Django 5.2.7 / Python 3.13 (корневой `.venv`), Pydantic-схемы, pytest-django против Postgres `:55432`; React + Vite, TanStack Query, vitest + RTL, i18next с инлайн-фолбэками `t('key', 'текст')`.

**Spec:** [2026-09-14-group-structure-roadmap.md](2026-09-14-group-structure-roadmap.md) §5.E (модель + UI + контракт), §6.1 (строка `hr.substitutes_for` — что именно ждёт сосед), §3 (режим перехода). Документ руководства: **HR-FRM-006 «Матрица замещения ключевых сотрудников»**, ТОО «Hi-Tech Management», утверждена приказом ГД — перерисована в §«Данные документа» ниже целиком, чтобы исполнителю не требовался PDF.

## Global Constraints

- Интерпретатор — **корневой** `.venv`. Из `backend/`: `../.venv/Scripts/python.exe -m pytest <path> -q`.
- **Один прогон pytest за раз, всегда в форграунде, никогда в фоне и не через монитор.** Тестовая БД общая. Ориентиры: полный сьют ~43 мин, `apps/hr` ~9 мин, `apps/companies` ~9 мин.
- Межаппный доступ — только через `apps.<x>.interface` (сторож `apps/core/tests/test_app_isolation.py`); межаппных FK нет; `apps.core` и `htqweb/*` — общий фундамент.
- `hr` — **тенантная** аппка: миграции доводит `manage.py migrate_companies` отдельным шагом выкатки. Только expand.
- Режим перехода (roadmap §3): на бою одна действующая компания; ничего не переносим, не переименовываем, не удаляем.
- **Зона:** `apps/contracts/**`, `apps/signoff/**` и их экраны не трогаются. Блок E только **предоставляет** контракт; вызывать его будет другой разработчик.
- **Ветки не создавать** — работа в выданной ветке (сейчас `sanzhar`).
- Трейлер коммитов: `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- Фронт: настоящая проверка типов — `npx tsc --noEmit -p tsconfig.app.json` (базовая линия **150** ошибок в чужих файлах, новых быть не должно); тесты — `npx vitest run <файлы>`; базовая линия — 8 падений в `src/components/hr/__tests__/{EmployeeFormDialog,CardT2SectionDialog}.test.tsx`.
- Известные падения бэкенда — ровно `backend/ci-known-failures.txt` (8 штук). Девятое — наше.
- **`test_positions_api.py` пинит ТОЧНЫЙ набор ключей `PositionOut`.** Замещения — ВЛОЖЕННЫЙ ресурс, в `PositionOut` не добавляются; если этот тест упал, значит кто-то полез в сериализацию должности — так делать не надо.

---

## Данные документа (HR-FRM-006), перерисованные в таблицу

| Должность | Основной замещающий | Резервный замещающий | Порядок оформления замещения | Примечание |
|---|---|---|---|---|
| Генеральный директор (CEO) | Операционный директор | Финансовый директор (CFO) | Приказ ГД / решение участника; доверенность | Право первой подписи по доверенности |
| Финансовый директор (CFO) | Главный бухгалтер | Экономист | Приказ ГД; доверенность на банк | Казначейские операции — по лимитам |
| Технический директор | Специалист ПТО | Операционный директор | Приказ ГД | — |
| Операционный директор | HR-специалист | Финансовый директор (CFO) | Приказ ГД | — |
| Главный бухгалтер | Бухгалтер | Экономист | Приказ ГД | Право подписи отчётности — по приказу |
| Системный администратор¹ | Внутригрупповой ИТ-подрядчик | — | Приказ ГД / договор | Обеспечение ИБ на период замещения |

¹ **Поправка заказчика от 16.09.2026:** должность в оргструктуре называется **«Специалист технической поддержки»**, а не «Системный администратор». Причина: у каждой компании группы свой человек на этой функции, и объём работы у него уже, чем у того, что платформа называет системным администратором — там под этим словом понимаются **администраторы сайта** с разными наборами возможностей. Смешивать две разные вещи одним словом нельзя. Таблица выше сохраняет формулировку документа дословно; переименование должности — задача 0.

## Решения, принятые при планировании (для проверки заказчиком)

1. **Замещающий — должность, не сотрудник.** Так составлен документ, и так правило переживает смену держателя должности: назначили нового главбуха — матрица не устарела. Кто конкретно замещает сегодня, сосед резолвит сам через существующую `hr.resolve_position_users`.
2. **Замещение — это ПРАВИЛО, а не событие отсутствия.** `substitutes_for(position_id, on_date)` отвечает «кто по регламенту замещает эту должность на эту дату», а не «болеет ли сегодня основной». Модели отсутствий в `hr` нет вовсе (есть только календарь дней и графики смен), и изобретать её в блоке E — отдельный проект. `valid_from`/`valid_to` описывают период действия САМОГО правила (приказ подписан тогда-то, отменён тогда-то), а не отпуск.
3. **Неактивные должности из контракта исключаются.** `substitutes_for` не вернёт замещающую должность с `is_active=False`: она никого не прикроет, а вернуть её — значит отправить маршрут согласования в тупик. UI при этом показывает правило как есть — это два разных вопроса, и расхождение задокументировано в обоих местах.
4. **Права на правку — как у остальных мутаций должности:** `api_view(admin=True)`, то есть «повышенная» учётка (`require_admin` → `TokenPayload.is_elevated`: staff/admin/superuser), ровно тот же гейт, что стоит на создании, правке и удалении самой должности. Матрица замещения утверждается приказом ГД; давать её правку каждому кадровику — не то, что описывает документ. Читать может любой вошедший: знать, кто кого замещает, нужно всем участникам согласования.
5. **История хранится, пересечения запрещены.** Для одной должности может быть много строк одного вида во времени, но не два одновременно действующих «основных»: проверку пересечения периодов делает сервис (тем же приёмом, что `LevelThreshold` проверяет пересечение диапазонов весов), а БД держит `UniqueConstraint(position, kind, valid_from)`.
6. **Строка «Специалист технической поддержки» (в документе — «Системный администратор») не сеется.** Документ называет его замещающим «Внутригрупповой ИТ-подрядчик» — это не должность и не пользователь платформы, смоделировать его как `substitute_position` нельзя. Сид печатает предупреждение, что строка документа осталась незакрытой; это честнее, чем выдумать должность-заглушку.
7. **Названия в HR-FRM-006 и в оргструктуре расходятся** — открытый вопрос руководству (roadmap §8.2), и блок E закрывает его лишь частично, поправками заказчика от 16.09.2026 (задача 0). Для демо-стенда заведено ЯВНОЕ соответствие (задача 6), каждая строка подписана оригиналом из документа; когда руководство ответит по остальным, правится одна таблица.

### Поправки заказчика от 16.09.2026 (обязательны к исполнению)

**П1. «Кадровый бухгалтер» → «Бухгалтер».** В оргструктуре должность называется просто «Бухгалтер». Следствие: расхождение с HR-FRM-006 по этой строке ИСЧЕЗАЕТ — документ и оргструктура называют её одинаково.

**П2. «Системный администратор» → «Специалист технической поддержки».** Две причины, и вторая важнее первой. Первая: у каждой компании группы свой человек на этой функции, и объём его работы — техническая поддержка, а не системное администрирование. Вторая: словом «системный администратор» платформа уже называет **администраторов сайта** — это роль доступа, а не кадровая должность, и у неё свои наборы возможностей. Одно слово для двух разных вещей приведёт к тому, что кадровик, увидев должность, решит, что даёт человеку права администратора сайта.

**Зафиксировано как задача администрирования (НЕ в этом блоке):** заказчик просит расширить состав администраторов сайта и завести СТАРШЕГО администратора — то есть несколько уровней административного доступа вместо одного «повышенного» флага. Это правка каталога ролей и гейта `require_admin` (`TokenPayload.is_elevated`), её место — блок I «Свернуть параллельный RBAC», где гейт `api_view(module=…)` и так навешивается по аппкам. Здесь она не делается, но записана, чтобы не потеряться.

---

## Структура файлов

| Файл | Ответственность |
|---|---|
| `backend/apps/hr/models.py` | `SubstitutionKind`, `Substitution` |
| `backend/apps/hr/migrations/0025_substitution.py` | expand-шаг (новая таблица) |
| `backend/apps/hr/services/substitution_service.py` | правила: пересечения, самозамещение, существование должностей, сериализация |
| `backend/apps/hr/interface.py` | `substitutes_for(position_id, on_date)` — контракт для соседа |
| `backend/apps/hr/schemas.py` | `SubstitutionCreate`, `SubstitutionUpdate` |
| `backend/apps/hr/views.py`, `urls.py` | `positions/<id>/substitutions`, `substitutions/<id>` |
| `frontend/src/api/hr.ts` | четыре функции клиента |
| `frontend/src/components/hr/PositionSubstitutions.tsx` | секция на карточке должности |
| `frontend/src/pages/hr/HRPositions.tsx` | подключение секции |
| `backend/apps/hr/management/group_structures.py`, `commands/seed_hr_demo.py` | матрица документа в демо-стенде |
| `docs/plans/2026-09-14-group-structure-roadmap.md`, `API.md`, `STRUCTURE.md`, `CLAUDE.md` | документы |

---

### Task 0: Поправки заказчика в названиях должностей холдинга

**Files:**
- Modify: `backend/apps/hr/management/group_structures.py` (структура холдинга: две `Post` и две `Person`)
- Modify: `backend/apps/hr/tests/test_group_structures.py` (литералы в `test_direct_chain_matches_the_document`)
- Modify: `docs/plans/2026-09-14-group-structure-roadmap.md` (§8, вопрос 2 — часть снята)
- Modify: `docs/plans/2026-09-15-block-d-levels-directorates-demo.md` (сноска о поправке; сам план блока D НЕ переписывать — он исторический документ)

**Interfaces:**
- Produces: должности `"Бухгалтер"` и `"Специалист технической поддержки"` в структуре холдинга. На эти названия ссылается задача 6.

- [ ] **Step 1: Правка данных**

В `group_structures.py`, структура `_HOLDING`:

```python
        Post("Бухгалтер", "fin", 620, 6, "middle", "Финансовый директор",
             serves_subsidiaries=True),
```
(было `Post("Кадровый бухгалтер", ...)` — вес, отдел, grade, hr_level, начальник и признак обслуживания НЕ меняются)

```python
        Post("Специалист технической поддержки", "ops", 680, 6, "junior",
             "Операционный директор", serves_subsidiaries=True),
```
(было `Post("Системный администратор", ...)` — остальные поля не меняются)

И соответствующие две строки в `people`:

```python
        Person("Досжанова", "Аружан", "Ерлановна", "Бухгалтер", "+7 (700) 100-20-03"),
        ...
        Person("Абишев", "Нурбол", "Талгатович", "Специалист технической поддержки", "+7 (700) 100-40-04"),
```

Над структурой `_HOLDING` добавить комментарий:

```python
# Поправки заказчика от 16.09.2026, две штуки, обе — расхождение с дословным
# текстом документа, принятое сознательно:
#
# «Кадровый бухгалтер» → «Бухгалтер»: так должность называется в
# оргструктуре на самом деле; побочно исчезает расхождение с HR-FRM-006,
# где замещающий главбуха назван «Бухгалтер».
#
# «Системный администратор» → «Специалист технической поддержки»: у каждой
# компании группы свой человек на этой функции, и объём его работы — именно
# техподдержка. Главное же в том, что словом «системный администратор»
# платформа называет АДМИНИСТРАТОРОВ САЙТА — это роль доступа, а не
# кадровая должность. Одно слово для двух разных вещей приводит к тому, что
# кадровик, заводя должность, думает, будто выдаёт права администратора.
```

- [ ] **Step 2: Правка теста**

В `backend/apps/hr/tests/test_group_structures.py`, в `test_direct_chain_matches_the_document`, заменить два литерала:

```python
            ("Бухгалтер", "Финансовый директор"),
            ...
            ("Специалист технической поддержки", "Операционный директор"),
```

Рядом с набором добавить комментарий, что две пары отражают поправку заказчика от 16.09.2026, а не текст документа дословно.

- [ ] **Step 3: Прогон**

Run (из `backend/`): `../.venv/Scripts/python.exe -m pytest apps/hr/tests/test_group_structures.py apps/hr/tests/test_seed_hr_demo.py -q`
Expected: все passed. Счётчики (12 должностей, 12 человек, 11 связей) не меняются — меняются только два названия.

- [ ] **Step 4: Документы**

В `docs/plans/2026-09-14-group-structure-roadmap.md`, §8 вопрос 2 («Должности расходятся…») — дописать, что две пары из четырёх сняты решением заказчика 16.09.2026: «Кадровый бухгалтер» → «Бухгалтер» (совпало с HR-FRM-006) и «Системный администратор» → «Специалист технической поддержки» (потому что «системный администратор» в платформе означает администратора сайта). Остаются открытыми «Менеджер по кадрам / HR-специалист», «Менеджер ПТО и КК / Специалист ПТО», «Экономист-аналитик / Экономист».

Туда же, в §8 или в конец §5, добавить строку: «**Уровни администраторов сайта.** Заказчик просит расширить состав администраторов и завести старшего администратора — несколько уровней административного доступа вместо одного флага `is_elevated`. Место — блок I, где и так пересматривается гейт `api_view(module=…)`.»

В `docs/plans/2026-09-15-block-d-levels-directorates-demo.md`, сразу под заголовком раздела «Данные документа (стр. 2–5)», добавить одну строку: «⚠️ Поправка заказчика от 16.09.2026: «Кадровый бухгалтер» читается как «Бухгалтер», «Системный администратор» — как «Специалист технической поддержки» (см. план блока E). Таблицы ниже сохраняют формулировки документа.» Сам план блока D НЕ переписывать: он — запись того, что было построено тогда.

- [ ] **Step 5: Коммит**

```bash
git add backend/apps/hr/management/group_structures.py backend/apps/hr/tests/test_group_structures.py docs/plans/2026-09-14-group-structure-roadmap.md docs/plans/2026-09-15-block-d-levels-directorates-demo.md
git commit -m "fix(hr): названия двух должностей холдинга по поправке заказчика

«Кадровый бухгалтер» → «Бухгалтер»: так должность называется в
оргструктуре, и расхождение с матрицей замещения исчезает.
«Системный администратор» → «Специалист технической поддержки»: тем же
словом платформа называет администраторов сайта, и совпадение вводило бы
кадровика в заблуждение насчёт выдаваемых прав.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 1: Модель `Substitution` и expand-миграция

**Files:**
- Modify: `backend/apps/hr/models.py` (после `ReportingRelation`, рядом с `EmployeeReportingOverride`)
- Create: `backend/apps/hr/migrations/0025_substitution.py` (через `makemigrations`)
- Test: `backend/apps/hr/tests/test_substitution_model.py`

**Interfaces:**
- Produces: `apps.hr.models.Substitution` с полями `position`, `substitute_position`, `kind`, `basis`, `note`, `valid_from`, `valid_to`; `apps.hr.models.SubstitutionKind.{PRIMARY,RESERVE}` со значениями `"primary"`/`"reserve"`. Эти имена использует каждая следующая задача.

- [ ] **Step 1: Написать падающий тест**

`backend/apps/hr/tests/test_substitution_model.py`:

```python
"""Матрица замещения (HR-FRM-006) на уровне схемы.

Замещающий — ДОЛЖНОСТЬ, а не человек: документ составлен по должностям, и
только так правило переживает смену держателя. Ограничения в БД закрывают
то, что нельзя доверить дисциплине вызывающего: замещение самого себя и
период, кончающийся раньше, чем начался.
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.db import IntegrityError, transaction

from apps.hr.models import Department, Position, Substitution, SubstitutionKind


@pytest.fixture
def dep(db):
    return Department.objects.create(name="Руководство", path="upr")


def _pos(dep, title, weight):
    return Position.objects.create(title=title, department=dep, weight=weight)


@pytest.mark.django_db
def test_substitution_stores_the_document_row(dep):
    ceo = _pos(dep, "Генеральный директор", 10)
    ops = _pos(dep, "Операционный директор", 130)
    row = Substitution.objects.create(
        position=ceo, substitute_position=ops, kind=SubstitutionKind.PRIMARY,
        basis="Приказ ГД / решение участника; доверенность",
        note="Право первой подписи по доверенности",
        valid_from=dt.date(2026, 9, 10),
    )
    row.refresh_from_db()
    assert row.kind == "primary"
    assert row.valid_to is None  # бессрочно, пока приказ не отменён
    assert row.get_kind_display() == "Основной"
    assert list(ceo.substitutions.all()) == [row]
    assert list(ops.substitutes_in.all()) == [row]


@pytest.mark.django_db
def test_position_cannot_substitute_itself(dep):
    ceo = _pos(dep, "Генеральный директор", 10)
    with pytest.raises(IntegrityError), transaction.atomic():
        Substitution.objects.create(
            position=ceo, substitute_position=ceo, basis="Приказ ГД",
            valid_from=dt.date(2026, 9, 10),
        )


@pytest.mark.django_db
def test_period_cannot_end_before_it_starts(dep):
    ceo = _pos(dep, "Генеральный директор", 10)
    ops = _pos(dep, "Операционный директор", 130)
    with pytest.raises(IntegrityError), transaction.atomic():
        Substitution.objects.create(
            position=ceo, substitute_position=ops, basis="Приказ ГД",
            valid_from=dt.date(2026, 9, 10), valid_to=dt.date(2026, 9, 1),
        )


@pytest.mark.django_db
def test_same_kind_cannot_start_twice_on_one_day(dep):
    """Два «основных» замещающих с одной датой начала — это не история, а
    ошибка ввода; пересечения периодов ловит сервис, точное совпадение —
    база."""
    ceo = _pos(dep, "Генеральный директор", 10)
    ops = _pos(dep, "Операционный директор", 130)
    cfo = _pos(dep, "Финансовый директор", 110)
    Substitution.objects.create(position=ceo, substitute_position=ops,
                                basis="Приказ ГД", valid_from=dt.date(2026, 9, 10))
    with pytest.raises(IntegrityError), transaction.atomic():
        Substitution.objects.create(position=ceo, substitute_position=cfo,
                                    basis="Приказ ГД", valid_from=dt.date(2026, 9, 10))


@pytest.mark.django_db
def test_reserve_may_start_the_same_day_as_primary(dep):
    """Основной и резервный — разные виды, один приказ заводит оба сразу."""
    ceo = _pos(dep, "Генеральный директор", 10)
    ops = _pos(dep, "Операционный директор", 130)
    cfo = _pos(dep, "Финансовый директор", 110)
    Substitution.objects.create(position=ceo, substitute_position=ops,
                                kind=SubstitutionKind.PRIMARY,
                                basis="Приказ ГД", valid_from=dt.date(2026, 9, 10))
    Substitution.objects.create(position=ceo, substitute_position=cfo,
                                kind=SubstitutionKind.RESERVE,
                                basis="Приказ ГД", valid_from=dt.date(2026, 9, 10))
    assert ceo.substitutions.count() == 2


@pytest.mark.django_db
def test_deleting_the_position_takes_its_rules_with_it(dep):
    """Правило замещения не переживает должность, к которой относится —
    тот же выбор, что у ReportingRelation."""
    ceo = _pos(dep, "Генеральный директор", 10)
    ops = _pos(dep, "Операционный директор", 130)
    Substitution.objects.create(position=ceo, substitute_position=ops,
                                basis="Приказ ГД", valid_from=dt.date(2026, 9, 10))
    ceo.delete()
    assert Substitution.objects.count() == 0
```

- [ ] **Step 2: Убедиться, что падает**

Run (из `backend/`): `../.venv/Scripts/python.exe -m pytest apps/hr/tests/test_substitution_model.py -q`
Expected: ERROR при импорте — `ImportError: cannot import name 'Substitution'`.

- [ ] **Step 3: Модель**

`backend/apps/hr/models.py`, сразу после класса `ReportingRelation` (там же живут остальные связи между должностями):

```python
class SubstitutionKind(models.TextChoices):
    PRIMARY = "primary", "Основной"
    RESERVE = "reserve", "Резервный"


class Substitution(HrBase):
    """Строка матрицы замещения ключевых должностей (HR-FRM-006).

    Замещающий — ДОЛЖНОСТЬ, а не сотрудник: документ руководства составлен
    по должностям, и только так правило переживает смену держателя —
    назначили нового главбуха, и матрица не устарела. Кто именно замещает
    сегодня, потребитель резолвит сам (``hr.interface.resolve_position_users``).

    Это ПРАВИЛО, а не событие отсутствия. ``valid_from``/``valid_to``
    описывают период действия самого правила (приказ подписан — приказ
    отменён), а не отпуск держателя: модели отсутствий в домене нет вовсе,
    и вопрос «болеет ли он сегодня» этой таблицей не решается.

    ``basis`` — колонка документа «Порядок оформления замещения» («Приказ
    ГД», «Приказ ГД; доверенность на банк»): в платформе замещение только
    отражается, юридическую силу ему даёт приказ, и ссылка на него обязана
    храниться рядом с правилом. ``note`` — колонка «Примечание» («Право
    первой подписи по доверенности»), она ограничивает то, что замещающий
    вправе делать, и теряться не должна.

    ``on_delete=CASCADE`` у обоих FK — как у ``ReportingRelation``: правило
    между двумя должностями не переживает ни одну из них. Практически
    удалить занятую должность и так нельзя (``Employee.position`` —
    ``PROTECT``).
    """

    position = models.ForeignKey(
        Position, on_delete=models.CASCADE, related_name="substitutions",
    )
    substitute_position = models.ForeignKey(
        Position, on_delete=models.CASCADE, related_name="substitutes_in",
    )
    kind = models.CharField(
        max_length=16,
        choices=SubstitutionKind.choices,
        default=SubstitutionKind.PRIMARY,
        db_default=SubstitutionKind.PRIMARY.value,
    )
    basis = models.CharField(max_length=255)
    note = models.CharField(max_length=255, null=True, blank=True)
    valid_from = models.DateField()
    valid_to = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name = "Замещение"
        verbose_name_plural = "Матрица замещения"
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(position=models.F("substitute_position")),
                name="ck_no_self_substitution",
            ),
            models.CheckConstraint(
                condition=models.Q(valid_to__isnull=True)
                | models.Q(valid_to__gte=models.F("valid_from")),
                name="ck_substitution_range",
            ),
            models.CheckConstraint(
                condition=models.Q(kind__in=list(SubstitutionKind.values)),
                name="ck_substitution_kind",
            ),
            # Точное совпадение (должность, вид, дата начала) — ошибка ввода.
            # ПЕРЕСЕЧЕНИЯ периодов ловит substitution_service: выразить их
            # ограничением БД без EXCLUDE-констрейнта нельзя, а EXCLUDE
            # потребовал бы расширения btree_gist ради одной таблицы.
            models.UniqueConstraint(
                fields=["position", "kind", "valid_from"],
                name="uq_substitution_start",
            ),
        ]

    def __str__(self) -> str:
        return (f"<Substitution(pos={self.position_id}, "
                f"sub={self.substitute_position_id}, kind='{self.kind}')>")
```

- [ ] **Step 4: Миграция**

Run: `../.venv/Scripts/python.exe manage.py makemigrations hr -n substitution`
Expected: один файл `0025_substitution.py` с `CreateModel`. Добавить в начало файла докстринг:

```python
"""Expand-шаг: таблица матрицы замещения (HR-FRM-006), блок E.

``hr`` — тенантная аппка: миграция НЕ применяется стартом контейнера
(``migrate_shared``), схемы компаний доводит ``manage.py migrate_companies``
отдельным шагом выкатки.

Шаг чисто аддитивный — новая таблица, ни одного существующего столбца не
трогает. ``Substitution`` НЕ входит в ``HOLDING_MODELS`` (``apps/hr/holding.py``):
сводное чтение матрицы замещения по всей группе никем не заказано, а
включение модели в сводки стоит пересборки представлений на каждой выкатке.
"""
```

- [ ] **Step 5: Тесты зелёные**

Run: `../.venv/Scripts/python.exe -m pytest apps/hr/tests/test_substitution_model.py apps/hr/tests/test_models_schema.py -q`
Expected: все passed.

- [ ] **Step 6: Коммит**

```bash
git add backend/apps/hr/models.py backend/apps/hr/migrations/0025_substitution.py backend/apps/hr/tests/test_substitution_model.py
git commit -m "feat(hr): матрица замещения ключевых должностей — модель

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Сервис `substitution_service`

**Files:**
- Create: `backend/apps/hr/services/substitution_service.py`
- Test: `backend/apps/hr/tests/test_substitution_service.py`

**Interfaces:**
- Consumes: `apps.hr.models.{Substitution, SubstitutionKind, Position}`.
- Produces (используют задачи 3, 4, 6):
  - исключения `SubstitutionError` (база), `SubstitutionSelfReferential`, `SubstitutionPositionNotFound`, `SubstitutionOverlap`, `SubstitutionNotFound` — каждое с полями `status` и `detail`, как у `lifecycle.LifecycleError` в `apps.companies`;
  - `serialize(row) -> dict` — ключи `id, position_id, substitute_position_id, substitute_position_title, kind, basis, note, valid_from, valid_to, created_at, updated_at` (даты — ISO-строки или `None`);
  - `list_for_position(position_id) -> list[Substitution]` — все строки, включая истёкшие, порядок: `kind` (primary раньше reserve), затем `valid_from` по убыванию;
  - `active_for_position(position_id, on_date) -> list[Substitution]` — только действующие на дату И с активной замещающей должностью;
  - `create(*, position_id, substitute_position_id, kind, basis, note, valid_from, valid_to) -> Substitution`;
  - `update(substitution_id, **fields) -> Substitution`;
  - `delete(substitution_id) -> None`.

- [ ] **Step 1: Написать падающий тест**

`backend/apps/hr/tests/test_substitution_service.py`:

```python
"""Правила матрицы замещения.

Главное правило одно: у должности не может быть двух одновременно
действующих замещающих одного вида. Иначе маршрут согласования получает
двух «основных» и молча выбирает первого попавшегося — то есть решение
принимает порядок строк в таблице.
"""

from __future__ import annotations

import datetime as dt

import pytest

from apps.hr.models import Department, Position, SubstitutionKind
from apps.hr.services import substitution_service as svc

TODAY = dt.date(2026, 9, 16)


@pytest.fixture
def positions(db):
    dep = Department.objects.create(name="Руководство", path="upr")
    return {
        "ceo": Position.objects.create(title="Генеральный директор", department=dep, weight=10),
        "ops": Position.objects.create(title="Операционный директор", department=dep, weight=130),
        "cfo": Position.objects.create(title="Финансовый директор", department=dep, weight=110),
    }


def _create(positions, who="ceo", sub="ops", kind=SubstitutionKind.PRIMARY,
            valid_from=dt.date(2026, 1, 1), valid_to=None, basis="Приказ ГД"):
    return svc.create(
        position_id=positions[who].id, substitute_position_id=positions[sub].id,
        kind=kind, basis=basis, note=None, valid_from=valid_from, valid_to=valid_to,
    )


def test_create_returns_a_row_and_serializes_it(positions):
    row = _create(positions, basis="Приказ ГД; доверенность на банк")
    body = svc.serialize(row)
    assert body["position_id"] == positions["ceo"].id
    assert body["substitute_position_id"] == positions["ops"].id
    assert body["substitute_position_title"] == "Операционный директор"
    assert body["kind"] == "primary"
    assert body["basis"] == "Приказ ГД; доверенность на банк"
    assert body["valid_from"] == "2026-01-01"
    assert body["valid_to"] is None


def test_self_substitution_is_refused(positions):
    with pytest.raises(svc.SubstitutionSelfReferential):
        svc.create(position_id=positions["ceo"].id,
                   substitute_position_id=positions["ceo"].id,
                   kind=SubstitutionKind.PRIMARY, basis="Приказ ГД", note=None,
                   valid_from=TODAY, valid_to=None)


@pytest.mark.parametrize("field", ["position_id", "substitute_position_id"])
def test_unknown_position_is_refused(positions, field):
    kwargs = dict(position_id=positions["ceo"].id,
                  substitute_position_id=positions["ops"].id,
                  kind=SubstitutionKind.PRIMARY, basis="Приказ ГД", note=None,
                  valid_from=TODAY, valid_to=None)
    kwargs[field] = 10_000_000
    with pytest.raises(svc.SubstitutionPositionNotFound):
        svc.create(**kwargs)


def test_two_open_ended_primaries_overlap(positions):
    _create(positions, valid_from=dt.date(2026, 1, 1))
    with pytest.raises(svc.SubstitutionOverlap):
        _create(positions, sub="cfo", valid_from=dt.date(2026, 6, 1))


def test_closed_period_lets_the_next_one_start(positions):
    _create(positions, valid_from=dt.date(2026, 1, 1), valid_to=dt.date(2026, 5, 31))
    row = _create(positions, sub="cfo", valid_from=dt.date(2026, 6, 1))
    assert row.valid_from == dt.date(2026, 6, 1)


def test_periods_touching_on_the_same_day_overlap(positions):
    """Границы включительные: правило, действующее ПО 31 мая, и правило,
    действующее С 31 мая, в этот день оба активны."""
    _create(positions, valid_from=dt.date(2026, 1, 1), valid_to=dt.date(2026, 5, 31))
    with pytest.raises(svc.SubstitutionOverlap):
        _create(positions, sub="cfo", valid_from=dt.date(2026, 5, 31))


def test_reserve_does_not_collide_with_primary(positions):
    _create(positions, kind=SubstitutionKind.PRIMARY, valid_from=dt.date(2026, 1, 1))
    row = _create(positions, sub="cfo", kind=SubstitutionKind.RESERVE,
                  valid_from=dt.date(2026, 1, 1))
    assert row.kind == "reserve"


def test_update_rechecks_the_overlap_without_colliding_with_itself(positions):
    row = _create(positions, valid_from=dt.date(2026, 1, 1), valid_to=dt.date(2026, 5, 31))
    # Своя же строка не должна считаться пересечением самой себя.
    updated = svc.update(row.id, valid_to=dt.date(2026, 6, 30))
    assert updated.valid_to == dt.date(2026, 6, 30)

    other = _create(positions, sub="cfo", valid_from=dt.date(2026, 7, 1))
    with pytest.raises(svc.SubstitutionOverlap):
        svc.update(other.id, valid_from=dt.date(2026, 6, 1))


def test_delete_removes_the_row_and_unknown_id_is_refused(positions):
    row = _create(positions)
    svc.delete(row.id)
    assert svc.list_for_position(positions["ceo"].id) == []
    with pytest.raises(svc.SubstitutionNotFound):
        svc.delete(row.id)


def test_list_puts_primary_first_then_newest_period(positions):
    old = _create(positions, valid_from=dt.date(2025, 1, 1), valid_to=dt.date(2025, 12, 31))
    new = _create(positions, sub="cfo", valid_from=dt.date(2026, 1, 1))
    reserve = _create(positions, sub="cfo", kind=SubstitutionKind.RESERVE,
                      valid_from=dt.date(2026, 1, 1))
    assert [r.id for r in svc.list_for_position(positions["ceo"].id)] == [
        new.id, old.id, reserve.id]


def test_active_for_position_filters_by_date(positions):
    past = _create(positions, valid_from=dt.date(2025, 1, 1), valid_to=dt.date(2025, 12, 31))
    now = _create(positions, sub="cfo", valid_from=dt.date(2026, 1, 1))
    active = svc.active_for_position(positions["ceo"].id, TODAY)
    assert [r.id for r in active] == [now.id]
    assert [r.id for r in svc.active_for_position(positions["ceo"].id,
                                                  dt.date(2025, 6, 1))] == [past.id]


def test_active_for_position_skips_a_deactivated_substitute(positions):
    """Неактивная должность никого не прикроет — вернуть её значит отправить
    маршрут согласования в тупик."""
    _create(positions)
    positions["ops"].is_active = False
    positions["ops"].save(update_fields=["is_active", "updated_at"])
    assert svc.active_for_position(positions["ceo"].id, TODAY) == []
```

- [ ] **Step 2: Убедиться, что падает**

Run: `../.venv/Scripts/python.exe -m pytest apps/hr/tests/test_substitution_service.py -q`
Expected: ERROR при импорте — `ImportError: cannot import name 'substitution_service'`.

- [ ] **Step 3: Сервис**

`backend/apps/hr/services/substitution_service.py`:

```python
"""Правила матрицы замещения ключевых должностей (HR-FRM-006), блок E.

Модель хранит строки, сервис хранит единственное правило, которое БД
выразить не может без расширения: у должности не бывает двух одновременно
действующих замещающих одного вида. Без него маршрут согласования получает
двух «основных» и выбирает первого попавшегося — то есть решение принимает
порядок строк в таблице.

Границы периодов ВКЛЮЧИТЕЛЬНЫЕ с обеих сторон: правило, действующее «по 31
мая», и правило «с 31 мая» в этот день пересекаются. Открытый конец
(``valid_to=None``) означает «пока не отменено приказом» и пересекается со
всем, что начинается позже.

Приём тот же, что у ``position_service`` с диапазонами весов уровней:
проверка пересечения живёт в сервисе, а БД держит то, что ей по силам —
точное совпадение (должность, вид, дата начала).
"""

from __future__ import annotations

import datetime as dt

from django.db.models import Q

from apps.hr.models import Position, Substitution, SubstitutionKind


class SubstitutionError(Exception):
    """База ошибок домена. ``status``/``detail`` читает слой HTTP."""

    status = 400
    detail = "Ошибка матрицы замещения."


class SubstitutionSelfReferential(SubstitutionError):
    status = 422
    detail = "Должность не может замещать сама себя."


class SubstitutionPositionNotFound(SubstitutionError):
    status = 404
    detail = "Должность не найдена."


class SubstitutionOverlap(SubstitutionError):
    status = 409

    def __init__(self, existing: Substitution) -> None:
        self.existing = existing
        end = existing.valid_to.isoformat() if existing.valid_to else "бессрочно"
        self.detail = (
            f"У этой должности уже есть замещающий того же вида в пересекающийся "
            f"период ({existing.valid_from.isoformat()} — {end}). Закройте прежнее "
            f"замещение датой окончания, прежде чем заводить новое."
        )
        super().__init__(self.detail)


class SubstitutionNotFound(SubstitutionError):
    status = 404
    detail = "Замещение не найдено."


# primary раньше reserve — порядок документа, а не алфавита.
_KIND_ORDER = {SubstitutionKind.PRIMARY.value: 0, SubstitutionKind.RESERVE.value: 1}


def serialize(row: Substitution) -> dict:
    """SubstitutionOut. ``substitute_position_title`` кладётся рядом с id
    намеренно: карточка должности показывает название, и без него фронт
    делал бы второй запрос за списком должностей ради одной строки."""
    return {
        "id": row.id,
        "position_id": row.position_id,
        "substitute_position_id": row.substitute_position_id,
        "substitute_position_title": row.substitute_position.title,
        "kind": row.kind,
        "basis": row.basis,
        "note": row.note,
        "valid_from": row.valid_from.isoformat(),
        "valid_to": row.valid_to.isoformat() if row.valid_to else None,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def _ordered(rows: list[Substitution]) -> list[Substitution]:
    return sorted(rows, key=lambda r: (_KIND_ORDER.get(r.kind, 9), -r.valid_from.toordinal()))


def list_for_position(position_id: int) -> list[Substitution]:
    """Все строки должности, включая истёкшие: карточка показывает историю."""
    rows = list(Substitution.objects
                .filter(position_id=position_id)
                .select_related("substitute_position"))
    return _ordered(rows)


def active_for_position(position_id: int, on_date: dt.date) -> list[Substitution]:
    """Действующие на дату строки с ДЕЙСТВУЮЩЕЙ замещающей должностью.

    Фильтр по ``is_active`` — здесь, а не у вызывающего: неактивная
    должность никого не прикроет, и вернуть её значит отправить маршрут
    согласования в тупик. Карточка должности при этом показывает правило как
    есть — это разные вопросы, и расхождение намеренное.
    """
    rows = list(Substitution.objects
                .filter(position_id=position_id, substitute_position__is_active=True)
                .filter(valid_from__lte=on_date)
                .filter(Q(valid_to__isnull=True) | Q(valid_to__gte=on_date))
                .select_related("substitute_position"))
    return _ordered(rows)


def _require_positions(*ids: int) -> None:
    known = set(Position.objects.filter(id__in=ids).values_list("id", flat=True))
    if set(ids) - known:
        raise SubstitutionPositionNotFound()


def _check_overlap(*, position_id: int, kind: str, valid_from: dt.date,
                   valid_to: dt.date | None, exclude_id: int | None = None) -> None:
    qs = Substitution.objects.filter(position_id=position_id, kind=kind)
    if exclude_id is not None:
        qs = qs.exclude(id=exclude_id)
    # Пересечение: начало нового не позже конца старого И конец нового не
    # раньше начала старого. Открытый конец — бесконечность справа.
    qs = qs.filter(Q(valid_to__isnull=True) | Q(valid_to__gte=valid_from))
    if valid_to is not None:
        qs = qs.filter(valid_from__lte=valid_to)
    clash = qs.order_by("valid_from").first()
    if clash is not None:
        raise SubstitutionOverlap(clash)


def create(*, position_id: int, substitute_position_id: int, kind: str,
           basis: str, note: str | None, valid_from: dt.date,
           valid_to: dt.date | None) -> Substitution:
    if position_id == substitute_position_id:
        raise SubstitutionSelfReferential()
    _require_positions(position_id, substitute_position_id)
    _check_overlap(position_id=position_id, kind=kind,
                   valid_from=valid_from, valid_to=valid_to)
    return Substitution.objects.create(
        position_id=position_id, substitute_position_id=substitute_position_id,
        kind=kind, basis=basis, note=note,
        valid_from=valid_from, valid_to=valid_to,
    )


def update(substitution_id: int, **fields) -> Substitution:
    """Правка строки. Пересечение перепроверяется по ИТОГОВЫМ значениям и с
    исключением самой строки — иначе правка даты окончания считала бы
    пересечением саму себя."""
    row = (Substitution.objects
           .filter(id=substitution_id)
           .select_related("substitute_position")
           .first())
    if row is None:
        raise SubstitutionNotFound()

    allowed = {"substitute_position_id", "kind", "basis", "note",
               "valid_from", "valid_to"}
    changes = {k: v for k, v in fields.items() if k in allowed}
    for key, value in changes.items():
        setattr(row, key, value)

    if row.position_id == row.substitute_position_id:
        raise SubstitutionSelfReferential()
    _require_positions(row.position_id, row.substitute_position_id)
    _check_overlap(position_id=row.position_id, kind=row.kind,
                   valid_from=row.valid_from, valid_to=row.valid_to,
                   exclude_id=row.id)
    row.save(update_fields=[*changes, "updated_at"])
    row.refresh_from_db()
    return row


def delete(substitution_id: int) -> None:
    deleted, _ = Substitution.objects.filter(id=substitution_id).delete()
    if not deleted:
        raise SubstitutionNotFound()
```

- [ ] **Step 4: Тесты зелёные**

Run: `../.venv/Scripts/python.exe -m pytest apps/hr/tests/test_substitution_service.py -q`
Expected: все passed. Если `test_update_rechecks_the_overlap_without_colliding_with_itself` падает — значит `exclude_id` не доехал до запроса; чинить сервис, не тест.

- [ ] **Step 5: Коммит**

```bash
git add backend/apps/hr/services/substitution_service.py backend/apps/hr/tests/test_substitution_service.py
git commit -m "feat(hr): правила матрицы замещения — пересечения периодов и самозамещение

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Контракт наружу — `hr.interface.substitutes_for`

**Files:**
- Modify: `backend/apps/hr/interface.py` (в конец, рядом с прочими функциями)
- Test: `backend/apps/hr/tests/test_interface_substitutes.py`

**Interfaces:**
- Consumes: `substitution_service.active_for_position`.
- Produces: `apps.hr.interface.substitutes_for(position_id: int, on_date: datetime.date | None = None) -> list[dict]`, каждый элемент — РОВНО три ключа `position_id`, `kind`, `basis`. Это контракт из roadmap §6.1; его ждёт разработчик signoff, менять форму в одиночку нельзя.

- [ ] **Step 1: Написать падающий тест**

`backend/apps/hr/tests/test_interface_substitutes.py`:

```python
"""Контракт `hr.substitutes_for` — то, что вызывает соседний домен.

Форма ответа зафиксирована в roadmap §6.1 и согласована с разработчиком
signoff: РОВНО три ключа. Лишний ключ здесь — это лишний ключ в чужом коде,
поэтому набор проверяется точным сравнением, а не вхождением.
"""

from __future__ import annotations

import datetime as dt

import pytest

from apps.core.services import ServiceDisabled
from apps.hr import interface
from apps.hr.models import Department, Position, SubstitutionKind
from apps.hr.services import substitution_service as svc

TODAY = dt.date(2026, 9, 16)


@pytest.fixture
def matrix(db):
    dep = Department.objects.create(name="Руководство", path="upr")
    ceo = Position.objects.create(title="Генеральный директор", department=dep, weight=10)
    ops = Position.objects.create(title="Операционный директор", department=dep, weight=130)
    cfo = Position.objects.create(title="Финансовый директор", department=dep, weight=110)
    svc.create(position_id=ceo.id, substitute_position_id=ops.id,
               kind=SubstitutionKind.PRIMARY,
               basis="Приказ ГД / решение участника; доверенность", note=None,
               valid_from=dt.date(2026, 1, 1), valid_to=None)
    svc.create(position_id=ceo.id, substitute_position_id=cfo.id,
               kind=SubstitutionKind.RESERVE, basis="Приказ ГД", note=None,
               valid_from=dt.date(2026, 1, 1), valid_to=None)
    return {"ceo": ceo, "ops": ops, "cfo": cfo}


def test_returns_exactly_the_agreed_keys(matrix):
    rows = interface.substitutes_for(matrix["ceo"].id, TODAY)
    assert [set(r) for r in rows] == [{"position_id", "kind", "basis"}] * 2


def test_primary_comes_first(matrix):
    rows = interface.substitutes_for(matrix["ceo"].id, TODAY)
    assert [r["kind"] for r in rows] == ["primary", "reserve"]
    assert rows[0]["position_id"] == matrix["ops"].id
    assert rows[0]["basis"] == "Приказ ГД / решение участника; доверенность"


def test_date_defaults_to_today(matrix):
    assert interface.substitutes_for(matrix["ceo"].id) == \
        interface.substitutes_for(matrix["ceo"].id, dt.date.today())


def test_position_without_rules_returns_empty_list(matrix):
    assert interface.substitutes_for(matrix["ops"].id, TODAY) == []


def test_unknown_position_returns_empty_list_not_an_error(matrix):
    """Сосед спрашивает про должность, которой в ЭТОЙ компании нет — это
    нормальный ответ «замещающих нет», а не отказ."""
    assert interface.substitutes_for(10_000_000, TODAY) == []


def test_expired_rule_is_not_returned(matrix):
    rows = interface.substitutes_for(matrix["ceo"].id, dt.date(2025, 1, 1))
    assert rows == []


def test_disabled_hr_refuses(matrix, monkeypatch):
    """Первая строка любой функции interface — require_service."""
    from apps.core import services as core_services

    monkeypatch.setattr(core_services, "service_status",
                        lambda name: (False, "выключено для проверки"))
    with pytest.raises(ServiceDisabled):
        interface.substitutes_for(matrix["ceo"].id, TODAY)
```

⚠️ Перед написанием шага 3 открой `apps/hr/interface.py` и посмотри, КАК там зовётся `require_service` и как устроен последний тест на выключенный сервис в `apps/hr/tests/` — подмена `service_status` в тесте выше должна совпадать с тем, что реально проверяет `require_service` в этом репозитории. Если подмена не срабатывает, приведи тест к тому приёму, который уже используется, а не изобретай свой.

- [ ] **Step 2: Убедиться, что падает**

Run: `../.venv/Scripts/python.exe -m pytest apps/hr/tests/test_interface_substitutes.py -q`
Expected: FAIL — `AttributeError: module 'apps.hr.interface' has no attribute 'substitutes_for'`.

- [ ] **Step 3: Функция интерфейса**

`backend/apps/hr/interface.py`, в конец файла:

```python
def substitutes_for(position_id: int, on_date: date | None = None) -> list[dict]:
    """Кто по регламенту замещает эту должность на эту дату (HR-FRM-006).

    Контракт для соседнего домена, зафиксированный в
    docs/plans/2026-09-14-group-structure-roadmap.md §6.1: РОВНО три ключа —
    ``position_id`` (должность замещающего), ``kind`` (``primary``/``reserve``),
    ``basis`` (чем оформлено: «Приказ ГД», «Приказ ГД; доверенность на банк»).
    Форма согласована с разработчиком signoff; расширять её в одиночку
    нельзя — лишний ключ здесь становится лишним ключом в чужом коде.

    Отвечает на вопрос «кто ВПРАВЕ подменить», а не «кто подменяет прямо
    сейчас»: отсутствие держателя (отпуск, болезнь) домен `hr` не
    моделирует вовсе, и решение «пора ли звать замещающего» принимает
    вызывающий.

    Действует в контексте ТЕКУЩЕЙ компании, как и остальные функции этого
    модуля: матрица замещения лежит в схеме компании. Чтобы спросить про
    должность другой компании, вызывающий сам входит в её схему через
    ``htqweb.tenancy.db.use_company`` — так же, как он уже делает ради
    ``get_positions_brief``.

    Неизвестная должность — пустой список, а не ошибка: «в этой компании
    такой должности нет» и «замещающих не назначено» для потребителя один и
    тот же ответ «звать некого».
    """
    require_service("hr")
    from apps.hr.services import substitution_service

    rows = substitution_service.active_for_position(position_id, on_date or date.today())
    return [{"position_id": row.substitute_position_id,
             "kind": row.kind,
             "basis": row.basis}
            for row in rows]
```

Импорт `date` добавить в шапку файла (`from datetime import date`), если его там ещё нет.

- [ ] **Step 4: Тесты зелёные + сторож границ**

Run: `../.venv/Scripts/python.exe -m pytest apps/hr/tests/test_interface_substitutes.py apps/core/tests/test_app_isolation.py -q`
Expected: все passed.

- [ ] **Step 5: Коммит**

```bash
git add backend/apps/hr/interface.py backend/apps/hr/tests/test_interface_substitutes.py
git commit -m "feat(hr): контракт substitutes_for для маршрутов согласования

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: HTTP — вложенный ресурс `positions/<id>/substitutions`

**Files:**
- Modify: `backend/apps/hr/schemas.py` (рядом с `LevelThresholdCreate`)
- Modify: `backend/apps/hr/views.py` (рядом с ручками должностей)
- Modify: `backend/apps/hr/urls.py` (секция `positions`)
- Test: `backend/apps/hr/tests/test_substitutions_api.py`

**Interfaces:**
- Consumes: `substitution_service` целиком.
- Produces (использует задача 5): `GET/POST /api/hr/v1/positions/<id>/substitutions`, `PATCH/DELETE /api/hr/v1/substitutions/<id>`; тело ответа — `substitution_service.serialize`.

- [ ] **Step 1: Написать падающий тест**

`backend/apps/hr/tests/test_substitutions_api.py`.

⚠️ Фикстуры `auth` и `admin_auth` объявлены **внутри** `apps/hr/tests/test_positions_api.py` (строки 41–60), а не в общем `conftest.py`, — то есть в новом файле их не будет. Скопируй обе дословно в начало своего файла вместе с тем, на чём они держатся (`auth_headers` из `apps/hr/tests/conftest.py` доступна всем тестам аппки и копирования не требует). Не переписывай их «по памяти» и не заводи третий способ аутентификации в тестах.

Тесты ниже опираются ровно на эти две фикстуры:

```python
"""HTTP матрицы замещения.

Права — как у остальных мутаций должности: читать может любой
аутентифицированный, править только платформенный администратор. Матрица
утверждается приказом ГД, и правка её каждым кадровиком противоречила бы
самому документу.
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.test import Client

from apps.hr.models import Department, Position, SubstitutionKind
from apps.hr.services import substitution_service as svc

BASE = "/api/hr/v1"


@pytest.fixture
def trio(db):
    dep = Department.objects.create(name="Руководство", path="upr")
    return {
        "ceo": Position.objects.create(title="Генеральный директор", department=dep, weight=10),
        "ops": Position.objects.create(title="Операционный директор", department=dep, weight=130),
        "cfo": Position.objects.create(title="Финансовый директор", department=dep, weight=110),
    }


def _body(trio, **over):
    body = {
        "substitute_position_id": trio["ops"].id,
        "kind": "primary",
        "basis": "Приказ ГД",
        "valid_from": "2026-01-01",
    }
    body.update(over)
    return body


@pytest.mark.django_db
def test_list_requires_jwt(trio):
    resp = Client().get(f"{BASE}/positions/{trio['ceo'].id}/substitutions")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_create_requires_admin(trio, auth):
    resp = Client().post(f"{BASE}/positions/{trio['ceo'].id}/substitutions",
                         data=_body(trio), content_type="application/json", **auth)
    assert resp.status_code == 403


@pytest.mark.django_db
def test_create_then_list(trio, admin_auth, auth):
    created = Client().post(f"{BASE}/positions/{trio['ceo'].id}/substitutions",
                            data=_body(trio), content_type="application/json",
                            **admin_auth)
    assert created.status_code == 201
    body = created.json()
    assert body["substitute_position_title"] == "Операционный директор"
    assert {"id", "position_id", "substitute_position_id",
            "substitute_position_title", "kind", "basis", "note",
            "valid_from", "valid_to", "created_at", "updated_at"} == set(body)

    listed = Client().get(f"{BASE}/positions/{trio['ceo'].id}/substitutions", **auth)
    assert listed.status_code == 200
    assert [r["id"] for r in listed.json()] == [body["id"]]


@pytest.mark.django_db
def test_both_url_spellings_work(trio, auth):
    """APPEND_SLASH=False — обе формы обязаны быть зарегистрированы."""
    for url in (f"{BASE}/positions/{trio['ceo'].id}/substitutions",
                f"{BASE}/positions/{trio['ceo'].id}/substitutions/"):
        assert Client().get(url, **auth).status_code == 200


@pytest.mark.django_db
def test_self_substitution_is_422(trio, admin_auth):
    resp = Client().post(f"{BASE}/positions/{trio['ceo'].id}/substitutions",
                         data=_body(trio, substitute_position_id=trio["ceo"].id),
                         content_type="application/json", **admin_auth)
    assert resp.status_code == 422
    assert "сама себя" in resp.json()["detail"]


@pytest.mark.django_db
def test_overlap_is_409_and_says_what_to_do(trio, admin_auth):
    Client().post(f"{BASE}/positions/{trio['ceo'].id}/substitutions",
                  data=_body(trio), content_type="application/json", **admin_auth)
    resp = Client().post(f"{BASE}/positions/{trio['ceo'].id}/substitutions",
                         data=_body(trio, substitute_position_id=trio["cfo"].id,
                                    valid_from="2026-06-01"),
                         content_type="application/json", **admin_auth)
    assert resp.status_code == 409
    assert "датой окончания" in resp.json()["detail"]


@pytest.mark.django_db
def test_unknown_substitute_position_is_404(trio, admin_auth):
    resp = Client().post(f"{BASE}/positions/{trio['ceo'].id}/substitutions",
                         data=_body(trio, substitute_position_id=10_000_000),
                         content_type="application/json", **admin_auth)
    assert resp.status_code == 404


@pytest.mark.django_db
def test_patch_closes_the_period(trio, admin_auth):
    row = svc.create(position_id=trio["ceo"].id,
                     substitute_position_id=trio["ops"].id,
                     kind=SubstitutionKind.PRIMARY, basis="Приказ ГД", note=None,
                     valid_from=dt.date(2026, 1, 1), valid_to=None)
    resp = Client().patch(f"{BASE}/substitutions/{row.id}",
                          data={"valid_to": "2026-05-31"},
                          content_type="application/json", **admin_auth)
    assert resp.status_code == 200
    assert resp.json()["valid_to"] == "2026-05-31"


@pytest.mark.django_db
def test_delete_then_404(trio, admin_auth):
    row = svc.create(position_id=trio["ceo"].id,
                     substitute_position_id=trio["ops"].id,
                     kind=SubstitutionKind.PRIMARY, basis="Приказ ГД", note=None,
                     valid_from=dt.date(2026, 1, 1), valid_to=None)
    assert Client().delete(f"{BASE}/substitutions/{row.id}", **admin_auth).status_code == 204
    assert Client().delete(f"{BASE}/substitutions/{row.id}", **admin_auth).status_code == 404


@pytest.mark.django_db
def test_valid_to_before_valid_from_is_422(trio, admin_auth):
    resp = Client().post(f"{BASE}/positions/{trio['ceo'].id}/substitutions",
                         data=_body(trio, valid_from="2026-06-01", valid_to="2026-01-01"),
                         content_type="application/json", **admin_auth)
    assert resp.status_code == 422
```

- [ ] **Step 2: Убедиться, что падает**

Run: `../.venv/Scripts/python.exe -m pytest apps/hr/tests/test_substitutions_api.py -q`
Expected: FAIL — 404 на всех путях (роутов ещё нет).

- [ ] **Step 3: Схемы**

`backend/apps/hr/schemas.py`, рядом с `LevelThresholdCreate`:

```python
class SubstitutionCreate(BaseModel):
    substitute_position_id: int
    kind: Literal["primary", "reserve"] = "primary"
    basis: str = Field(..., min_length=1, max_length=255)
    note: str | None = Field(default=None, max_length=255)
    valid_from: date
    valid_to: date | None = None

    @model_validator(mode="after")
    def _period_is_sane(self):
        # Тот же инвариант, что в CheckConstraint модели: 422 из схемы
        # понятнее клиенту, чем 500 из БД.
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError("valid_to не может быть раньше valid_from")
        return self


class SubstitutionUpdate(BaseModel):
    substitute_position_id: int | None = None
    kind: Literal["primary", "reserve"] | None = None
    basis: str | None = Field(default=None, min_length=1, max_length=255)
    note: str | None = Field(default=None, max_length=255)
    valid_from: date | None = None
    valid_to: date | None = None
```

⚠️ Проверь, что `date`, `Literal` и `model_validator` уже импортированы в этом файле; если нет — добавь в существующие строки импортов, не заводя новых блоков.

- [ ] **Step 4: Вьюхи**

`backend/apps/hr/views.py`, после ручек должности (рядом с `position_detail`):

```python
# ── /positions/{id}/substitutions — матрица замещения (блок E) ────────────

def _substitution_error(exc: sub_svc.SubstitutionError):
    """Одна точка перевода доменной ошибки в HTTP: каждая ошибка сервиса
    несёт свой status и detail, и дублировать таблицу соответствий в каждой
    вьюхе не нужно."""
    return json_error(exc.detail, exc.status)


@api_view(methods=("GET",), auth="jwt")
def _list_substitutions(request, id: int):
    return [sub_svc.serialize(row) for row in sub_svc.list_for_position(id)]


@api_view(methods=("POST",), auth="jwt", admin=True,
          body=schemas.SubstitutionCreate, status=201)
def _create_substitution(request, id: int, data: schemas.SubstitutionCreate):
    try:
        row = sub_svc.create(
            position_id=id, substitute_position_id=data.substitute_position_id,
            kind=data.kind, basis=data.basis, note=data.note,
            valid_from=data.valid_from, valid_to=data.valid_to,
        )
    except sub_svc.SubstitutionError as exc:
        return _substitution_error(exc)
    return sub_svc.serialize(row)


def position_substitutions(request, id: int):
    if request.method == "GET":
        return _list_substitutions(request, id=id)
    if request.method == "POST":
        return _create_substitution(request, id=id)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("PATCH",), auth="jwt", admin=True, body=schemas.SubstitutionUpdate)
def _update_substitution(request, sub_id: int, data: schemas.SubstitutionUpdate):
    fields = data.model_dump(exclude_unset=True)
    try:
        row = sub_svc.update(sub_id, **fields)
    except sub_svc.SubstitutionError as exc:
        return _substitution_error(exc)
    return sub_svc.serialize(row)


@api_view(methods=("DELETE",), auth="jwt", admin=True)
def _delete_substitution(request, sub_id: int):
    try:
        sub_svc.delete(sub_id)
    except sub_svc.SubstitutionError as exc:
        return _substitution_error(exc)
    return HttpResponse(status=204)


def substitution_detail(request, sub_id: int):
    if request.method == "PATCH":
        return _update_substitution(request, sub_id=sub_id)
    if request.method == "DELETE":
        return _delete_substitution(request, sub_id=sub_id)
    return json_error("Method Not Allowed", 405)
```

Импорт сервиса добавить туда же, где импортируются остальные (`from apps.hr.services import substitution_service as sub_svc`) — посмотри, как в этом файле назван импорт `position_service` (`pos_svc`), и повтори приём.

- [ ] **Step 5: Роуты**

`backend/apps/hr/urls.py`, в секции `positions`, ПОСЛЕ `positions/<int:id>/` и рядом с прочими вложенными путями:

```python
    # Матрица замещения (блок E). Обе формы пути — APPEND_SLASH=False.
    path("positions/<int:id>/substitutions", views.position_substitutions),
    path("positions/<int:id>/substitutions/", views.position_substitutions),
    path("substitutions/<int:sub_id>", views.substitution_detail),
    path("substitutions/<int:sub_id>/", views.substitution_detail),
```

- [ ] **Step 6: Тесты зелёные**

Run: `../.venv/Scripts/python.exe -m pytest apps/hr/tests/test_substitutions_api.py apps/hr/tests/test_positions_api.py -q`
Expected: все passed. `test_positions_api` обязан остаться зелёным — если он упал на наборе ключей `PositionOut`, значит кто-то полез в сериализацию должности; откатить это.

- [ ] **Step 7: Коммит**

```bash
git add backend/apps/hr/schemas.py backend/apps/hr/views.py backend/apps/hr/urls.py backend/apps/hr/tests/test_substitutions_api.py
git commit -m "feat(hr): матрица замещения правится через API должности

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Фронт — секция «Замещение» на карточке должности

**Files:**
- Modify: `frontend/src/api/hr.ts` (рядом с функциями должностей)
- Create: `frontend/src/components/hr/PositionSubstitutions.tsx`
- Modify: `frontend/src/pages/hr/HRPositions.tsx` (подключение секции в диалог должности)
- Modify: `frontend/public/locales/ru/translation.json`, `frontend/public/locales/en/translation.json`
- Test: `frontend/src/components/hr/__tests__/PositionSubstitutions.test.tsx`

**Interfaces:**
- Consumes: ручки задачи 4.
- Produces: компонент `<PositionSubstitutions positionId={number} positions={Position[]} />`.

- [ ] **Step 1: Клиент API**

`frontend/src/api/hr.ts`, после `deletePosition`:

```ts
/* ---------- Замещение (HR-FRM-006) ---------- */

export type SubstitutionKind = 'primary' | 'reserve';

export interface Substitution {
  id: number;
  position_id: number;
  substitute_position_id: number;
  substitute_position_title: string;
  kind: SubstitutionKind;
  basis: string;
  note: string | null;
  valid_from: string;
  valid_to: string | null;
  created_at: string;
  updated_at: string;
}

export interface SubstitutionInput {
  substitute_position_id: number;
  kind: SubstitutionKind;
  basis: string;
  note?: string | null;
  valid_from: string;
  valid_to?: string | null;
}

export const fetchSubstitutions = async (positionId: number): Promise<Substitution[]> => {
  const res = await api.get(`${HR}positions/${positionId}/substitutions`);
  return unwrap<Substitution>(res.data);
};

export const createSubstitution = async (
  positionId: number, data: SubstitutionInput,
): Promise<Substitution> => {
  const res = await api.post(`${HR}positions/${positionId}/substitutions`, data);
  return res.data;
};

export const updateSubstitution = async (
  id: number, data: Partial<SubstitutionInput>,
): Promise<Substitution> => {
  const res = await api.patch(`${HR}substitutions/${id}`, data);
  return res.data;
};

export const deleteSubstitution = async (id: number): Promise<void> => {
  await api.delete(`${HR}substitutions/${id}`);
};
```

- [ ] **Step 2: Написать падающий тест**

`frontend/src/components/hr/__tests__/PositionSubstitutions.test.tsx`. Возьми за образец способ подмены API и рендера из `frontend/src/components/hr/OrgChart/ExternalHierarchy.test.tsx` (он уже мокает модуль api и рендерит через `renderWithProviders`):

```tsx
/**
 * Секция замещения на карточке должности.
 *
 * Проверяем не разметку, а три вещи, ради которых секция существует:
 * правило видно со всеми колонками документа (кто, каким приказом, до
 * какой даты), истёкшее правило отличимо от действующего, и ошибка
 * пересечения от сервера показывается человеку, а не глотается.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/renderWithProviders';
import { PositionSubstitutions } from '../PositionSubstitutions';
import * as hrApi from '@/api/hr';

vi.mock('@/api/hr', async (importOriginal) => {
  const actual = await importOriginal<typeof hrApi>();
  return { ...actual, fetchSubstitutions: vi.fn(), createSubstitution: vi.fn(),
           deleteSubstitution: vi.fn() };
});

const POSITIONS = [
  { id: 1, title: 'Генеральный директор' },
  { id: 2, title: 'Операционный директор' },
  { id: 3, title: 'Финансовый директор' },
] as hrApi.Position[];

const ROW = {
  id: 10, position_id: 1, substitute_position_id: 2,
  substitute_position_title: 'Операционный директор',
  kind: 'primary' as const, basis: 'Приказ ГД; доверенность',
  note: 'Право первой подписи', valid_from: '2026-01-01', valid_to: null,
  created_at: '2026-01-01T00:00:00', updated_at: '2026-01-01T00:00:00',
};

beforeEach(() => vi.clearAllMocks());

describe('PositionSubstitutions', () => {
  it('показывает замещающего, вид, основание и примечание', async () => {
    vi.mocked(hrApi.fetchSubstitutions).mockResolvedValue([ROW]);
    renderWithProviders(<PositionSubstitutions positionId={1} positions={POSITIONS} />);

    expect(await screen.findByText('Операционный директор')).toBeInTheDocument();
    expect(screen.getByText(/Основной/)).toBeInTheDocument();
    expect(screen.getByText(/Приказ ГД; доверенность/)).toBeInTheDocument();
    expect(screen.getByText(/Право первой подписи/)).toBeInTheDocument();
  });

  it('пустая матрица объясняет себя, а не показывает пустоту', async () => {
    vi.mocked(hrApi.fetchSubstitutions).mockResolvedValue([]);
    renderWithProviders(<PositionSubstitutions positionId={1} positions={POSITIONS} />);
    expect(await screen.findByText(/замещающих не назначено/i)).toBeInTheDocument();
  });

  it('истёкшее правило помечено, а не выглядит действующим', async () => {
    vi.mocked(hrApi.fetchSubstitutions).mockResolvedValue([
      { ...ROW, valid_to: '2025-12-31' },
    ]);
    renderWithProviders(<PositionSubstitutions positionId={1} positions={POSITIONS} />);
    expect(await screen.findByText(/истекло/i)).toBeInTheDocument();
  });

  it('ошибку пересечения от сервера показывает человеку', async () => {
    vi.mocked(hrApi.fetchSubstitutions).mockResolvedValue([]);
    vi.mocked(hrApi.createSubstitution).mockRejectedValue({
      response: { status: 409, data: { detail: 'У этой должности уже есть замещающий' } },
    });
    renderWithProviders(<PositionSubstitutions positionId={1} positions={POSITIONS} />);

    await userEvent.click(await screen.findByRole('button', { name: /добавить/i }));
    await userEvent.type(screen.getByLabelText(/основание/i), 'Приказ ГД');
    await userEvent.click(screen.getByRole('button', { name: /сохранить/i }));

    await waitFor(() =>
      expect(screen.getByText(/уже есть замещающий/i)).toBeInTheDocument());
  });
});
```

Run (из `frontend/`): `npx vitest run src/components/hr/__tests__/PositionSubstitutions.test.tsx`
Expected: FAIL — модуля `PositionSubstitutions` нет.

- [ ] **Step 3: Компонент**

Создай `frontend/src/components/hr/PositionSubstitutions.tsx`. Требования к нему (разметку делай по образцу соседних секций карточки должности в `HRPositions.tsx` — те же `Label`, `Select`, `Input`, `Button` из `@/components/ui/*`):

- список строк, у каждой: название замещающей должности, бейдж вида («Основной» / «Резервный»), основание, примечание, период `valid_from — valid_to || «бессрочно»`;
- строка с прошедшей `valid_to` помечена словом «истекло» и приглушена;
- пустой список даёт строку «Замещающих не назначено» с пояснением, что матрица утверждается приказом;
- форма добавления: выбор должности (из пропса `positions`, исключая саму `positionId`), вид, основание (обязательное), примечание, дата начала (по умолчанию сегодня), дата окончания (пустая = бессрочно);
- удаление строки — с подтверждением;
- ошибка сервера показывается текстом из `detail`, а не проглатывается: у 409 (пересечение) в теле лежит инструкция, что делать, и она нужна человеку дословно;
- данные через TanStack Query: `useQuery({ queryKey: ['hr','substitutions',positionId] })`, мутации инвалидируют этот ключ;
- все подписи через `t('hr.substitutions.<key>', 'русский текст')`.

- [ ] **Step 4: Подключить секцию**

В `frontend/src/pages/hr/HRPositions.tsx` добавить секцию в диалог должности — **только при редактировании существующей** (`editingPos?.id != null`): у несохранённой должности нет id, и замещать некого. Рядом поставить поясняющую строку, что матрица замещения действует для маршрутов согласования.

- [ ] **Step 5: Локали**

Добавить ветку `hr.substitutions.*` в оба файла `frontend/public/locales/{ru,en}/translation.json` — по одному ключу на каждую подпись компонента. Правку делать точечно, отступы и кодировку файла не менять.

- [ ] **Step 6: Проверки фронта**

Run: `npx vitest run src/components/hr/__tests__/PositionSubstitutions.test.tsx src/lib/i18n/__tests__/translationKeys.test.ts`
Expected: оба файла зелёные (второй — сторож «ключ есть в ru»).
Run: `npx tsc --noEmit -p tsconfig.app.json 2>&1 | tail -1` — не больше 150 ошибок.

- [ ] **Step 7: Коммит**

```bash
git add frontend/src/api/hr.ts frontend/src/components/hr/PositionSubstitutions.tsx frontend/src/components/hr/__tests__/PositionSubstitutions.test.tsx frontend/src/pages/hr/HRPositions.tsx frontend/public/locales/ru/translation.json frontend/public/locales/en/translation.json
git commit -m "feat(hr): матрица замещения правится на карточке должности

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Матрица HR-FRM-006 в демо-стенде

**Files:**
- Modify: `backend/apps/hr/management/group_structures.py`
- Modify: `backend/apps/hr/management/commands/seed_hr_demo.py`
- Test: `backend/apps/hr/tests/test_group_structures.py`, `backend/apps/hr/tests/test_seed_hr_demo.py`

**Interfaces:**
- Consumes: `Structure` из задачи блока D, `substitution_service.create`.
- Produces: поле `Structure.substitutions: tuple[SubstitutionRow, ...]` и шаг `_seed_substitutions` в команде.

- [ ] **Step 1: Данные и падающий тест**

В `group_structures.py` добавить датакласс и заполнить его ТОЛЬКО для холдинга:

```python
@dataclass(frozen=True)
class SubstitutionRow:
    """Строка HR-FRM-006. ``document_title`` — как замещающий назван В
    ДОКУМЕНТЕ, ``substitute`` — как называется соответствующая должность в
    утверждённой оргструктуре. Они расходятся (roadmap §8.2, вопрос
    руководству), и пока ответа нет, соответствие обязано быть видимым, а не
    растворённым в данных."""

    position: str
    substitute: str
    document_title: str
    kind: str
    basis: str
    note: str = ""
```

Матрица холдинга (порядок строк — как в документе):

```python
    substitutions=(
        SubstitutionRow("Генеральный директор", "Операционный директор",
                        "Операционный директор", "primary",
                        "Приказ ГД / решение участника; доверенность",
                        "Право первой подписи по доверенности"),
        SubstitutionRow("Генеральный директор", "Финансовый директор",
                        "Финансовый директор (CFO)", "reserve",
                        "Приказ ГД / решение участника; доверенность",
                        "Право первой подписи по доверенности"),
        SubstitutionRow("Финансовый директор", "Главный бухгалтер",
                        "Главный бухгалтер", "primary",
                        "Приказ ГД; доверенность на банк",
                        "Казначейские операции — по лимитам"),
        SubstitutionRow("Финансовый директор", "Экономист-аналитик",
                        "Экономист", "reserve",
                        "Приказ ГД; доверенность на банк",
                        "Казначейские операции — по лимитам"),
        SubstitutionRow("Технический директор", "Менеджер ПТО и КК",
                        "Специалист ПТО", "primary", "Приказ ГД"),
        SubstitutionRow("Технический директор", "Операционный директор",
                        "Операционный директор", "reserve", "Приказ ГД"),
        SubstitutionRow("Операционный директор", "Менеджер по кадрам",
                        "HR-специалист", "primary", "Приказ ГД"),
        SubstitutionRow("Операционный директор", "Финансовый директор",
                        "Финансовый директор (CFO)", "reserve", "Приказ ГД"),
        SubstitutionRow("Главный бухгалтер", "Бухгалтер",
                        "Бухгалтер", "primary", "Приказ ГД",
                        "Право подписи отчётности — по приказу"),
        SubstitutionRow("Главный бухгалтер", "Экономист-аналитик",
                        "Экономист", "reserve", "Приказ ГД",
                        "Право подписи отчётности — по приказу"),
    )
```

Остальным трём структурам — `substitutions=()`: документ описывает матрицу только для управляющей компании.

⚠️ **Строка «Системный администратор» не входит** — документ называет его замещающим «Внутригрупповой ИТ-подрядчик», а это не должность и не пользователь платформы. Это решение 6 плана; оно закрепляется тестом ниже и печатается командой в задаче 2 этого шага.

Тесты в `test_group_structures.py`:

```python
def test_substitution_matrix_matches_the_document():
    """Десять строк HR-FRM-006, литералами. Одиннадцатая («Системный
    администратор» → «Внутригрупповой ИТ-подрядчик») намеренно отсутствует:
    подрядчик — не должность."""
    actual = {(r.position, r.kind, r.substitute) for r in HOLDING.substitutions}
    assert actual == {
        ("Генеральный директор", "primary", "Операционный директор"),
        ("Генеральный директор", "reserve", "Финансовый директор"),
        ("Финансовый директор", "primary", "Главный бухгалтер"),
        ("Финансовый директор", "reserve", "Экономист-аналитик"),
        ("Технический директор", "primary", "Менеджер ПТО и КК"),
        ("Технический директор", "reserve", "Операционный директор"),
        ("Операционный директор", "primary", "Менеджер по кадрам"),
        ("Операционный директор", "reserve", "Финансовый директор"),
        ("Главный бухгалтер", "primary", "Бухгалтер"),
        ("Главный бухгалтер", "reserve", "Экономист-аналитик"),
    }
    assert not any(r.position == "Специалист технической поддержки"
                   for r in HOLDING.substitutions)


def test_every_substitution_names_real_positions_of_its_structure():
    for structure in gs.STRUCTURES.values():
        titles = {p.title for p in structure.posts}
        for row in structure.substitutions:
            assert row.position in titles, (structure.kind, row.position)
            assert row.substitute in titles, (structure.kind, row.substitute)
            assert row.position != row.substitute


def test_only_the_holding_has_a_substitution_matrix():
    """Документ описывает матрицу только для управляющей компании."""
    for kind in ("construction", "it", "service"):
        assert gs.STRUCTURES[kind].substitutions == ()


def test_document_titles_are_preserved_where_they_differ():
    """Расхождение названий (roadmap §8.2) обязано быть видимым: пока
    руководство не ответило, оригинал документа хранится рядом."""
    differing = {(r.document_title, r.substitute) for r in HOLDING.substitutions
                 if r.document_title != r.substitute}
    assert differing == {
        ("Финансовый директор (CFO)", "Финансовый директор"),
        ("Экономист", "Экономист-аналитик"),
        ("Специалист ПТО", "Менеджер ПТО и КК"),
        ("HR-специалист", "Менеджер по кадрам"),
    }
```

- [ ] **Step 2: Убедиться, что падает**

Run: `../.venv/Scripts/python.exe -m pytest apps/hr/tests/test_group_structures.py -q`
Expected: FAIL — у `Structure` нет поля `substitutions`.

- [ ] **Step 3: Шаг сида**

В `seed_hr_demo.py` добавить шаг после `_seed_relations` (замещения ссылаются на должности, но не на связи подчинения — порядок между ними безразличен, важно лишь что должности уже есть):

```python
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
        «Внутригруппового ИТ-подрядчика» — это не должность и не
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
```

Вызвать шаг из `_run` и добавить его число в итоговую строку. Импортировать `Substitution` в шапку файла к остальным моделям.

- [ ] **Step 4: Тест сида**

В `test_seed_hr_demo.py` добавить:

```python
def test_holding_seed_lays_out_the_substitution_matrix(company_schema):
    from django.core.cache import cache

    from apps.companies.models import Company
    from apps.hr.models import Substitution
    from htqweb.tenancy.db import use_company

    Company.objects.filter(slug=company_schema["slug"]).update(kind="holding")
    cache.clear()
    _seed(company=company_schema["slug"])
    with use_company(company_schema["slug"]):
        assert Substitution.objects.count() == 10
        assert Substitution.objects.filter(kind="primary").count() == 5
        ceo = Substitution.objects.get(position__title="Генеральный директор",
                                       kind="primary")
        assert ceo.substitute_position.title == "Операционный директор"
        assert ceo.basis.startswith("Приказ ГД / решение участника")
        assert not Substitution.objects.filter(
            position__title="Специалист технической поддержки").exists()


def test_substitution_seed_is_idempotent(company_schema):
    from django.core.cache import cache

    from apps.companies.models import Company
    from apps.hr.models import Substitution
    from htqweb.tenancy.db import use_company

    Company.objects.filter(slug=company_schema["slug"]).update(kind="holding")
    cache.clear()
    _seed(company=company_schema["slug"])
    _seed(company=company_schema["slug"])
    with use_company(company_schema["slug"]):
        assert Substitution.objects.count() == 10


@pytest.mark.django_db
def test_construction_structure_has_no_substitutions():
    _seed()
    from apps.hr.models import Substitution
    assert Substitution.objects.count() == 0
```

- [ ] **Step 5: Прогон**

Run: `../.venv/Scripts/python.exe -m pytest apps/hr/tests/test_group_structures.py apps/hr/tests/test_seed_hr_demo.py -q`
Expected: все passed.

- [ ] **Step 6: Коммит**

```bash
git add backend/apps/hr/management/group_structures.py backend/apps/hr/management/commands/seed_hr_demo.py backend/apps/hr/tests/test_group_structures.py backend/apps/hr/tests/test_seed_hr_demo.py
git commit -m "feat(hr): матрица замещения документа в демо-стенде холдинга

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Сквозная проверка и документы

**Files:**
- Modify: `API.md` (раздел `hr`), `STRUCTURE.md` (состав `apps/hr`), `CLAUDE.md` (абзац про замещение), `docs/plans/2026-09-14-group-structure-roadmap.md` (§4 таблица «Замещение», §5.E → «выполнено», §6.1 статус строки `hr.substitutes_for`, §7 шаг 3)

- [ ] **Step 1: Прогоны (гонит КОНТРОЛЛЕР, не исполнитель)**

`../.venv/Scripts/python.exe -m pytest -q` — полный сьют, ожидается ровно 8 известных падений.
Из `frontend/`: `npx vitest run` (8 базовых падений) и `npx tsc --noEmit -p tsconfig.app.json` (150).

- [ ] **Step 2: Сквозной прогон на dev-базе**

Из `backend/`, с длинной строкой переменных окружения (см. CLAUDE.md, раздел «Reaching the dev database from the host»):

```
manage.py migrate_companies --company hi-tech-group     # hr/0025 в схему холдинга
manage.py seed_hr_demo --company hi-tech-group          # матрица документа
manage.py tenancy_status
```

Затем проверить через Bash (не PowerShell):

```bash
docker exec htqweb-local-db-1 psql -U htqweb -d htqweb -At -c "
select p.title, s.kind, sp.title, s.basis
from co_hi_tech_group.hr_substitution s
join co_hi_tech_group.hr_position p on p.id = s.position_id
join co_hi_tech_group.hr_position sp on sp.id = s.substitute_position_id
order by p.weight, s.kind;"
```
Expected: 10 строк, ровно матрица документа.

- [ ] **Step 3: Документы**

`API.md`, раздел `hr` — добавить четыре ручки (`GET/POST positions/{id}/substitutions`, `PATCH/DELETE substitutions/{id}`) с правами: чтение — JWT, запись — администратор.

`STRUCTURE.md`, состав `apps/hr` — упомянуть `services/substitution_service.py` и модель `Substitution` одной строкой.

`CLAUDE.md`, в раздел «Мультикомпанейность» после абзаца о наследовании прав:

«**Замещение ключевых должностей** — `hr.Substitution` (HR-FRM-006, миграция `hr/0025`): кто замещает должность, каким приказом это оформлено и в какой период действует правило. Замещающий — **должность**, а не человек: так правило переживает смену держателя. Наружу отдаётся одной функцией `hr.interface.substitutes_for(position_id, on_date)` (ровно три ключа — `position_id`, `kind`, `basis`), которую зовут маршруты согласования. Это ПРАВИЛО, а не отсутствие: домен `hr` отпуска и болезни не моделирует, и решение «пора ли звать замещающего» принимает вызывающий. Неактивные замещающие должности из ответа исключаются — маршрут не должен упираться в тупик.»

Roadmap: §4 строка «Замещение» → «✅ `hr.Substitution` + `substitutes_for`» / расхождение «названия должностей в HR-FRM-006 и оргструктуре расходятся (§8.2); строка «Системный администратор → внутригрупповой ИТ-подрядчик» не выражается должностью». §5.E — «(выполнено)» и три строки о сделанном. §6.1 — статус строки `hr.substitutes_for` с «новое (E)» на «есть, блок E». §7 шаг 3 — упомянуть `hr/0025` в списке того, что доводится `migrate_companies`.

- [ ] **Step 4: Коммит**

```bash
git add API.md STRUCTURE.md CLAUDE.md docs/plans/2026-09-14-group-structure-roadmap.md
git commit -m "docs: блок E закрыт — матрица замещения и контракт для согласований

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Self-review

**Покрытие спеки (roadmap §5.E):**
- «`hr.Substitution(position, substitute_position, kind=primary|reserve, basis, valid_from, valid_to)`» → задача 1. Добавлено поле `note` сверх перечисленного: в документе есть колонка «Примечание», которая ограничивает права замещающего («Право первой подписи по доверенности»), и терять её нельзя.
- «UI на карточке должности» → задача 5.
- «`apps.hr.interface.substitutes_for(position_id, on_date) -> list[dict]` — контракт для signoff (§6)» → задача 3; форма ответа взята из §6.1 дословно и закреплена тестом на точный набор ключей.
- Сверх спеки: сид матрицы в демо-стенд (задача 6) — иначе блок нечего показать заказчику, а расхождение названий останется невидимым.

**Заглушек нет:** весь код задач 1–4 и 6 приведён целиком; в задаче 5 разметка компонента описана требованиями, а не кодом, — сознательно: она обязана повторять соседние секции того же диалога, и копия чужой разметки в плане устарела бы раньше, чем её прочтут. Тесты задачи 5 приведены полностью и задают поведение однозначно.

**Согласованность имён:** `Substitution`/`SubstitutionKind` (1→2,3,4,6), `substitution_service.{serialize,list_for_position,active_for_position,create,update,delete}` (2→3,4,6), исключения с `status`/`detail` (2→4), `substitutes_for` три ключа (3, §6.1), `SubstitutionRow.{position,substitute,document_title,kind,basis,note}` (6), `fetchSubstitutions`/`createSubstitution`/`updateSubstitution`/`deleteSubstitution` (5).

**Риски, названные заранее:** расхождение названий должностей между HR-FRM-006 и оргструктурой — открытый вопрос руководству, в коде закреплено видимым соответствием; строка «Системный администратор» документа не выражается должностью и не сеется; `Substitution` не входит в `HOLDING_MODELS` (сводное чтение матрицы по группе не заказывалось).
