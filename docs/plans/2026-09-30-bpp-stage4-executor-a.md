# БЗО, этап 4 — план исполнителя A (Санжар, ветка `new-module-BPP-sanzhar`)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** «Оплаты факт» целиком по ТЗ §11:
- **Сверка выписки со счетами (A4.2).** Автоматическая по номеру счёта в назначении платежа, ручные действия ФД, отмена загрузки, статус сверки счёта (CALC-010).
- **Дашборд D-01 «Оплаты» (A4.3).** Показатели со ссылками на реестр счетов, графики, «Оплачено факт» по статьям (CALC-007).

**Стартовая точка:** `new-module-BPP-merge` после PR #40 (`90b2b0a`). В ветке уже есть:
- загрузка выписки (A4.1 — сделана на этапе 3);
- счёт с полями сверки `Invoice.paid_bank_amount` / `recon_status` (B3.2);
- `apps.bpp.interface.find_by_number`.

До старта подтянуть в `new-module-BPP-merge` новую работу Руслана — его ветка впереди общей:
- файлы договора и счёта;
- экраны B на общих кусках A;
- демо-данные.

**Architecture:**
- Сверка — подмодуль `bank` (`bpp_bank`): модели `PaymentMatch` и новые поля строки выписки в `models/bank.py`, сервисы `services/bank/recon.py` (чистые функции номера и распределения) и `services/bank/matching.py` (запись под блокировками). Ручки добавляются в `views_bank.py` / `urls_bank.py`.
- Статус сверки счёта пишет только `matching.recalc_invoice` (`services/bank/matching.py`) — в той же транзакции, что и изменение сопоставлений (контракт §2.6).
- Дашборд — `services/dashboard/payments.py` и ручка `bank/dashboard`. Это агрегаты SQL, без кэша: ТЗ требует свежих цифр при каждом открытии. Экран — `features/bpp/dashboard/` на `recharts` (уже в проекте).

**Tech Stack:** Django 5.2.7, PostgreSQL (схема на компанию), Celery, openpyxl 3.1.5, pytest-django; React 18 + TypeScript + react-query + recharts 2.15, vitest.

**Spec:**
- ТЗ `docs/tz/TZ-budget-procurement-payments-v1.0.md`:
  - разделы §11.1–§11.5, §15.5, §19 (L-07);
  - правила и расчёты BR-060, BR-070, BR-071, BR-073, BR-075, CALC-007, CALC-010;
  - приёмка AC-010, AC-011;
  - требования REQ-016, REQ-017, REQ-018, REQ-027.
- [Мастер-план](2026-09-26-bpp-master-plan.md):
  - §2.5 и §2.6 (`recalc_invoice`, `find_by_number`);
  - §4 Review Focus 3 («грязная выписка»);
  - §5, этап 4: A4.2, A4.3.
- [План этапа 3 A](2026-09-28-bpp-stage3-executor-a.md) — что уже сделано в загрузке выписки.

---

## Что уже сделано к старту

| Мастер-план | Состояние |
|---|---|
| A4.1 загрузка выписки | сделано на этапе 3: `BankImport`, `BankStatementLine`, разбор 1С / Excel / CSV, дубли, уборщик |
| B3.1–B3.3 договор, счёт, «задействовано» | сделано; у счёта есть `paid_bank_amount`, `recon_status` (`no_data`/`partial`/`full`/`overpaid`), `PaymentMark` |
| B4.1 подотчёт, B4.2 демо-данные | сделано |
| **A4.2 сверка, A4.3 дашборд** | **не начато — этот план** |

## Решения этого плана

**D-S4-1. Сопоставление «на проверке» в сумму счёта не входит.**
- «Оплачено по банку» — это сумма только подтверждённых сопоставлений: автоматических без замечаний, ручных и подтверждённых ФД.
- Строка «Требуют проверки» статус сверки счёта не меняет, пока ФД её не подтвердит (AC-011).

**D-S4-2. Причины попадания во «Требуют проверки»** — дословно из ТЗ §11.2:
- «БИН получателя не совпадает с БИН контрагента счёта»;
- «В назначении несколько номеров, сумма не делится однозначно»;
- «Счёт в статусе, отличном от К оплате / Оплачено»;
- «Валюта платежа ≠ валюте счёта».

Код причины хранится в строке, текст причины — на экране.

**D-S4-3. Какие статусы счёта сверка принимает без проверки.** Сопоставление проходит без проверки, если статус счёта — `to_pay`, `partially_paid`, `paid`, `awaiting_docs`, `docs_provided` или `closed`, то есть «К оплате» или «Оплачено» с любым шагом закрывающих документов (D-13).
- Остальные статусы уходят на проверку: `draft`, `under_review`, `returned`, `not_payable`, `cancelled`, `replaced`.
- Ручное сопоставление к «Отменён» и «Не к оплате» запрещено (ТЗ §11.4).

**D-S4-4. Несколько номеров в одном назначении.**
- Сумма платежа распределяется по неоплаченным остаткам счетов в порядке номеров.
- Если сумма платежа ≠ Σ остатков — строка уходит на проверку с предложенным распределением (ТЗ §11.3 п.6).
- Остаток счёта = сумма счёта − «Оплачено по банку» на момент сверки (не ниже 0).

**D-S4-5. Показатели дашборда — по статусам после D-13.** ТЗ §11.5 писался до того, как закрывающие документы стали запрашиваться после оплаты, поэтому показатели привязаны к нынешним статусам:
- «К оплате» — `to_pay` + `partially_paid`, это вкладка L-06 `to_pay`;
- «Из них ждут АВР / накладную» заменяется показателем «Ждут закрывающих» — вкладка `awaiting_docs`;
- «Отмечено БУХ „Оплачено“, банк не подтвердил > 3 раб. дней» — вкладка `bank_unconfirmed` и последняя неотменённая отметка оплаты старше 3 рабочих дней (Пн–Пт, без праздников — как в метрике этапа 3);
- «Платёж есть, отметки БУХ нет» — `recon_status ≠ no_data` и статус счёта не из группы «Оплачено».

**D-S4-6. Период дашборда.**
- Банковские показатели («Оплачено по банку», переплата и недоплата, несопоставленные, недельный график, топ-10) считаются по дате платежа в выписке.
- Очереди счетов берутся на текущий момент, без периода. Так ссылка всегда совпадает с тем, что видно во вкладке реестра.

**D-S4-7. Столбец «Оплачено факт» в бюджете.**
- A делает функцию `recon.paid_fact_by_article(project_id) -> dict[str, Decimal]` (CALC-007).
- Столбец в карточке и экране бюджета добавляет B в своей зоне (остаток B).

**D-S4-8. Фильтры реестра счетов для ссылок дашборда.** Реестру L-06 (ручка B) нужны фильтры `author_id` и `recon_status`, иначе ссылки дашборда не воспроизводят показатель. Их добавляет A — отдельным коммитом с пометкой «зона B», в задаче 5.

---

## Global Constraints

- **Окружение.** Интерпретатор — корневой `.venv`; команды из `backend/`: `../.venv/Scripts/python.exe …`. **Один прогон pytest за раз на машине:** пока контроллер гоняет набор, разработчики pytest не запускают.
- **Ветки и коммиты.** Ветки не создавать; коммитить только файлы своей задачи. Правка в зоне B (`services/invoices/*`, `views_invoices.py`, экраны B) — отдельным коммитом с пометкой.
- **Межаппный доступ** — только `apps.<x>.interface`.
  - Внутри аппки `bpp` подмодуль A читает модели счёта напрямую; счёт пишет только через `matching.recalc_invoice` — поля сверки, по контракту §2.6.
  - Задачи Celery — `@company_task`, первой строкой `require_service("bpp")`, затем `require_service("bpp_bank")`.
- **Ручки и права.**
  - Ручки — `api_view(module="bpp", level=…)` с явным уровнем.
  - Права: `bpp.bank` edit (ФД) — все действия сверки; `bpp.bank` view (ФД, БУХ) — чтение и выгрузка; дашборд — `bpp.dashboard` view (матрица ролей, `access_functions.py`).
- **Деньги** — `Decimal(18,2)`, `ROUND_HALF_UP`, никогда не `float`.
- **Ошибки** — `DomainError` с текстами ТЗ дословно.
  - Комментарий короче 10 символов — `BR-060`.
  - Счёт не найден или недопустим для ручного сопоставления — `E-VAL-01` на поле `invoice_id`.
  - Сумма распределения больше строки — `E-VAL-01` на поле `amount`.
- **Конкурентность.** Изменение сопоставлений блокирует строки счетов `select_for_update` в порядке `id`: две загрузки с платежами по одному счёту не теряют сумму.
- **Идемпотентность.** Каждая POST-ручка — `idempotent=True`. Повтор автосверки той же загрузки ничего не удваивает.
- **Фронт.**
  - Строки — `t('bpp.<ключ>', 'Русский текст')`, ошибки — `reportApiError`.
  - Селект, наполняемый запросом, объясняет пустой список через `PrerequisiteNotice`.
  - Полный `npx vitest run` проходит без новых падений; `tsc` — не выше 148.
- **Метрики** — только вместе с панелью или правилом (`test_metrics_are_observed`).
- **Документация.** `STRUCTURE.md`, `CLAUDE.md`, `API.md` правятся в той задаче, что меняет структуру или ручки.
- **Тесты после HTTP-запроса.** Чтение БД после запроса тестовым `Client` — внутри `with use_company(slug):`: ответ сбрасывает `search_path` в `public`.

## Review Focus

1. **Грязный номер.** Мастер-план §4 п.3, ТЗ §11.3 п.4. В назначении: латинская `C`/`X`, нижний регистр, пробелы и дефисы внутри номера («оплата по счёту cч - 2026 - 000123»). Ожидается `СЧ-2026-000123`.
   - Номер из 7 цифр не совпадает.
   - Цифры вне шаблона (год «20260», сумма «2026000123») не дают ложного номера.
   - Тест — задача 1 (`test_find_numbers_*`).
2. **AC-010.** Счёт на 1 000 000, списания 400 000 и 600 000 в двух выписках. После первой — «Оплачен частично», после второй — «Оплачен полностью». Повторная загрузка той же выписки сумму не меняет. Тест — задача 2.
3. **AC-011 и BR-073.** Чужой БИН получателя.
   - Строка уходит в «Требуют проверки», статус сверки счёта не меняется.
   - После подтверждения ФД с комментарием статус меняется.
   - Отмена подтверждённого сопоставления возвращает статус.
   - Тест — задачи 2 и 3.
4. **Гонка по одному счёту.** Две загрузки из разных выписок параллельно сопоставляют платежи с одним счётом. Итог «Оплачено по банку» = сумма обоих. Тест — задача 2 (`transaction=True`, потоки).
5. **Отмена загрузки.** Отменяются все её сопоставления, статусы сверки затронутых счетов пересчитываются. Отметка БУХ, заблокированная сверкой (`PaymentMark.unmark` при `paid_bank_amount > 0`), снова доступна. Повторная загрузка той же выписки после отмены сверяет заново. Тест — задача 3.

---

## Волны

- **Волна 1 (A):** задачи 1–3 (бэкенд сверки), затем 4 (экран сверки). Задача 1 идёт первой — от неё зависят 2 и 3.
- **Волна 2 (A):** задачи 5–6 (дашборд), задача 7 — сквозная проверка, полный прогон, ревью, PR.
- **B в это время** — раздел «Остаток B» ниже; сведение через `new-module-BPP-merge` в конце этапа.

---

## Task 1: Модели сверки и номер счёта в назначении

**Files:**
- Modify: `backend/apps/bpp/models/bank.py`:
  - `LineMatchStatus`: добавить `matched` «Сопоставлена», `needs_review` «Требует проверки», `excluded` «Исключена» (к `unmatched`);
  - `BankStatementLine`: `found_numbers` (JSON, номера из назначения), `review_reason` (код D-S4-2, пусто), `excluded_comment`, `excluded_by_id`, `excluded_at`;
  - новая `PaymentMatch(BppModel)`: `line` (FK), `invoice` (FK `Invoice`, `PROTECT`), `amount` (`Decimal(18,2)`), `manual`, `state` (`active`/`review`/`cancelled`), `review_reason`, `comment`, `confirmed_by_id`, `confirmed_at`, `cancelled_by_id`, `cancelled_at`, `created_by_id`;
  - индексы по `(invoice, state)` и `(line, state)`;
  - `BankImportStatus.RECONCILED = "reconciled", "Сверена"`.
- Create: `backend/apps/bpp/services/bank/recon.py` — чистые функции:
  - `normalize_purpose(text: str) -> str`;
  - `find_numbers(text: str) -> list[str]` — канонические `СЧ-ГГГГ-NNNNNN` в порядке появления, без повторов;
  - `distribute(amount: Decimal, remainders: list[tuple[str, Decimal]]) -> tuple[list[tuple[str, Decimal]], bool]` — распределение и признак «делится однозначно».
- Миграцию `bpp/00NN_recon` генерирует контроллер. Поля добавляются как expand: новые поля строк nullable или с умолчанием.
- Tests: `backend/apps/bpp/tests/bank/test_recon_numbers.py`.

**Interfaces:**
- Produces:
  - `recon.find_numbers`, `recon.distribute`;
  - модель `PaymentMatch`;
  - статусы `LineMatchStatus.MATCHED/NEEDS_REVIEW/EXCLUDED`, `BankImportStatus.RECONCILED`.

```python
# services/bank/recon.py — ядро разбора номера (ТЗ §11.3 п.4, BR-070)
import re
from decimal import Decimal

_LOOKALIKES = str.maketrans({"C": "С", "X": "Х", "c": "С", "x": "Х"})
# После перевода в верхний регистр и замены латиницы: «СЧ», затем год из 4 цифр
# и номер из 6. Между частями допускаются пробелы и дефисы (любые тире).
# (?!\d) после номера не даёт взять номер длиннее шести цифр.
_NUMBER = re.compile(r"СЧ[\s\-‐-―]*(\d{4})[\s\-‐-―]*(\d{6})(?!\d)")


def normalize_purpose(text: str) -> str:
    return (text or "").upper().translate(_LOOKALIKES)


def find_numbers(text: str) -> list[str]:
    seen: dict[str, None] = {}
    for year, seq in _NUMBER.findall(normalize_purpose(text)):
        seen.setdefault(f"СЧ-{year}-{seq}", None)
    return list(seen)
```

- [ ] **Step 1: Падающие тесты** (Review Focus 1):
  - `test_find_numbers_normalizes_latin_case_spaces_and_dashes`:
    - `"оплата по счёту cч - 2026 - 000123"` → `["СЧ-2026-000123"]`;
    - `"СЧ2026000123"` → то же;
    - `"сч—2026—000123"` → то же.
  - `test_find_numbers_several_in_order_without_duplicates`: `"СЧ-2026-000002, сч-2026-000001, СЧ-2026-000002"` → `["СЧ-2026-000002", "СЧ-2026-000001"]`.
  - `test_find_numbers_rejects_wrong_lengths`:
    - `"СЧ-2026-0001234"` → `[]` (7 цифр);
    - `"СЧ-20260-000123"` → `[]`.
  - `test_distribute_exact_and_ambiguous`:
    - `distribute(Decimal("1000"), [("A", Decimal("400")), ("B", Decimal("600"))])` → `([("A", 400), ("B", 600)], True)`;
    - 900 на те же остатки → распределение по порядку `[("A", 400), ("B", 500)]` и `False`;
    - 1200 → `[("A", 400), ("B", 600)]` плюс `False` (переплата — проверка).
- [ ] **Step 2: Реализация** `recon.py` и моделей. Контроллер генерирует миграцию; `makemigrations --check` — «No changes».
- [ ] **Step 3: Прогон** (контроллер): `apps/bpp/tests/bank/test_recon_numbers.py` и `apps/bpp/tests/bank`.
- [ ] **Коммит** — `feat(bpp): модели сверки выписки и номер счёта в назначении платежа (A4.2, часть 1)`.

## Task 2: Автосверка и статус сверки счёта (CALC-010)

**Files:**
- Create: `backend/apps/bpp/services/bank/matching.py`:
  - `auto_match(import_id) -> dict` — итоги по вкладкам;
  - `recalc_invoice(invoice_id) -> None` — CALC-010, контракт §2.6;
  - `_lock_invoices(ids)` — `select_for_update` в порядке `id`.
- Modify: `backend/apps/bpp/services/bank/imports.py::run_import`.
  - После загрузки строк — `auto_match` в той же задаче, в той же схеме компании.
  - Статус загрузки после неё — «Сверена».
  - В карточке загрузки — итоги: сопоставлено, на проверке, не сопоставлено, исключено; Σ сумм каждой группы.
- Tests: `backend/apps/bpp/tests/bank/test_matching.py`.

**Interfaces:**
- Consumes: `recon.find_numbers`, `recon.distribute` (задача 1), `apps.bpp.interface.find_by_number(number) -> dict | None` (B, ключи `id, number, status, amount, currency_code, counterparty_reg_number, paid_bank_amount, recon_status`).
- Produces:
  - `matching.recalc_invoice(invoice_id)` — единственная точка записи `Invoice.paid_bank_amount` / `recon_status`;
  - `matching.auto_match(import_id)`.

```python
# services/bank/matching.py — CALC-010
from decimal import Decimal
from django.db.models import Sum

from apps.bpp.models import Invoice, PaymentMatch, ReconStatus


def recalc_invoice(invoice_id) -> None:
    """P = Σ подтверждённых сопоставлений (D-S4-1).
    P = 0 → «Нет данных банка»; 0 < P < Сумма → «Оплачен частично»;
    P = Сумма → «Оплачен полностью»; P > Сумма → «Переплата».
    Вызывается под блокировкой строки счёта, в транзакции изменения."""
    paid = (PaymentMatch.objects.filter(invoice_id=invoice_id, state="active")
            .aggregate(total=Sum("amount"))["total"]) or Decimal("0")
    inv = Invoice.objects.select_for_update().only("amount").get(pk=invoice_id)
    if paid == 0:
        status = ReconStatus.NO_DATA
    elif paid < inv.amount:
        status = ReconStatus.PARTIAL
    elif paid == inv.amount:
        status = ReconStatus.FULL
    else:
        status = ReconStatus.OVERPAID
    Invoice.objects.filter(pk=invoice_id).update(paid_bank_amount=paid, recon_status=status)
```

Правила `auto_match` (ТЗ §11.3 пп.5–8):
- строка без номеров или с номером несуществующего счёта — «Не сопоставлена»;
- один номер — сопоставление на всю сумму строки. На проверку оно уходит, если:
  - БИН получателя ≠ БИН контрагента счёта;
  - валюта ≠ валюте счёта;
  - статус счёта не из D-S4-3.

  Такое сопоставление получает `state=review` и причину.
- несколько номеров — `distribute` по остаткам (D-S4-4). Если сумма делится однозначно — `active` на каждый счёт, иначе всё распределение `review` с причиной «несколько номеров»;
- после сопоставлений — `recalc_invoice` по каждому затронутому счёту, под блокировкой в порядке `id`;
- уже обработанная строка (есть сопоставление или исключение) при повторе не трогается — идемпотентность.

- [ ] **Step 1: Падающие тесты** (Review Focus 2, 3, 4). Счета — через помощники B `apps/bpp/tests/test_invoices.py` (`_submitted`, `_fd`, `_buh`), выписки — через `apps/bpp/tests/bank/common.py`.
  - `test_ac010_partial_then_full_and_reupload_changes_nothing`:
    - счёт на 1 000 000; выписка 1 со строкой 400 000 и номером в назначении → `partial`, `paid_bank_amount = 400000.00`;
    - выписка 2 с 600 000 → `full`;
    - выписка 1 ещё раз → 0 новых строк, сумма та же.
  - `test_ac011_foreign_bin_goes_to_review_and_keeps_status`: строка `needs_review` с причиной `bin_mismatch`, у счёта `no_data`.
  - `test_currency_mismatch_and_wrong_status_go_to_review`.
  - `test_several_numbers_exact_split_and_ambiguous_split`.
  - `test_unknown_number_and_no_number_stay_unmatched`.
  - `test_two_imports_race_for_one_invoice` (`transaction=True`, два потока, барьер перед записью) — итог равен сумме обоих платежей.
  - `test_import_becomes_reconciled_with_totals`.
- [ ] **Step 2: Реализация.**
- [ ] **Step 3: Прогон** (контроллер): `apps/bpp/tests/bank`, `apps/bpp/tests/test_invoices.py`, `apps/bpp/tests/test_stage3_e2e.py` — сквозной тест этапа 3 правится: строка теперь «Сопоставлена».
- [ ] **Документация:** `API.md` (карточка загрузки — итоги по вкладкам, статус «Сверена»), `STRUCTURE.md` (строка bpp).
- [ ] **Коммит** — `feat(bpp): автосверка выписки со счетами и статус сверки счёта — CALC-010, AC-010, AC-011 (A4.2, часть 2)`.

## Task 3: Ручные действия ФД, отмена загрузки, выгрузка результата

**Files:**
- Modify: `backend/apps/bpp/services/bank/matching.py`:
  - `candidates(line_id, query: str = "") -> list[dict]` — до 5 кандидатов (ТЗ §11.2). Сначала тот же БИН и сумма ±10 %, затем поиск по номеру, контрагенту и сумме из `query`. Счета «Отменён» и «Не к оплате» исключены;
  - `match_line(actor_id, line_id, allocations: list[{invoice_id, amount}], comment) -> dict` — ручное сопоставление `manual=True`, сразу `active`. Проверки ТЗ §11.4: счёт существует, не «Отменён» и не «Не к оплате»; Σ распределения ≤ сумме строки;
  - `confirm(actor_id, line_id, comment)` — «Подтвердить сопоставление»: `review` → `active` (комментарий обязателен, BR-060);
  - `cancel_match(actor_id, line_id, comment)` — отмена всех активных и review-сопоставлений строки, строка → «Не сопоставлена»;
  - `exclude(actor_id, line_id, comment)` — «Исключить — не относится к закупкам» (BR-060), строка → «Исключена»;
  - `cancel_import(actor_id, import_id, comment)` — отмена загрузки «Сверена», мягкая:
    - строки и сопоставления получают `cancelled_at`;
    - счета пересчитываются;
    - загрузка → «Отменена»;
    - повторная загрузка той же выписки сверяется заново (дубли считаются только среди неотменённых строк — индекс этапа 3).
  - `impact(import_id) -> {"invoices": N}` — для диалога подтверждения.

  Каждое действие — `audit.record` и `recalc_invoice` затронутых счетов в той же транзакции.
- Modify: `backend/apps/bpp/views_bank.py`, `urls_bank.py`:
  - `GET bank/imports/<id>/lines?tab=matched|review|unmatched|excluded` (страница строк: причина, найденные номера, сопоставления со ссылками на счета, «Оплачено по банку всего»);
  - `GET bank/lines/<id>/candidates?q=`;
  - `POST bank/lines/<id>/match`, `bank/lines/<id>/confirm`, `bank/lines/<id>/cancel-match`, `bank/lines/<id>/exclude`;
  - `GET bank/imports/<id>/impact`, `POST bank/imports/<id>/cancel`;
  - `GET bank/imports/<id>/export` — xlsx из трёх листов (§11.4 «Экспорт результата»): «Сопоставлены», «Требуют проверки», «Не сопоставлены».
- Modify: `backend/apps/bpp/services/core/export.py` — `write_xlsx_sheets(name, sheets: list[tuple[str, columns, rows]])`, те же форматы колонок.
- Tests: `backend/apps/bpp/tests/bank/test_manual_matching.py`.

**Interfaces:**
- Consumes: задачи 1–2.
- Produces: ручки выше (контракт экрана задачи 4); `export.write_xlsx_sheets`.

- [ ] **Step 1: Падающие тесты** (Review Focus 3, 5):
  - кандидаты — тот же БИН и сумма ±10 %, не больше 5, без «Отменён» и «Не к оплате»;
  - ручное сопоставление на двух счетах с Σ = строке; Σ > строки → 422 на `amount`;
  - подтверждение review → статус счёта меняется; комментарий из 9 символов → 422 `BR-060`;
  - отмена сопоставления возвращает статус;
  - исключение без комментария → 422, с комментарием — «Исключена» и вне остальных вкладок;
  - отмена загрузки: счета пересчитаны, отметка БУХ снова отменяема (`payments.unmark` проходит), повторная загрузка сверяет заново;
  - права: БУХ читает и выгружает, но POST → 403; ТД → 403;
  - повтор POST с тем же `Idempotency-Key` — одно действие и одна запись журнала;
  - выгрузка: три листа, суммы — числа.
- [ ] **Step 2: Реализация.**
- [ ] **Step 3: Прогон** (контроллер): `apps/bpp/tests/bank`, `apps/bpp/tests/test_invoices.py`, `apps/bpp/tests/test_export.py`, сторожа (`test_gate`, `test_app_isolation`, `test_invariants`).
- [ ] **Документация:** `API.md` (все ручки выше, коды ошибок), `STRUCTURE.md`.
- [ ] **Коммит** — `feat(bpp): ручная сверка выписки — кандидаты, сопоставление, подтверждение, исключение, отмена загрузки, выгрузка (A4.2, часть 3)`.

## Task 4: Экран результатов сверки

**Files** (`frontend/src/features/bpp/bank/`):
- Modify: `BankImportPage.tsx`:
  - итог вверху — строк, списаний, дублей и четыре группы с суммами (ТЗ §11.2);
  - вкладки «Сопоставлены», «Требуют проверки», «Не сопоставлены», «Исключены»;
  - кнопки «Выгрузить результат» и «Отменить загрузку» — диалог с числом затрагиваемых счетов (`impact`).
- Create:
  - `ReconLinesTable.tsx` — колонки по ТЗ §11.2: дата, № ПП, получатель, БИН, сумма, назначение с подсветкой найденного номера, счёт-ссылка, сумма счёта, «Оплачено по банку всего», статус сверки, причина;
  - `ManualMatchDialog.tsx` — кандидаты и поиск (autocomplete по номеру, контрагенту, сумме), распределение суммы по нескольким счетам, остаток к распределению на лету;
  - `CommentDialog.tsx` — общий для «Подтвердить», «Отменить сопоставление», «Исключить»: комментарий не короче 10 символов с подсказкой;
  - тесты.
- Modify: `api.ts`, `core/statusDictionaries.ts` — `bank_line`: `matched`, `needs_review`, `excluded`; `bank_import`: `reconciled`.

- [ ] **Step 1: Тесты vitest:**
  - вкладки и счётчики;
  - подсветка номера в назначении;
  - диалог ручного сопоставления не отправляет Σ больше строки;
  - кнопки действий скрыты без `bpp.bank` edit;
  - комментарий из 9 символов не отправляется;
  - после действия карточка и строки перечитываются;
  - отмена загрузки показывает число счетов.
- [ ] **Step 2: Реализация.** Полный `npx vitest run`, `eslint src/features/bpp`, `tsc` не выше 148.
- [ ] **Коммит** — `feat(bpp): экран сверки выписки — вкладки, ручное сопоставление, подтверждение, исключение, отмена загрузки (A4.2, часть 4)`.

## Task 5: Дашборд D-01 — бэкенд и «Оплачено факт»

**Files:**
- Create: `backend/apps/bpp/services/dashboard/__init__.py`, `services/dashboard/payments.py`:
  - `indicators(actor, filters) -> list[dict]` — `[{key, label, count, amount, link}]`, где `link` — адрес реестра счетов с фильтрами;
  - `article_chart(project_id) -> list[{article_id, name, limit, committed, paid_fact}]` — лимит и «Задействовано» из сервисов бюджета B (`services/budget/balance`, `committed.committed_by_article`);
  - `weekly_paid(filters) -> list[{week_start, amount}]`;
  - `top_counterparties(filters) -> list[{counterparty_id, name, amount}]` — топ-10.
- Modify: `backend/apps/bpp/services/bank/recon.py` — `paid_fact_by_article(project_id) -> dict[str, Decimal]` (CALC-007: Σ подтверждённых сопоставлений по счетам статьи; D-S4-7).
- Create: `backend/apps/bpp/views_dashboard.py`, `urls_dashboard.py` — `GET dashboard/payments?period_from=&period_to=&project_id=&article_id=&counterparty_id=&author_id=`, право `bpp.dashboard` view. Под рубильником модуля `bpp`: подмодуля нет, проверить `PREFIX_TO_SERVICE`.
- Modify (зона B, отдельный коммит): `backend/apps/bpp/views_invoices.py` и `services/invoices/read.py` — фильтры реестра `author_id` и `recon_status` (D-S4-8) плюс их тест.
- Tests: `backend/apps/bpp/tests/test_dashboard.py`.

Показатели (D-S4-5, D-S4-6):

| key | Показатель | Отбор | Ссылка реестра |
|---|---|---|---|
| `fd` | Счета на решении ФД, шт / сумма | `under_review` | `?tab=fd` |
| `to_pay` | К оплате, шт / сумма | `to_pay`, `partially_paid` | `?tab=to_pay` |
| `awaiting_docs` | Ждут закрывающих | `awaiting_docs` | `?tab=awaiting_docs` |
| `bank_unconfirmed` | Отмечено «Оплачено», банк не подтвердил > 3 раб. дней | вкладка `bank_unconfirmed` + последняя неотменённая отметка старше 3 рабочих дней | `?tab=bank_unconfirmed` |
| `full` | Оплачено полностью по банку | `recon_status=full` | `?recon_status=full` |
| `underpaid` | Оплачено частично, недоплата | `recon_status=partial`; сумма — Σ(сумма − оплачено по банку) | `?recon_status=partial` |
| `overpaid` | Переплата | `recon_status=overpaid`; сумма — Σ(оплачено − сумма) | `?recon_status=overpaid` |
| `no_mark` | Платёж есть, отметки БУХ нет | `recon_status≠no_data` и статус не из группы «Оплачено» | `?tab=bank_mismatch` (или фильтры статуса и `recon_status`, если вкладка B шире) |
| `unmatched` | Несопоставленные списания | Σ строк «Не сопоставлена» за период | экран «Оплаты факт» |

Фильтры проекта, статьи, контрагента и автора применяются ко всем показателям и переносятся в ссылки.

- [ ] **Step 1: Падающие тесты:**
  - `test_each_indicator_equals_the_registry_count_by_its_link` — для каждого показателя: GET реестра по его ссылке → `total` равен `count`;
  - `test_underpaid_and_overpaid_sums`;
  - `test_bank_unconfirmed_counts_three_working_days`;
  - `test_article_chart_limit_committed_paid_fact`;
  - `test_weekly_and_top10`;
  - `test_paid_fact_by_article_counts_only_confirmed_matches` (D-S4-1);
  - права: ФД, ГД и БУХ по матрице `bpp.dashboard` — да, СН — 403.
- [ ] **Step 2: Реализация.**
- [ ] **Step 3: Прогон** (контроллер): `apps/bpp/tests/test_dashboard.py`, `apps/bpp/tests/test_invoices.py`, `apps/bpp/tests/bank`, сторожа.
- [ ] **Документация:** `API.md`, `STRUCTURE.md`.
- [ ] **Коммиты:**
  - `feat(bpp): дашборд «Оплаты» D-01 — показатели со ссылками, графики, «Оплачено факт» (A4.3, часть 1)`;
  - отдельно — `feat(bpp): фильтры реестра счетов по автору и статусу сверки — для ссылок дашборда (зона B)`.

## Task 6: Экран дашборда

**Files** (`frontend/src/features/bpp/dashboard/`):
- Create:
  - `module.tsx` — пункт меню «Дашборд оплат», видимость по `bpp.dashboard` view, порядок — после «Оплаты факт»;
  - `PaymentsDashboardPage.tsx`:
    - фильтры: период, проект, статья, контрагент, автор счёта — выборы с `PrerequisiteNotice`;
    - карточки показателей — каждая ссылка ведёт на реестр счетов с теми же фильтрами;
    - столбцы «Лимит / Задействовано / Оплачено факт» по статьям выбранного проекта (без проекта — подсказка выбрать);
    - линия «Оплачено по банку» по неделям;
    - таблица топ-10 контрагентов.
  - `api.ts`, тесты.
- Обновление: запрос при каждом открытии (`staleTime: 0`, `refetchOnMount: 'always'`). Задача 4 после загрузки и после действий сверки инвалидирует ключ дашборда.

- [ ] **Step 1: Тесты vitest:**
  - карточка ведёт на реестр с фильтрами;
  - смена фильтра перечитывает данные;
  - графики получают деньги строками, без `float` в подписях (`formatMoney`);
  - пункт меню скрыт без права;
  - пустой проект — подсказка вместо графика.
- [ ] **Step 2: Реализация.** Полный `npx vitest run`, `eslint`, `tsc`.
- [ ] **Коммит** — `feat(bpp): экран дашборда «Оплаты» — показатели, графики, топ-10 (A4.3, часть 2)`.

## Task 7: Сквозная проверка этапа, прогон, ревью, PR

- [ ] **Сквозной тест** `backend/apps/bpp/tests/test_stage4_e2e.py` — одна история:
  1. Счёт оплачен отметкой БУХ.
  2. Выписка с «грязным» номером → «Сопоставлена», счёт «Оплачен полностью», дашборд: `full` = 1, `bank_unconfirmed` = 0.
  3. Отмена загрузки → счёт «Нет данных банка», дашборд `bank_unconfirmed` = 1 через 4 рабочих дня (подмена даты).
  4. Повторная загрузка → снова «Сопоставлена».
- [ ] **Прогоны:**
  - весь бэкенд без `ci-known-failures.txt`, чанками по одному (контроллер);
  - полный `npx vitest run`, `tsc`, `eslint`;
  - `./scripts/check-monitoring-config.sh`.
- [ ] **Финальное ревью** ветки отдельным ревьюером. Critical и Important исправить, мелочи — в журнал.
- [ ] **PR** в `new-module-BPP-merge`.

---

## Остаток B на этапе 4 (Руслан) — справочно

| # | Что | На чём стоит |
|---|---|---|
| B-1 | PR в `new-module-BPP-merge` с уже сделанным в его ветке: файлы договора и счёта (`f94d491`), экраны на общих кусках A (`f20dd61`), демо-данные на все статусы (`c17a0dd`) | — |
| B-2 | «Оплачено факт» в карточке и экране бюджета — поверх `recon.paid_fact_by_article` (D-S4-7) | задача 5 |
| B-3 | L-06: колонка и фильтр «Статус сверки» на экране (REQ-017); проверить вкладки «Оплачено, банк не подтвердил» и «Расхождения с банком» на данных сверки | задачи 2, 5 |
| B-4 | `InvoicesPage` читает `?tab=` из адреса — ссылки дашборда и сводки открывают нужную вкладку | задача 5 |
| B-5 | Ключи закрывающих документов счёта (`avr`) ↔ тип файла `act` (`files/0004`) — проверить сопоставление в `services/invoices/file_owner.py` | — |
| B-6 | Предложение: начать B6.1 (перенос из `contracts`) — не зависит от этапа 4 и 5 A. B5.1 ждёт A5.1 (этап 5) | — |

## Ждёт решения пользователя

- **Выбор контрагента:** один общий компонент или два — сравнение отправлено 29.09.
- **ТЗ §11.5, показатель «> 3 раб. дней»** помечен [У]. План считает рабочие дни Пн–Пт без праздников (D-S4-5), так же как метрика этапа 3. Нужен ли учёт праздников?
