# БЗО, этап 2 — исполнитель B (Руслан, ветка `new-module-BPP-ruslan`)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Первая половина денежной цепочки модуля:
- **бюджет проекта** — версии, корректировка, закрытие;
- **расчёт «задействовано»** — от заявок, с ночной сверкой;
- **заявка на закупку** — черновик, отправка с контролем остатка под блокировкой, маршрут ТД → ОД, отзыв, отмена, копирование, печать;
- **план закупок** — позиции утверждённых заявок, проверка выбора, переназначение исполнителя;
- **экраны** этих документов на каркасе исполнителя A.

**Architecture:**
- **Где лежит код.** Три подмодуля `apps/bpp` исполнителя B:
  - `budget` — модели `models/budget.py`, сервисы `services/budget/`, ручки `views_budget.py`/`urls_budget.py`;
  - `requests` — `models/requests.py`, `services/requests/`, `views_requests.py`/`urls_requests.py`;
  - `plan` — `services/plan/`, `views_plan.py`/`urls_plan.py`.

  Подключаются сами (задача 1 плана A): общих файлов с A нет.
- **Бюджет без маршрута.** Утверждение и корректировка — прямое действие ФД (D-07).
- **Заявка через signoff.** Согласуется предметом `bpp.purchase_request` с флагами маршрута этапа 1 (B1.2): запрет самосогласования, комментарий ≥ 10 при отказе и возврате, ленивое разрешение исполнителя.
- **«Задействовано»** считается из источника (позиции заявок; договоры и счета добавит этап 3) и хранится кэшем в строке бюджета.
  - Кэш пересчитывается в той же транзакции, что и переход статуса. Остаток проверяется под `SELECT … FOR UPDATE` строки бюджета (BR-011).
  - Ночная задача сравнивает кэш с пересчётом и пишет `fallback` при расхождении (D-08, CALC-002).
- **Каждый документ регистрируется** в `services/core/owners.register` — так он получает файлы и журнал с проверкой доступа (задача 4 плана A).

**Tech Stack:** Django 5.2.7, PostgreSQL (схема на компанию), Celery + django-celery-beat, pytest-django; React 18 + TypeScript + react-query, vitest.

**Spec:** [мастер-план](2026-09-26-bpp-master-plan.md): §1 (D-06, D-07, D-08, D-10, D-21, D-28, D-29), §2.4–2.6, §4 (Review Focus 1, 2, 5), §5 «Этап 2» (B2.1–B2.5); ТЗ [§06–§08](../tz/TZ-budget-procurement-payments-v1.0.md), §13, §14 (BR-001…004, BR-010…014, BR-020, BR-021, BR-060, BR-061), §15.1–15.2, §19, §20 (CALC-001…006), §22, §23, §26, §29 (AC-001…AC-004).

**Как задачи соотносятся с мастер-планом:**

| Мастер-план | Этот план |
|---|---|
| — (стык этапа 1: уведомления signoff через центр, маршрут БЗО) | задача 1 |
| B2.1 | задача 2 |
| B2.4 | задача 3 |
| B2.2 | задачи 4, 5 |
| B2.3 | задача 6 |
| B2.5 | задача 7 |

## Порядок, волны и сведение веток

Ветки сводятся через `new-module-BPP-merge` (CLAUDE.md, «Модуль БЗО»).

- **До старта этапа** в `new-module-BPP-merge` сведены этапы 0 и 1 обоих исполнителей, обе ветки его подтянули. Без этого нет ядра `bpp`, прав `permissions.can`, `refdata`, `project`, центра уведомлений (этап 1 A) и строкового `subject_id` с флагами маршрута (этапы 0–1 B).
- **Волна 1** — задачи 1–6 (бэкенд). Параллельно A делает каркас фронта, контрагентов, экспорт и печать.
- **Сведение внутри этапа.**
  - PR обеих веток в `new-module-BPP-merge`, затем обе подтягивают.
  - У A и B будут миграции `bpp` от одного родителя `0002_files`. Второй PR сначала подтягивает `new-module-BPP-merge` и добавляет `manage.py makemigrations bpp --merge`.
  - Задачам 2–6 из плана A нужны `services/core/registry.py`, `owners.py`, `money.py`, `export.py`, `printing.py`. **Если волна 1 A ещё не сведена, а B уже на задаче 2, B временно пишет без них**: пагинация — `page`/`page_size` вручную, файлы и журнал — без регистрации, печать — без PDF. После сведения B переводит код на общие модули отдельным коммитом.
- **Волна 2** — задача 7 (экраны) на каркасе A (`BppRegistry`, `BppDocumentShell`, хуки).

---

## Global Constraints

- Интерпретатор — корневой `.venv`; команды из `backend/`: `../.venv/Scripts/python.exe …`. **Один прогон pytest за раз на машине.**
- Ветки не создавать. Коммитить только файлы своей задачи. Файлы A (`bpp/models/__init__.py`, `bpp/urls.py`, `bpp/views.py`, `services/core/*`, `features/bpp/core/*`, `features/bpp/modules.ts`) не править — нужна правка, присылать A.
- Межаппный доступ — только `apps.<x>.interface`: `project`, `refdata`, `signoff`, `notifications`, `hr`. Внутри `bpp` — через функции подмодуля (`services/counterparties/lookup.py` и т. п.), модели соседнего подмодуля не менять.
- Ручки — `api_view(module="bpp", level=…)` с явным уровнем; права тоньше модуля — `services/core/permissions.can(request, node, flag)`; группы статей — `permissions.article_groups_for(request)`.
- Записывающие ручки документов — `idempotent=True` и поле `version` в теле (`check_version` → 409 E-CON-01). Изменение `version` — `+1` при каждой записи документа.
- Деньги — `Decimal(18,2)`, количество — `Decimal(15,3)`, округление `ROUND_HALF_UP` до 0,01 (`services/core/money.py`, план A). На проводе — строки.
- «Сегодня» — `django.utils.timezone.localdate()` (сторож `apps/core/tests/test_platform_today.py`).
- Тексты ошибок — дословно из ТЗ §26.1 и примеров BR с подстановкой; суммы в текстах — `money.format_money` (`1 250 000,00 KZT`).
- Физически удаляются только черновики (BR-080); удаление — запись в аудит.
- Переходы статусов — только таблицы ТЗ §15.1–15.2; прочие → 409 `E-STS-01` «Нельзя {действие} {документ} в статусе „{статус}“».
- `bpp` тенантная: миграции схем — `manage.py migrate_companies`; ссылки на соседние аппки — строками UUID без FK (`project_id`, `article_id`, `uom_id`).
- Новые строки фронта — `t('bpp.<ключ>', 'Русский текст')`; `tsc` без новых ошибок; ошибки в `onError` — `reportApiError`.

**Коды ошибок этапа** (новые — в каталог `API.md`):

| Код | Когда | Текст |
|---|---|---|
| E-BUD-01 | Сумма заявки > остатка (BR-011) | ТЗ §26.1 дословно, суммы и статья с подстановкой |
| E-BUD-02 | Нет утверждённого бюджета (BR-003) | ТЗ §26.1 |
| E-BUD-03 | Второй бюджет проекта (BR-001) | «У проекта {код} уже есть бюджет {номер}. Откройте его и выполните корректировку.» (ТЗ §6.5 п.4) + `fields[0].existing_id` |
| E-BUD-04 | Статья дважды (BR-002) | «Статья „{название}“ уже есть в бюджете, строка {N}.» |
| E-BUD-05 | Лимит ниже задействованного (BR-004) | «Лимит статьи „{название}“ не может быть меньше задействованной суммы {сумма}.» |
| E-BUD-06 | Закрытие при открытых документах | «Бюджет нельзя закрыть: {N} заявок на согласовании. Дождитесь решений или отзовите заявки.» |
| E-REQ-01 | Обязательное поле (ТЗ §26.1) | со списком `fields` |
| E-REQ-02 | Комментарий < 10 (BR-060) | «Опишите причину: комментарий не короче 10 символов.» |
| E-REQ-04 | Статья чужой группы (BR-010, AC-002) | 403 — «Статья „{название}“ недоступна для роли {Снабженец/Руководитель проекта}.» (ТЗ §13.3) |
| E-REQ-05 | Проект недоступен (BR-014) | 403 — «Проект {код} вам недоступен.» |
| E-REQ-06 | Больше 200 позиций | «В заявке не больше 200 позиций.» |
| E-PLN-01 | Разные проект или статья (BR-021) | «Для одного документа выберите позиции одного проекта и одной статьи» (ТЗ §8.3) |
| E-PLN-02 | Остаток позиции 0 | «Позиция {номер} уже закуплена полностью.» |
| E-STS-01 | Переход не из §15 | 409 — «Нельзя {действие} {документ} в статусе „{статус}“» |
| E-ACC-01 | Нет прав на действие | ТЗ §26.1 |

## Review Focus

1. **Гонка за остаток (AC-004).** Две заявки по 2 000 000 при остатке 3 000 000 отправлены одновременно из двух потоков: одна «На согласовании», вторая получает E-BUD-01 с актуальными цифрами. Задействовано — ровно 2 000 000. Тест — задача 4 (`test_parallel_submit_one_wins`).
2. **Двойной клик «Отправить».** Два запроса с одним `Idempotency-Key`: один переход статуса, одна запись аудита, один процесс signoff. Тест — задача 4 (`test_submit_twice_same_key`).
3. **Совмещение ролей и архив (§4 п.5 мастер-плана).**
   - Пользователь и СН, и ПМ: список статей — объединение групп, но заявка привязана к одной роли инициатора. Смена роли очищает статью; статья чужой для выбранной роли группы → 403 E-REQ-04.
   - Архивная статья не предлагается в новой заявке, но видна в старой с меткой «Архив».
   - Тест — задача 4 (`test_dual_role_article_follows_initiator_role`, `test_archived_article_not_offered`).
4. **Корректировка против заявок в полёте.**
   - Пока открыт черновик версии N+1, заявки проверяются по действующей версии N.
   - Лимит N+1 ниже задействованного — 422 E-BUD-05.
   - После утверждения N+1 остатки считаются по ней, а снимок N доступен во вкладке «Версии».
   - Тест — задача 2 (`test_requests_check_active_version_during_correction`).
5. **Неполное согласование (AC-003).** После ТД статус не меняется и позиций в плане нет; после ОД — «Утверждена», позиции в плане автора. Возврат после ТД снимает резерв, новый круг начинается с нуля. Тест — задача 5 (`test_td_only_is_not_approved`, `test_rework_releases_reserve`).

---

## Task 1: Стык этапа 1 — уведомления signoff через центр, маршрут БЗО

**Files:**
- Modify: `backend/apps/signoff/services/engine.py` (или где сейчас `_notify`), `backend/apps/signoff/tests/…`
- Create: `backend/apps/bpp/management/commands/bpp_configure_routes.py` (+ тест)

**Interfaces:**
- Consumes: `notifications.interface.notify(..., deliver=…)`.
- Produces: уведомления signoff идут в центр:
  - `deliver=True` для предметов `bpp.*` — события модуля: колокольчик и e-mail, ТЗ §22;
  - `deliver=False` для остальных (`hr.*`, `approvals`, `contracts`) — только колокольчик, как было. Подтверждено пользователем 27.09 для ленты задач; то же правило для прочих предметов signoff.
- Команда `bpp_configure_routes --company <slug> [--dry-run]`:
  - маршрут `bpp.purchase_request` — этап ТД, затем ОД;
  - этапы по **должностям** «Технический директор», «Операционный директор» через `hr.interface`;
  - флаги `forbid_self_approval=True`, `reject_comment_min=10`, `lazy_resolution=True`;
  - идемпотентна, как `seed_purchase_request_template`.

- [ ] **Step 1: Падающие тесты:**
  - отправка на согласование `bpp.*` создаёт `notifications.Notification` получателям этапа и доставку `email`;
  - согласование `hr.*` — уведомление без доставок;
  - текст уведомления для заявки — ТЗ §22: «Заявка ЗЗ-2026-000045 на 2 400 000,00 KZT по проекту П-015 ждёт вашего согласования» (берётся из `describe` предмета);
  - команда создаёт маршрут с нужными флагами, повтор ничего не меняет.
- [ ] **Step 2: Реализация.** Все вызовы `_notify` движка — через `notifications.notify(recipients, event=f"signoff.{событие}", title, url, company_slug=current_company(), target_type=subject_type, target_id=str(subject_id), deliver=subject_type.startswith("bpp."))`. Мессенджер для уведомлений signoff больше не зовётся: мгновенный показ делает центр.
- [ ] **Step 3:** весь набор `apps/signoff`, `apps/approvals`, `apps/contracts`, `apps/hr` зелёный (поведение для не-БЗО не меняется).
- [ ] **Step 4: Коммит** — `feat(signoff): уведомления через центр уведомлений; маршрут заявки БЗО командой bpp_configure_routes`.

---

## Task 2: Бюджет проекта (B2.1)

**Files:**
- Create: `backend/apps/bpp/models/budget.py`, миграция `bpp/00NN_budget`
- Create: `backend/apps/bpp/services/budget/__init__.py`, `service.py`, `balance.py`, `access.py`
- Create: `backend/apps/bpp/schemas/budget.py`, `backend/apps/bpp/views_budget.py`, `backend/apps/bpp/urls_budget.py`
- Test: `backend/apps/bpp/tests/budget/test_budget.py`, `test_budget_api.py`, `test_balance.py`

**Interfaces:**
- Consumes: `project.interface.project_brief/is_member/search_projects`, `refdata.interface.article_brief/article_groups`, `services/core/{numbering,audit,errors,permissions,owners,registry,money,export,printing}`.
- Produces (мастер-план §2.6):
  - `services/budget/balance.balance(project_id: str, article_id: str, *, exclude_request_id: str | None = None, lock: bool = False) -> dict` — `{limit, committed, available, as_of, line_id}` по **действующей** версии; `lock=True` — `SELECT … FOR UPDATE` строки бюджета (только внутри транзакции);
  - `services/budget/balance.lines_for(project_id: str, article_group_codes: list[str]) -> list[dict]` (ТЗ §23 GetBudgetLines);
  - `models.budget`: `Budget`, `BudgetVersion`, `BudgetLine`, `BudgetStatus` (`draft|approved|closed`), `VersionState` (`draft|active|archived`).

- [ ] **Step 1: Модели**

```python
"""Бюджет проекта (ТЗ §06, D-06, D-07): один на проект на весь срок, версии со
снимками; черновик корректировки на остатки не влияет."""

from __future__ import annotations

from django.db import models
from django.db.models import Q

from .core import BppModel, VersionedModel

__all__ = ["Budget", "BudgetLine", "BudgetStatus", "BudgetVersion", "VersionState"]


class BudgetStatus(models.TextChoices):
    DRAFT = "draft", "Черновик"
    APPROVED = "approved", "Утверждён"
    CLOSED = "closed", "Закрыт"


class VersionState(models.TextChoices):
    DRAFT = "draft", "Черновик"
    ACTIVE = "active", "Действующая"
    ARCHIVED = "archived", "Архив"


class Budget(BppModel, VersionedModel):
    number = models.CharField(max_length=64, unique=True)          # БДЖ-<код проекта>
    project_id = models.CharField(max_length=36, unique=True)      # BR-001; project — соседняя аппка
    currency_code = models.CharField(max_length=3, default="KZT", db_default="KZT")
    date_from = models.DateField(null=True, blank=True)
    date_to = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=BudgetStatus.choices,
                              default=BudgetStatus.DRAFT, db_default=BudgetStatus.DRAFT.value)

    class Meta:
        constraints = [models.CheckConstraint(
            condition=Q(date_from__isnull=True) | Q(date_to__isnull=True) | Q(date_to__gte=models.F("date_from")),
            name="ck_bpp_budget_period")]


class BudgetVersion(BppModel):
    budget = models.ForeignKey(Budget, on_delete=models.CASCADE, related_name="versions")
    version_no = models.PositiveIntegerField()
    state = models.CharField(max_length=16, choices=VersionState.choices)
    comment = models.TextField(default="", blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.IntegerField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["budget", "version_no"], name="uq_bpp_budget_version"),
            # Одна действующая и один черновик на бюджет.
            models.UniqueConstraint(fields=["budget"], condition=Q(state="active"),
                                    name="uq_bpp_budget_one_active"),
            models.UniqueConstraint(fields=["budget"], condition=Q(state="draft"),
                                    name="uq_bpp_budget_one_draft"),
        ]


class BudgetLine(BppModel):
    version = models.ForeignKey(BudgetVersion, on_delete=models.CASCADE, related_name="lines")
    article_id = models.CharField(max_length=36)                   # refdata — соседняя аппка
    limit_amount = models.DecimalField(max_digits=18, decimal_places=2)
    # Кэш CALC-002: пересчитывается в транзакции перехода статуса документа,
    # сверяется ночной задачей (задача 3). Только у действующей версии.
    committed_cache = models.DecimalField(max_digits=18, decimal_places=2, default=0, db_default=0)
    comment = models.CharField(max_length=255, default="", blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["version", "article_id"], name="uq_bpp_budget_line"),  # BR-002
            models.CheckConstraint(condition=Q(limit_amount__gte=0), name="ck_bpp_budget_limit"),
        ]
```

- [ ] **Step 2: Падающие тесты сервиса** (`test_budget.py`):
  - **Создание.** Черновик с номером `БДЖ-<код проекта>`; второй бюджет проекта → E-BUD-03 со ссылкой; статья дважды → E-BUD-04 с номером строки; лимит < 0 → 422.
  - **Утверждение.** «Утвердить»: пустой бюджет или Σ = 0 → 422; иначе статус «Утверждён», версия 1 действующая, `approved_at/by`, аудит.
  - **Корректировка.**
    - `start_correction` — черновик версии 2 копией строк; второй старт → 409 E-STS-01.
    - `approve_correction` с комментарием < 10 → E-REQ-02; лимит ниже задействованного → E-BUD-05 с суммой; иначе версия 2 действующая, версия 1 в архиве.
    - `cancel_correction` удаляет черновик версии.
    - `test_requests_check_active_version_during_correction` — Review Focus 4.
  - **Закрытие и повторное открытие.** Закрыть при заявке «На согласовании» → E-BUD-06; «Открыть повторно» — с комментарием ≥ 10.
  - **Удаление.** Удалить можно только черновик; аудит пишет факт удаления.
- [ ] **Step 3: Реализация** `service.py` — функции `create`, `update_draft(budget_id, *, lines, version, actor_id)`, `approve`, `start_correction`, `update_correction`, `approve_correction`, `cancel_correction`, `close`, `reopen`, `delete_draft`, `serialize(budget, *, request)` (строки, итоги по бюджету и по группам статей, `allowed_actions`). Строка с «Задействовано» > 0 не удаляется в корректировке (ТЗ §6.4).
- [ ] **Step 4: Права (`access.py`)**:
  - видят бюджет — `bpp.budgets:view`;
  - СН и ПМ — только строки своих групп статей (`permissions.article_groups_for`); ПМ — только проектов-участий (`project.interface.is_member`);
  - править — `bpp.budgets:edit`;
  - утверждать, корректировать, закрывать — `bpp.budgets.approve:edit`;
  - `allowed_actions` — по статусу и этим правам.
- [ ] **Step 5: Ручки** (`/api/bpp/v1/budgets…`, ТЗ §23):
  - реестр L-01 — фильтры «статус», «проект»; колонки — проект, версия, статус, Σ лимит, задействовано, оплачено факт (в этапе 2 — 0), доступно, дата утверждения; экспорт;
  - `GET/PATCH /budgets/<id>`, `POST /budgets`;
  - действия `approve`, `correction/start|approve|cancel`, `close`, `reopen`, `DELETE` черновика;
  - `GET /budgets/<id>/versions/<no>` — снимок;
  - `GET /budgets/lines?project_id=&role=sn|pm` (GetBudgetLines);
  - `GET /budgets/balance?project_id=&article_id=&exclude_request_id=` (GetBudgetBalance);
  - печать версии — PDF.

  Регистрация `owners.register("bpp.budget", …)`.
- [ ] **Step 6:** `pytest apps/bpp apps/access/tests/test_gate.py` → PASS; `API.md` — раздел «Бюджеты».
- [ ] **Step 7: Коммит** — `feat(bpp): бюджет проекта — версии, корректировка, закрытие, остаток по статье`.

---

## Task 3: «Задействовано» и ночная сверка (B2.4)

**Files:**
- Create: `backend/apps/bpp/services/budget/committed.py`, `backend/apps/bpp/tasks_budget.py` (задача `reconcile_committed` — `@company_task`, beat через `@company_dispatch_task`), миграция `bpp/00NN_committed_beat` (PeriodicTask 02:30 Asia/Almaty ежедневно)
- Test: `backend/apps/bpp/tests/budget/test_committed.py`

**Interfaces:**
- `committed.compute(project_id, article_id) -> Decimal` — CALC-002 из источника. Берутся позиции заявок со статусом заявки «На согласовании», «Утверждена», «Закрыта»:
  - открытая или частично закрытая позиция — плановая сумма;
  - закрытая или аннулированная — Σ строк счетов (в этапе 2 — 0).

  Этап 3 (B3.3) расширяет формулу договорами и счетами — в одной функции.
- `committed.refresh(line: BudgetLine) -> Decimal` — пересчитать и записать `committed_cache` (зовётся под блокировкой строки в каждом переходе статуса заявки).

- [ ] Тесты:
  - формула для открытой, частично закрытой и закрытой позиции;
  - черновик и «На доработке» не занимают;
  - отмена и отклонение снимают;
  - ночная задача на подложенном расхождении (кэш испорчен вручную) пишет `fallback("bpp.budget.committed_drift", …, expected=False)` с компанией, проектом, статьёй и чинит кэш;
  - без расхождения — тишина.

  Метрики и панели здесь нет: её добавит A в A3.2 (этап 3). Сторож `test_metrics_are_observed` не пустит метрику без панели; до тех пор расхождение видно в Loki по строке `FALLBACK` (правило `htqweb-fallback-worker-logs`).
- [ ] Коммит — `feat(bpp): «задействовано» по статье — расчёт из заявок, кэш в строке бюджета, ночная сверка`.

---

## Task 4: Заявка на закупку — модель, черновик, отправка (B2.2, часть 1)

**Files:**
- Create: `backend/apps/bpp/models/requests.py`, миграция
- Create: `backend/apps/bpp/services/requests/__init__.py`, `service.py`, `access.py`, `submit.py`
- Create: `backend/apps/bpp/schemas/requests.py`, `views_requests.py`, `urls_requests.py`
- Test: `backend/apps/bpp/tests/requests/test_request_draft.py`, `test_request_submit.py`, `test_request_api.py`

**Interfaces:**
- Модели: `PurchaseRequest` (`BppModel`, `VersionedModel`), `PurchaseRequestItem`, `RequestStatus` (`draft|in_approval|rework|rejected|approved|cancelled|closed`), `ItemStatus` (`open|partially_closed|closed|annulled`), `InitiatorRole` (`sn|pm`), `PurchaseType` (`goods|works`).
- Поля заявки — ТЗ §7.3 и §24:
  - `number`, `author_id`, `initiator_role`, `project_id`, `article_id`, `purchase_type`, `need_date`, `justification`;
  - `total_amount` (Σ позиций, считает сервер), `currency_code`, `status`, `rework_comment` (последний возврат — жёлтая плашка).
- Поля позиции — ТЗ §7.4: `request`, `line_no`, `sys_number`, `name`, `specs`, `uom_id`, `qty`, `price`, `amount`, `need_date`, `status`, `executor_id`. `executor_id` — исполнитель в плане, по умолчанию автор (задача 6).
- CHECK `qty > 0`, `amount > 0`; UNIQUE `number`, `sys_number`, `(request, line_no)`.

- [ ] **Step 1: Падающие тесты черновика:**
  - первое сохранение выдаёт `ЗЗ-ГГГГ-000001`, позиции — `…-01`, `…-02`;
  - сохранение без проекта → E-REQ-01 (проект обязателен даже для черновика, ТЗ §7.7);
  - 201 позиция → E-REQ-06;
  - сумма позиции = `ROUND(кол-во × цена, 2)` (CALC-004), сумма заявки — Σ; присланные клиентом суммы игнорируются;
  - `test_dual_role_article_follows_initiator_role`, `test_archived_article_not_offered` — Review Focus 3;
  - ПМ выбирает проект, где он не участник → 403 E-REQ-05;
  - проект без утверждённого бюджета → E-BUD-02;
  - копирование — новая «Черновик» без файлов и согласований, чужая группа статей при копировании → 403.
- [ ] **Step 2: Падающие тесты отправки** (ТЗ §7.7, §28.1):
  - обязательные поля (обоснование 10–2000, потребность ≥ сегодня, ≥ 1 позиция) → E-REQ-01 со списком `fields`;
  - AC-001: 3 650 000 при остатке 2 400 000 → 422 E-BUD-01 с превышением «1 250 000,00 KZT», статус «Черновик»;
  - `test_parallel_submit_one_wins` — Review Focus 1: два потока, `transaction=True`, каждый поток своё соединение;
  - `test_submit_twice_same_key` — Review Focus 2;
  - устаревшая `version` → 409 E-CON-01;
  - успешная отправка — «На согласовании», кэш «задействовано» вырос, процесс signoff запущен (`start_process(subject_type="bpp.purchase_request", subject_id=str(id), initiator_id=author)`), аудит `submitted`.
- [ ] **Step 3: Реализация.** Отправка — одна транзакция в порядке ТЗ §28.1:
  1. права;
  2. статус;
  3. поля;
  4. `balance(..., exclude_request_id=id, lock=True)`;
  5. сравнение;
  6. статус и `version + 1`;
  7. `committed.refresh`;
  8. `start_process`;
  9. аудит.

  Уведомления этапов отправляет движок (задача 1).
- [ ] **Step 4: Ручки** (`/api/bpp/v1/requests…`, ТЗ §23):
  - реестр L-02 — фильтры «статус», «проект», «статья», «автор», «период», «Ждёт моего решения» (`signoff.list_awaiting_subject_ids`); колонка «Сейчас у» через `holders`;
  - `POST/GET/PATCH /requests[/<id>]`, `POST /requests/<id>/submit`, `POST /requests/<id>/copy`, `DELETE` черновика;
  - `GET /requests/<id>/print` (PDF с листом согласования — `printing`, шаблон наследует `bpp/print/base.html`);
  - видимость (ТЗ §7.1): автор — свои; ТД, ОД, ФД, ГД — все; СН и ПМ чужие не видят.

  Регистрация `owners.register("bpp.purchase_request", …)`; файлы — тип `request_attachment`.
- [ ] **Step 5: Коммит** — `feat(bpp): заявка на закупку — черновик, отправка с контролем остатка под блокировкой`.

---

## Task 5: Заявка — согласование, отзыв, отмена (B2.2, часть 2)

**Files:**
- Create: `backend/apps/bpp/approval_hooks.py`, `backend/apps/bpp/services/requests/transitions.py`
- Modify: `backend/apps/bpp/apps.py` — **файл A**: в `BppConfig.ready()` A заранее кладёт вызов `from . import approval_hooks; approval_hooks.register()` в `try/except ImportError`. B создаёт `approval_hooks.py`, `apps.py` не трогает; если строки нет — прислать A.
- Test: `backend/apps/bpp/tests/requests/test_request_approval.py`

**Interfaces:**
- `approval_hooks.register()`: `signoff.register_subject("bpp.purchase_request", label="Заявка на закупку", model=PurchaseRequest, on_approved=…, on_rejected=…, on_rework=…, on_cancelled=…, describe=…, facts=…)`. Образец — `apps/contracts/approval_hooks.py`.
  - `describe` — номер, сумма, проект, ссылка `/bpp/requests/<id>`.
  - `facts` — сумма, проект, статья, роль инициатора (маршрут может ветвиться по сумме).
- Колбэки выполняются в транзакции движка и держат кэш «задействовано» в согласии со статусом:
  - `on_approved` → «Утверждена», позиции «Открыта», уведомление автору «Заявка … утверждена. Позиции доступны в Плане закупок» (ТЗ §22);
  - `on_rework` → «На доработке», `rework_comment`, резерв снят;
  - `on_rejected` → «Отклонена», позиции «Аннулирована», резерв снят.
- `transitions.withdraw(id, *, actor_id, version)`: автор, «На согласовании», ни одного решения (`signoff`), `cancel_process` → «Черновик», резерв снят. Решение уже есть → 409 E-STS-01.
- `transitions.cancel(id, *, actor_id, comment, version)`:
  - автор — «Черновик» / «На доработке»;
  - ФД (`bpp.requests.cancel_approved:edit`) — «Утверждена» без позиций в договорах и счетах (этап 2: всегда без);
  - комментарий ≥ 10;
  - итог — «Отменена», позиции «Аннулирована», резерв снят.
- «Закрыть остаток» и блок «Исполнение» — этап 3: им нужны счета.

- [ ] Тесты:
  - `test_td_only_is_not_approved` (AC-003);
  - `test_rework_releases_reserve` — повторная отправка начинает новый круг с нуля;
  - отклонение с комментарием 9 символов → 422 (флаг маршрута);
  - автор-ТД не согласует свою заявку (флаг запрета самосогласования, этап 1 B);
  - отзыв после первого решения → 409;
  - отмена ФД утверждённой → резерв снят;
  - повтор колбэка (движок доставил дважды) не меняет статус второй раз.
- [ ] Коммит — `feat(bpp): заявка — согласование ТД → ОД, возврат, отклонение, отзыв, отмена`.

---

## Task 6: План закупок (B2.3)

**Files:**
- Create: `backend/apps/bpp/services/plan/__init__.py`, `service.py`; `views_plan.py`, `urls_plan.py`
- Test: `backend/apps/bpp/tests/plan/test_plan.py`

**Interfaces:**
- `service.items(request, *, filters, sort)` — позиции утверждённых заявок (BR-020):
  - СН — где исполнитель он и роль инициатора `sn`, ПМ — `pm` (ТЗ §8.1);
  - ФД (`bpp.plan.all:view`) — все, без действий;
  - колонки ТЗ §8.2; остаток кол-ва и суммы — CALC-005 / CALC-006 (в этапе 2 — план, счетов ещё нет), фильтр «Остаток > 0» по умолчанию.
- `service.validate_selection(item_ids, *, target: "contract" | "invoice", request)`:
  - позиции видимы вызывающему;
  - один проект и одна статья (BR-021) → иначе E-PLN-01;
  - остаток > 0 → иначе E-PLN-02.

  Ответ `{ok: true, project_id, article_id, purchase_type, items: [{id, sys_number, name, uom_id, qty_left, amount_left}]}` — то, что откроет F-04 / F-05 в этапе 3.
- `service.reassign(item_ids, *, to_user_id, actor_id)` — АДМ (`bpp.settings:edit`), аудит по каждой позиции.
- Ручки: `GET /plan` (реестр L-04 с экспортом), `POST /plan/validate`, `POST /plan/reassign`.

- [ ] Тесты:
  - позиции разных статей → E-PLN-01;
  - позиция с остатком 0 не выбирается → E-PLN-02;
  - ФД видит все позиции, действия ему недоступны (403 на `validate`);
  - переназначение переносит позиции в план другого исполнителя;
  - отклонённая и отменённая заявки в плане не появляются.
- [ ] Коммит — `feat(bpp): план закупок — позиции утверждённых заявок, проверка выбора, переназначение`.

---

## Task 7 (волна 2): Экраны бюджета, заявки, плана (B2.5)

**Files:**
- Create: `frontend/src/features/bpp/budgets/module.tsx` + L-01, F-01 (вкладка «Версии», итоги по группам, режим корректировки)
- Create: `frontend/src/features/bpp/requests/module.tsx` + L-02, F-02
- Create: `frontend/src/features/bpp/plan/module.tsx` + L-04 и мастер F-03
- Modify: `frontend/src/app/signoffSubjectViews.ts` — `subject_id` строкой (сейчас `Number(process.subject_id)`, UUID дал бы `NaN`); вид для `bpp.purchase_request`
- Tests: vitest на каждый экран

**F-02 — заявка:**
- **Остаток.** «Остаток после заявки» пересчитывается на лету (CALC-004 на фронте, суммы строками через `parseMoneyInput`). При превышении — плашка «Сумма заявки превышает доступный остаток статьи на …», «Отправить» недоступна, «Сохранить черновик» доступна.
- **Роль и статья.** «Роль инициатора» видна только при двух ролях (`GET /bpp/v1/me`), её смена очищает статью. Статья недоступна до выбора проекта с подсказкой «Сначала выберите проект».
- **Возврат.** Комментарий возврата — жёлтой плашкой.
- **Позиции.** Вставка позиций из Excel (буфер обмена: Наименование / Ед. / Кол-во / Цена); лимит 200 позиций.

**Каркас.** Кнопки — только из `allowed_actions`, через `BppDocumentShell`. Автосохранение черновика и диалог несохранённых изменений — там же.

**План.** Кнопки «Оформить договор» и «Оформить счёт» зовут `POST /plan/validate` и ведут на `/bpp/agreements/new` / `/bpp/invoices/new`. Эти экраны появятся в этапе 3, поэтому кнопка рисуется, только если такой маршрут есть среди `bppModules` — проверка наличия, а не заглушка.

- [ ] Тесты:
  - пересчёт остатка на лету;
  - «Отправить» недоступна при превышении;
  - выбор позиций разных статей блокирует кнопки с подсказкой ТЗ §8.3;
  - смена роли очищает статью;
  - вставка из буфера разбирает строки таблицы.
- [ ] Коммит — `feat(bpp): экраны бюджета, заявки и плана закупок`.

---

## После этапа

- [ ] Весь набор бэкенда (без `ci-known-failures.txt`) и `npx vitest run` зелёные, кроме падений, воспроизводящихся на базовом коммите; набор `signoff`/`approvals`/`contracts`/`hr` — без правок старых тестов.
- [ ] Изменения `signoff` (задача 1) — на подтверждение A до PR (мастер-план §0, правило 3).
- [ ] Финальное ревью ветки отдельным ревьюером; PR в `new-module-BPP-merge`.
