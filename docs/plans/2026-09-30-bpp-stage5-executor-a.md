# БЗО, этап 5 — план исполнителя A (Санжар, ветка `new-module-BPP-sanzhar`)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Альтернативы снабженца и KPI по ТЗ §12:
- **A5.1 — альтернативные предложения (АП).** Модель, форма F-07, окно подачи, лимиты, лента L-09, блок сравнения.
- **A5.2 — KPI снабжения.** Запись KPI, её подтверждение и аннулирование, отчёт R-01.
- **Контракт для B5.1.** Выбор альтернативы делает B (Руслан) поверх функций этого плана.

**Стартовая точка:** `new-module-BPP-merge` после PR #42 (`280ae41`). Что уже есть:
- рубильник `bpp_alternatives` и префиксы шлюза `/api/bpp/v1/alternatives`, `/api/bpp/v1/kpi`;
- узлы прав `bpp.alternatives`, `bpp.alternatives.select`, `bpp.kpi` в `access/0014`;
- тип файла `alternative_offer` («КП», PDF DOCX XLSX JPG PNG, 20 МБ) в `files/0004`;
- `Agreement.alt_limit` (3) и статусы `replaced` «Заменён альтернативой» у договора и счёта;
- варианты голоса в signoff (`options`, `check_option`, `on_option`, признак этапа `votes_option`).

Ветка Руслана впереди общей: реестр счетов с `?tab=` (`256c801`), метрики, сверка B. План от неё не зависит. Файлы, которые правят оба, перечислены в «Сведение с B».

**Architecture:**
- **Всё новое — подмодуль `alternatives`** (рубильник `bpp_alternatives`):
  - модели — `models/alternatives.py`: `AlternativeOffer`, `AlternativeOfferLine`, `KpiRecord`;
  - сервисы — `services/alternatives/`: `calc.py` (CALC-013, чистые функции), `offers.py` (АП: черновик, подача, отзыв), `lifecycle.py` (закрытие АП по решению об исходном документе и контракт для B5.1), `read.py` (лента L-09, сравнение, карточка), `kpi.py` (запись KPI, синхронизация по новому документу, ручное аннулирование), `report.py` (R-01), `file_owner.py` (КП в `apps.files`);
  - ручки — `views_alternatives.py` / `urls_alternatives.py` (префиксы `alternatives/…` и `kpi/…`).
- **Изменения чужих документов — только по их событиям.** Модели счёта и договора A не пишет. Точки вызова в коде B — одной строкой, отдельными коммитами с пометкой «зона B»:
  - закрытие АП;
  - уведомление снабженцам;
  - синхронизация KPI.
- **Фронт — `features/bpp/alternatives/`:** лента L-09, форма F-07, блок «Альтернативы» для форм F-04/F-05, отчёт R-01.

**Tech Stack:** Django 5.2.7, PostgreSQL (схема на компанию), pytest-django; React 18 + TypeScript + react-query, vitest; xlsx — `services/core/export.py`.

**Spec:**
- ТЗ `docs/tz/TZ-budget-procurement-payments-v1.0.md`:
  - §12.1–§12.9, BR-090…BR-096, CALC-013, KPI-001…004;
  - AC-014…AC-019, REQ-028…REQ-030;
  - меню §5 (пункты 11 «Альтернативы», 12 «Отчёты»).
- [Мастер-план](2026-09-26-bpp-master-plan.md):
  - D-25, D-26 (реестр решений §1);
  - §2.4 (права), §2.6 (контракты);
  - §5, этап 5: A5.1, A5.2, B5.1.
- Ответы: Q-B28, Q-B29, Q-E09, Q-E10, Q-E11, В-19…В-23 — в `docs/plans/2026-09-25-bpp-open-questions.md`.
- Права — [матрица ролей](2026-09-27-bpp-roles-matrix.md), утверждена Алгазы 27.09.

---

## Решения этого плана

**D-S5-1. Кто подаёт АП — по матрице ролей.**
- Создаёт АП держатель `bpp.alternatives` + `create`. По матрице 27.09 это только СН.
- D-25 (Q-E10) разрешает ПМ подавать «до 3 своих». Правило лимита для ПМ заводится в коде (задача 2), но действует, только когда матрица даст ПМ `create`.
- Пока матрица главнее: она утверждена позже D-25. Это вопрос Алгазы (раздел «Ждёт решения»).

**D-S5-2. Лимиты.**
- **На документ** — поле `alt_limit`, по умолчанию 3.
  - У договора поле уже есть. Счёту A добавляет его одной строкой в зоне B.
  - Поднять лимит может СН — автор исходного документа (прочтение (б) Q-E10), не выше 10. Опустить ниже числа уже поданных АП нельзя.
- **На автора** — СН подаёт одну действующую АП к документу, ПМ — до трёх.
- Действующие АП — «Черновик», «Подано», «Выбрано». «Отозвано», «Не выбрано» и «Аннулировано» в лимиты не входят.

**D-S5-3. Состав АП — часть позиций или все (D-25, В-22).**
- В АП входит от одной до всех позиций исходного документа. Количество равно исходному.
- Цена вводится за единицу, **с НДС, если он есть**, — так же, как суммы строк счёта и договора (НДС внутри суммы).
- Экономия считается только по выбранным позициям:
  - исходная часть = Σ сумм этих позиций исходного документа;
  - экономия = исходная часть − сумма АП; обе суммы с НДС, в KZT (CALC-013).

**D-S5-4. Валюта АП.**
- По умолчанию — валюта исходного документа, можно выбрать другую.
- Суммы в KZT пересчитываются на дату подачи по курсу НБРК (`calc.to_kzt`). Курса нет — подача отклоняется `E-REF-05`, как у счёта.
- Исходная часть в KZT считается по курсу исходного документа: у счёта — его `rate`, у договора — `to_kzt` на `ext_date` или на сегодня.

**D-S5-5. АП к открытому договору нельзя.**
- У открытого договора нет цен позиций (ТЗ §9.3 п.2), сравнивать не с чем.
- Отказ: 422 `E-VAL-01` «К открытому договору альтернатива не подаётся: у позиций нет цен». В ТЗ этого случая нет — ставлю в список вопросов.

**D-S5-6. Закрытие АП по решению об исходном документе делает A, выбор — B.**
- Мастер-план отдал закрытие («Оплатить» / утверждение → «Не выбрано»; отзыв, отклонение, возврат, отмена → «Аннулировано») задаче B5.1.
- Эти переходы нужны уже A5.1: без них лимиты и лента врут. Поэтому A делает функцию `lifecycle.close_for_source` и зовёт её из хуков B (коммиты «зона B»).
- B5.1 остаётся только выбор: «Выбрать» по счёту, голоса договора, новые черновики.
- При закрытии черновики АП тоже получают «Аннулировано»: подать их уже нельзя (ТЗ §12.4 п.7 — «при повторной отправке СН может подать АП заново»).

**D-S5-7. KPI подтверждается по статусу нового документа (BR-095, Q-B29).**
- Счёт: «Оплачено» и дальше по оси закрывающих (`paid`, `awaiting_docs`, `docs_provided`, `closed`, D-13) → «Подтверждён». «Оплачено частично» — ещё нет.
- Договор: «Действует» / «Исполнен» → «Подтверждён».
- Аннулирование системой:
  - счёт «Не к оплате», «Отменён», «Заменён альтернативой»;
  - договор «Отклонён»;
  - договор «Расторгнут» без оплаченных счетов.

  Правило одно для «Предварительного» и «Подтверждённого» (ТЗ §12.5).
- Снятая отметка БУХ после подтверждения KPI не откатывает: в §12.5 такого перехода нет.
- Пока KPI «Предварительный», сумма нового документа и экономия пересчитываются при каждой синхронизации (CALC-013, «пересчёт при изменении суммы нового документа до его утверждения»). После «Подтверждён» — заморожены.

**D-S5-8. Синхронизация KPI — одна идемпотентная функция `kpi.sync_for_document(doc_type, doc_id)`.**
- Её зовут хуки B на каждом изменении статуса счёта или договора: отметка оплаты, решение ФД, отмена, колбэки signoff, расторжение.
- Функция сама читает текущий статус. Лишний вызов ничего не меняет, пропущенный лечится следующим.

**D-S5-9. KPI заводится на автора выбранной АП.**
- Роль (`sn` / `pm`) и признак «К своему документу» (BR-092) — колонки записи.
- Итог R-01 считается по всем, роль видна отдельно (D-25, вопрос №18 Алгазы).

**D-S5-10. Параметр «Время ожидания альтернатив» (ТЗ §12.1, [У], по умолчанию 0 часов) на этапе 5 не делается.**
- Ответ Q-B28 — «0 часов, как в ТЗ». Значение 0 значит «не ждать», то есть поведения нет.
- Кнопки решения — у B. Если понадобится, это параметр модуля плюс проверка у B.

**D-S5-11. Метрик и алертов на этапе 5 нет.** Отчёт R-01 — это и есть наблюдение за KPI. Новая метрика без панели не пройдёт `test_metrics_are_observed`, а панель ради панели не нужна.

---

## Global Constraints

- **Окружение.**
  - Интерпретатор — корневой `.venv`, команды из `backend/`: `../.venv/Scripts/python.exe …`.
  - **Один прогон pytest за раз на машине.** Разработчики pytest не запускают, прогоны — у контроллера.
  - Миграции генерирует контроллер.
- **Ветки и коммиты.**
  - Ветки не создавать.
  - Коммитить только файлы своей задачи.
  - Правка в зоне B (`models/invoices.py`, `models/agreements.py`, `services/invoices/*`, `services/agreements/*`, `views_invoices.py`, `views_agreements.py`, экраны `features/bpp/invoices|agreements`) — отдельным коммитом с пометкой «зона B».
- **Межаппный доступ** — только `apps.<x>.interface`.
  - Внутри `bpp` подмодуль `alternatives` читает модели счёта и договора напрямую и блокирует их строки (`select_for_update`). Поля счёта и договора не пишет, кроме `alt_limit`.
- **Ручки и права.**
  - Ручки — `api_view(module="bpp", level=…)`, уровень явный.
  - Права — по узлам матрицы:

    | Действие | Узел и признак |
    |---|---|
    | создать, подать, отозвать свою АП | `bpp.alternatives` create |
    | видеть АП и ленту | `bpp.alternatives` view |
    | отчёт R-01 | `bpp.kpi` view |
    | аннулировать KPI | `bpp.kpi` edit |

  - СН видит в R-01 только свои строки. ПМ видит АП только к своим документам.
- **Деньги** — `Decimal(18,2)`, `ROUND_HALF_UP` (`services/money.py`), никогда не `float`; во фронт — строками.
- **Ошибки** — `DomainError` с текстами ТЗ дословно.

  | Случай | Ответ |
  |---|---|
  | окно подачи закрыто (BR-090) | 422 `E-STATE-01` |
  | тот же контрагент (BR-091) | 422 `E-VAL-01` на `counterparty_id` |
  | лимит исчерпан | 422 `E-VAL-01` на `source_id` |
  | обоснование короче 30 символов при удорожании | 422 `E-VAL-01` на `justification` |
  | комментарий короче 10 символов | 422 `BR-060` |
  | устаревшая версия | 409 `E-CON-01` |

- **Конкурентность.** Подача и отзыв АП блокируют строку исходного документа (`select_for_update`), затем строки АП. Лимиты и окно проверяются под этой блокировкой.
- **Идемпотентность.** Каждая POST-ручка — `idempotent=True`.
- **Журнал.**
  - Каждое изменение АП и KPI — `audit.record`.
  - Типы `bpp.alternativeoffer` и `bpp.kpirecord` регистрируют `audit.register_history_access` рядом с моделью.
- **Фронт.**
  - Строки — `t('bpp.<ключ>', 'Русский текст')`, ошибки — `reportApiError`.
  - Выбор, наполняемый запросом, объясняет пустой список через `PrerequisiteNotice`.
  - Полный `npx vitest run` — без новых падений; `tsc` — не выше 148; `eslint src/features/bpp` — чисто.
- **Тесты после HTTP-запроса.** Чтение и запись БД после запроса тестовым `Client` — внутри `with use_company(slug):`: ответ сбрасывает `search_path` в `public`. «Сегодня» — только через `timezone.localdate()` (сторож `test_platform_today`).
- **Документация.** `API.md`, `STRUCTURE.md`, `CLAUDE.md` правятся в той задаче, что меняет ручки или структуру.

## Review Focus

1. **Гонка за последнее место в лимите.** Лимит 3, подано 2. Два СН одновременно подают третью и четвёртую АП. Проходит ровно одна, вторая получает 422 про лимит. Тест — задача 2 (`transaction=True`, два потока, барьер после чтения).
2. **Подача против решения по исходному документу.** ФД ставит счёту «К оплате» в тот же момент, когда СН подаёт АП. Итог — одно из двух: АП отклонена по BR-090 или подана и сразу «Не выбрано». «Подано» к решённому документу не остаётся. Тест — задача 3.
3. **Частичная АП в валюте.** Счёт в USD на три позиции, АП в KZT на две из них. Экономия считается по двум позициям, исходная часть — по курсу счёта. Процент — от исходной части. Тест — задача 1 (`calc`) и задача 2 (подача).
4. **KPI не откатывается и не дублируется.**
   - Повтор `sync_for_document` ничего не меняет.
   - Снятие отметки БУХ после «Подтверждён» статус не трогает.
   - Допсоглашение к новому договору не меняет подтверждённую экономию.
   - Вторая запись KPI по той же АП невозможна: `offer` уникален в таблице.
   - Тест — задача 5.
5. **Чужие строки R-01.**
   - СН видит в отчёте и выгрузке только свои записи.
   - Карточка чужой записи KPI отвечает 404.
   - Знаменатель KPI-004 не включает «Отозвано» и «Аннулировано».
   - Тест — задача 5.

---

## Контракт для B5.1 (выбор альтернативы)

B зовёт эти функции внутри своей транзакции выбора. Имена и типы окончательные; они же — в мастер-плане §2.6 (правка в задаче 3).

```python
# services/alternatives/lifecycle.py (A, задача 3)
SOURCE_INVOICE = "invoice"
SOURCE_AGREEMENT = "agreement"

def offers_for(source_type: str, source_id, *, statuses=("submitted",)) -> list[AlternativeOffer]
def options_for(source_type: str, source_id) -> list[dict]
#   для signoff options у договора: [{"key": "original", "label": "Исходный документ ДГ-…"},
#   {"key": "offer:<uuid>", "label": "Альтернатива АП-2026-000007 — ТОО «Бета», 2 450 000,00 KZT"}]
def check_option(source_type: str, source_id, option_key: str) -> str | None   # причина отказа или None
def mark_selected(offer_id, *, actor_id: int, comment: str) -> AlternativeOffer
#   под блокировкой исходного документа: выбранная → «Выбрано» (decided_by, decided_at, comment),
#   прочие «Подано» → «Не выбрано»; повтор по уже выбранной — 409 E-STATE-01 (BR-096)
def close_for_source(source_type: str, source_id, outcome: str, *, reason: str) -> int
#   outcome: "not_selected" | "annulled"; зовут хуки (задача 3); возвращает число закрытых АП

# services/alternatives/kpi.py (A, задача 5)
def create_preliminary(offer_id, *, result_type: str, result_id, selected_by_id: int) -> KpiRecord
#   в транзакции выбора, после mark_selected и создания черновика нового документа
#   (при частичной АП — только черновик по альтернативе, D-25)
def sync_for_document(doc_type: str, doc_id) -> None   # D-S5-8, идемпотентна
```

Новый документ по АП заполняет B: контрагент, позиции и цены из `AlternativeOfferLine`, поле «Основание: альтернатива АП-…».

КП переносится во вложения нового документа: `services/core/files.attach` + `files.interface.download_link` / `find_version` (байты текущей версии КП). Какой тип файла у КП в новом документе, решает B.

---

## Волны

- **Волна 1:** задача 1, затем параллельно 2 (dev1) и 5 (dev2) — обе стоят только на моделях задачи 1.
- **Волна 2:** задачи 3 (dev1) и 4 (dev2).
- **Волна 3:** фронт — задачи 6 (dev1) и 7 (dev2).
- **Волна 4:** задача 8 — сквозная проверка, полный прогон, итоговое ревью, PR.

---

## Task 1: Модели, CALC-013, владелец КП

**Files:**
- Create:
  - `backend/apps/bpp/models/alternatives.py`;
  - `backend/apps/bpp/services/alternatives/__init__.py`, `calc.py`, `file_owner.py`.
- Modify (зона B, отдельный коммит): `backend/apps/bpp/models/invoices.py` — `alt_limit = models.PositiveSmallIntegerField(default=3, db_default=3)` у `Invoice`, как у договора.
- Миграция `bpp/0015_alternatives` — генерирует контроллер. Expand: новые таблицы и поле с умолчанием в БД.
- Tests: `backend/apps/bpp/tests/alternatives/__init__.py`, `test_calc.py`, `test_models.py`.

**Модели:**
- **`OfferStatus`:**
  - `draft` «Черновик», `submitted` «Подано», `selected` «Выбрано»;
  - `not_selected` «Не выбрано», `withdrawn` «Отозвано», `annulled` «Аннулировано».
- **`AlternativeOffer(VersionedModel)`:**
  - `number` — уникальный, `АП-ГГГГ-NNNNNN` из `numbering.next_number("АП")`;
  - `source_type` — `invoice` / `agreement`; `source_id` — UUID;
  - `author_id`, `author_role` (`sn` / `pm`), `own_document` (bool, BR-092);
  - `counterparty` — FK `Counterparty`, `PROTECT`;
  - `currency_code`, `rate`, `amount`, `amount_kzt`;
  - `with_vat`, `vat_rate`, `vat_source`, `vat_amount`;
  - `source_amount_kzt` — исходная часть, D-S5-3;
  - `saving_amount`, `saving_pct` (`Decimal(7,2)`);
  - `delivery_date`, `payment_terms` (`full_prepay` / `partial_prepay` / `postpay`), `payment_terms_note`;
  - `justification`, `status`, `submitted_at`;
  - `decided_by_id`, `decided_at`, `decision_comment`;
  - `result_type`, `result_id` (заполняет B5.1);
  - `closed_reason` — почему «Не выбрано» или «Аннулировано».
- **Ограничения `AlternativeOffer`:**
  - `UniqueConstraint(source_type, source_id, counterparty)` при `status in (draft, submitted, selected)` — BR-091;
  - индексы `(source_type, source_id, status)`, `(author_id, status)`.

  Уникальность «один автор — одна АП» кодом, а не БД: у ПМ лимит 3 (D-S5-2).
- **`AlternativeOfferLine(VersionedModel)`:**
  - `offer` — FK, `CASCADE`, `related_name="lines"`;
  - `source_line_id` — UUID строки счёта или позиции договора;
  - `request_item` — FK `PurchaseRequestItem`, `PROTECT`;
  - `qty`, `source_price`, `price`, `amount`;
  - `UniqueConstraint(offer, source_line_id)`; `CheckConstraint(price > 0)`.
- **`KpiStatus`:** `preliminary` «Предварительный», `confirmed` «Подтверждён», `annulled` «Аннулирован».
- **`KpiRecord(VersionedModel)`:**
  - `offer` — `OneToOneField`, `PROTECT` (BR-096: одна запись на АП);
  - `buyer_id`, `buyer_role`, `own_document`;
  - `project_id`, `article_id`;
  - `source_type`, `source_id`, `source_number`, `source_counterparty_id`, `source_amount_kzt`;
  - `result_type`, `result_id`, `result_number`, `result_amount_kzt`;
  - `saving_amount`, `saving_pct`;
  - `selected_at`, `selected_by_id`;
  - `status`, `status_changed_at`;
  - `annul_comment`, `annulled_by_id`;
  - индексы `(buyer_id, status)`, `(selected_at)`.
- Журнал: рядом с моделями — `audit.register_history_access("bpp.alternativeoffer", can_view)` и `("bpp.kpirecord", can_view)`. Сами `can_view` — в `read.py` (задача 4) и `report.py` (задача 5). Регистрация по пути импорта строкой, как у документов B.

```python
# services/alternatives/calc.py — CALC-013 и суммы АП, без БД
from decimal import Decimal
from apps.bpp.services.money import money, line_amount

def offer_amount(lines: list[tuple[Decimal, Decimal]]) -> Decimal:
    """Σ qty × price по строкам АП (цены с НДС, если он есть)."""
    return money(sum((line_amount(qty, price) for qty, price in lines), Decimal("0")))

def source_part(lines: list[tuple[Decimal, Decimal]]) -> Decimal:
    """Σ сумм выбранных позиций исходного документа (D-S5-3)."""
    return money(sum((amount for _, amount in lines), Decimal("0")))

def saving(source_kzt: Decimal, offer_kzt: Decimal) -> tuple[Decimal, Decimal]:
    """CALC-013: экономия KZT и % от исходной части (0,01 %). Отрицательная — удорожание."""
    amount = money(source_kzt - offer_kzt)
    pct = (amount * 100 / source_kzt).quantize(Decimal("0.01")) if source_kzt else Decimal("0.00")
    return amount, pct

def source_price(amount: Decimal, qty: Decimal) -> Decimal:
    """Цена позиции исходного документа за единицу: сумма / количество, до копеек."""
    return money(amount / qty)
```

**`file_owner.py`** — `register()` по образцу `services/bank/file_owner.py`:
- `register_owner("bpp.alternative_offer", tenant=True, service="bpp_alternatives", folder="alternative-offer", model=AlternativeOffer, file_types=(FileTypeSpec("alternative_offer", max_documents=5, required=True),), …)`;
- `can_view` — видит АП (задача 4 уточнит, пока — автор, ФД, ТД, ОД, ГД по узлу `bpp.alternatives` view);
- `can_modify` — только автор и только «Черновик», иначе `FilesLocked` «КП меняется только в черновике АП»;
- `was_sent` — статус не «Черновик»; `lock` — `select_for_update` строки АП;
- плюс `services.core.files.register_owner_type(AlternativeOffer, "bpp.alternative_offer")`.

- [ ] **Step 1: Падающие тесты:**
  - `test_saving_positive_and_negative`:
    - `saving(Decimal("2800000"), Decimal("2450000"))` → `(350000.00, 12.50)` (AC-014);
    - `saving(Decimal("3900000"), Decimal("4500000"))` → `(-600000.00, -15.38)`.
  - `test_offer_amount_rounds_per_line`: `offer_amount([(Decimal("3"), Decimal("33.335"))])` → `100.01` (строка 3 × 33,335 = 100,005 → 100,01, `ROUND_HALF_UP`).
  - `test_source_price_divides_amount_by_qty`: `source_price(Decimal("100.00"), Decimal("3"))` → `33.33`.
  - `test_saving_on_zero_source_is_zero_pct` — без деления на ноль.
  - `test_offer_counterparty_unique_among_live` — вторая действующая АП с тем же контрагентом к тому же документу — `IntegrityError`; после «Отозвано» — проходит.
  - `test_kpi_record_one_per_offer` — вторая `KpiRecord` на ту же АП — `IntegrityError`.
  - `test_invoice_alt_limit_defaults_to_three`.
- [ ] **Step 2: Реализация.** Контроллер генерирует `0015_alternatives`; `makemigrations --check` — «No changes».
- [ ] **Step 3: Прогон** (контроллер): `apps/bpp/tests/alternatives`, `apps/bpp/tests/test_file_owner_discovery.py`, `apps/bpp/tests/test_files.py`.
- [ ] **Документация:** `STRUCTURE.md` — подмодуль `alternatives` в строке `bpp` и в дереве `apps/bpp`.
- [ ] **Коммиты:**
  - `feat(bpp): модели альтернатив и KPI, экономия CALC-013, КП в подсистеме файлов (A5.1, часть 1)`;
  - отдельно — `feat(bpp): лимит альтернатив у счёта — поле alt_limit (зона B)`.

## Task 2: АП — черновик, подача, отзыв, лимиты (A5.1)

**Files:**
- Create:
  - `backend/apps/bpp/services/alternatives/offers.py`;
  - `backend/apps/bpp/schemas/alternatives.py`;
  - `backend/apps/bpp/views_alternatives.py`, `backend/apps/bpp/urls_alternatives.py`.
- Tests: `backend/apps/bpp/tests/alternatives/common.py` (помощники: счёт без договора «На рассмотрении ФД», договор «На согласовании», СН, ПМ, ФД — поверх помощников `tests/test_invoices.py` и `tests/test_agreements.py`), `test_offers.py`.

**Interfaces:**
- Consumes: модели и `calc` задачи 1; `invoices.invoices.lock`, модель `Agreement`; `calc.vat_for`, `calc.to_kzt`; `numbering.next_number`; `notifications.interface.notify`.
- Produces: функции ниже — задачи 3, 4, 6 и B5.1 опираются на них.

```python
def source_of(source_type: str, source_id, *, lock: bool = False) -> Invoice | Agreement   # 404 на чужой вид / нет
def window_open(source) -> bool          # BR-090: счёт no_contract under_review без fd_decided_at; договор on_review
def create(actor, *, source_type, source_id) -> AlternativeOffer                 # «Черновик»
def update_draft(actor, offer_id, *, expected_version, data: dict) -> AlternativeOffer
def delete_draft(actor, offer_id, *, expected_version) -> None
def submit(actor, offer_id, *, expected_version) -> AlternativeOffer             # «Подано»
def withdraw(actor, offer_id, *, expected_version) -> AlternativeOffer           # «Отозвано»
def set_limit(actor, *, source_type, source_id, limit: int) -> int               # D-S5-2
def allowed_actions(actor, offer) -> list[str]
```

Правила (ТЗ §12.1, §12.3, §12.7, BR-090…092):
- **`create`:**
  - право `bpp.alternatives` create;
  - исходный документ — счёт без договора или договор; счёт по договору → 422 `E-VAL-01` на `source_id`: «Альтернатива к счёту по договору не подаётся»;
  - окно открыто;
  - договор не открытый (D-S5-5);
  - лимиты не исчерпаны (D-S5-2, проверка ещё раз при подаче).
- **Черновик при создании:** все позиции исходного документа, цены пустые, валюта — исходного документа. `own_document = author_id == source.author_id`; `author_role` — по группе статей автора (`Actor.initiator_roles`: `sn` при группе «Снабжение», иначе `pm`).
- **`update_draft` принимает:**
  - `counterparty_id` — «Активен», ≠ контрагенту исходного, ≠ контрагентам других действующих АП (BR-091), иначе 422 на `counterparty_id` «Контрагент совпадает с исходным или с другой альтернативой по документу»;
  - `lines[{source_line_id, price}]` — подмножество позиций, минимум одна, `price > 0`;
  - `currency_code`, `delivery_date` (≥ сегодня), `payment_terms`, `payment_terms_note`, `justification` (10–2000), `with_vat`, `vat_rate` (ручная ставка — как у счёта, `vat_source="manual"`).

  После каждой правки пересчитываются: НДС (`calc.vat_for` страны контрагента на сегодня, если не ручная), суммы строк, `amount`, `source_amount_kzt`, `saving_*`. `amount_kzt` — если курс есть; нет — пусто.
- **`submit`** — под блокировкой исходного документа (`source_of(lock=True)`), затем АП:
  1. окно открыто, иначе 422 `E-STATE-01` «Документ уже решён — альтернатива не подаётся»;
  2. лимит документа: число «Подано» + «Выбрано» < `alt_limit`, иначе 422 на `source_id` «К документу уже подано N альтернатив — это лимит»;
  3. лимит автора: у СН нет другой действующей АП, у ПМ их меньше трёх;
  4. обязательные поля заполнены, КП приложен (`files.list_files` владельца — хотя бы один документ), иначе 422 со списком полей;
  5. `amount_kzt` посчитан, иначе `E-REF-05`;
  6. если `saving_amount < 0` — обоснование ≥ 30 символов, иначе 422 на `justification` «Альтернатива дороже исходного — опишите причину (сроки, качество, наличие), не короче 30 символов».

  Затем: `status=submitted`, `submitted_at`, `audit.record`, уведомление ФД (держатели `bpp.invoices.decision` edit) и автору исходного документа: «Подана альтернатива АП-… к СЧ-…: экономия 350 000,00 KZT (12,5 %)», ссылка на исходный документ.
- **`withdraw`** — автор, «Подано», окно ещё открыто, иначе `E-STATE-01`.
- **`delete_draft`** — автор, «Черновик». Физическое удаление плюс `files.owner_deleted`.
- **`set_limit`** — СН-автор исходного документа, окно открыто, `limit` в `[число поданных, 10]`, иначе 422 на `limit`. `audit.record` у исходного документа.

Ручки (`urls_alternatives.py`, префикс `alternatives/`):

| Метод и путь | Что делает |
|---|---|
| `POST alternatives/offers` | `{source_type, source_id}` → черновик |
| `GET alternatives/offers/<id>` | карточка АП (задача 4 дополнит сравнением) |
| `PATCH alternatives/offers/<id>` | правка черновика, `version` |
| `DELETE alternatives/offers/<id>` | удалить черновик, `version` |
| `POST alternatives/offers/<id>/submit` | подать, `version` |
| `POST alternatives/offers/<id>/withdraw` | отозвать, `version` |
| `POST alternatives/sources/<source_type>/<source_id>/limit` | `{limit}` |

- [ ] **Step 1: Падающие тесты** (`test_offers.py`):
  - `test_ac014_saving_visible_after_submit` — счёт без договора на 2 800 000 от ПМ, АП на 2 450 000 с КП → «Подано», экономия `350000.00`, `12.50`.
  - `test_offer_to_contract_invoice_is_422`.
  - `test_same_counterparty_as_source_is_422_br091` и `test_same_counterparty_as_other_offer_is_422`.
  - `test_own_document_flag_ac018` — СН — автор счёта, АП к своему счёту принимается, `own_document=True`.
  - `test_window_closed_after_fd_decision_is_422` — после `decide(to_pay)` подача отклоняется.
  - `test_document_limit_and_raise` — три АП от трёх СН, четвёртая — 422; автор-СН поднимает лимит до 4 — проходит; поднять до 11 — 422; опустить ниже поданных — 422.
  - `test_one_offer_per_buyer` — второй черновик того же СН к тому же документу — 422.
  - `test_partial_offer_saving_on_chosen_lines_only` — счёт в USD (курс 500) на позиции A, B, C; АП в KZT на A и B; исходная часть = (A + B) × 500 (Review Focus 3).
  - `test_more_expensive_needs_30_chars` — удорожание с обоснованием 29 символов — 422, 30 — проходит.
  - `test_submit_requires_kp_file`.
  - `test_race_for_last_limit_slot` (`transaction=True`, два потока, барьер после чтения) — Review Focus 1.
  - `test_open_agreement_is_422` (D-S5-5).
  - Права:
    - ТД создаёт — 403;
    - ПМ создаёт — 403 (D-S5-1);
    - чужой СН правит черновик — 403;
    - повтор POST с тем же `Idempotency-Key` — одна АП и одна запись журнала.
- [ ] **Step 2: Реализация.**
- [ ] **Step 3: Прогон** (контроллер): `apps/bpp/tests/alternatives`, сторожа (`test_gate`, `test_app_isolation`, `test_invariants`, `test_bpp_scaffold`).
- [ ] **Документация:** `API.md` — раздел «Альтернативы (A5.1)» с ручками и кодами ошибок.
- [ ] **Коммит** — `feat(bpp): альтернативные предложения — черновик, подача, отзыв, лимиты BR-090…092 (A5.1, часть 2)`.

## Task 3: Жизненный цикл АП и контракт для B5.1

**Files:**
- Create: `backend/apps/bpp/services/alternatives/lifecycle.py` — функции контракта (раздел «Контракт для B5.1») и `notify_buyers`.
- Modify (зона B, отдельный коммит):
  - `backend/apps/bpp/services/invoices/decisions.py` — после решения ФД: `to_pay` → `close_for_source(..., "not_selected")`, `not_payable` / `returned` → `"annulled"`;
  - `backend/apps/bpp/services/invoices/invoices.py`:
    - `cancel` → `"annulled"`;
    - `on_started` у счёта без договора → `lifecycle.notify_buyers(...)`;
  - `backend/apps/bpp/services/agreements/agreements.py`:
    - `on_approved` → `"not_selected"`;
    - `on_rejected`, `on_rework`, `on_cancelled`, `withdraw` → `"annulled"`;
    - `on_started` → `notify_buyers`.

  Каждая точка — один вызов в той же транзакции.
- Modify: мастер-план `docs/plans/2026-09-26-bpp-master-plan.md` §2.6 — блок контракта из этого плана; строка B5.1 в §5 — «закрытие АП по решению об исходном документе сделано A (D-S5-6)».
- Tests: `backend/apps/bpp/tests/alternatives/test_lifecycle.py`.

**Правила:**
- **`close_for_source`** — `select_for_update` АП документа в статусах `draft` / `submitted`:
  - `outcome="not_selected"` — «Подано» → «Не выбрано», «Черновик» → «Аннулировано»;
  - `outcome="annulled"` — обе → «Аннулировано»;
  - `closed_reason` — текст («Счёт принят к оплате без выбора альтернативы», «Документ возвращён на доработку» …);
  - `audit.record` на каждую АП, уведомление её автору.
- **`mark_selected`:**
  - АП «Подано», окно исходного документа ещё открыто (B зовёт до смены статуса исходного);
  - у документа ещё нет «Выбрано», иначе 409 `E-STATE-01` «Документ уже заменён альтернативой» (BR-096);
  - выбранная → «Выбрано», прочие «Подано» → «Не выбрано», черновики → «Аннулировано».
- **`options_for`** — «Исходный документ» и все «Подано» (порядок — по номеру).
- **`check_option`:**
  - `original` — всегда `None`;
  - `offer:<id>` — `None`, если АП «Подано» и относится к документу, иначе причина «Альтернатива отозвана или уже не действует».
- **`notify_buyers(source_type, source_id)`:**
  - получатели — держатели `bpp.alternatives` create в компании (`access.interface.holders_of`) минус автор документа;
  - текст ТЗ §12.2 дословно по образцу: «ПМ Иванов А. отправил счёт СЧ-2026-000140 на 2 800 000,00 KZT, ТОО „Альфа“. Можно предложить альтернативу»;
  - ссылка — `/bpp/alternatives?source=<type>:<id>`;
  - у договора — «договор ДГ-…».
- Гонка из Review Focus 2 закрывается порядком блокировок: `submit` держит строку исходного документа, а решение ФД (`decide`) тоже её блокирует (`invoices.lock`). Кто второй, тот видит результат первого.

- [ ] **Step 1: Падающие тесты:**
  - `test_ac017_pay_sets_offers_not_selected` — «К оплате» по исходному → все «Подано» — «Не выбрано».
  - `test_returned_rejected_cancelled_annul` — возврат, «Не к оплате», отмена счёта, отклонение, доработка, отзыв договора → «Аннулировано», черновики тоже.
  - `test_resubmitted_source_accepts_new_offers` — после возврата и повторной отправки СН подаёт АП заново (§12.4 п.7).
  - `test_mark_selected_closes_others_and_is_single` — выбранная «Выбрано», вторая «Не выбрано»; повтор `mark_selected` по той же АП — 409; по другой АП того же документа — 409.
  - `test_options_for_agreement_lists_original_and_submitted`.
  - `test_submit_vs_fd_decision_race` (`transaction=True`, два потока) — Review Focus 2: «Подано» к решённому счёту не остаётся.
  - `test_buyers_notified_on_source_start` — все СН, кроме автора; у ПМ-автора уведомления нет.
- [ ] **Step 2: Реализация.**
- [ ] **Step 3: Прогон** (контроллер): `apps/bpp/tests/alternatives`, `apps/bpp/tests/test_invoices.py`, `apps/bpp/tests/test_agreements.py`, сторожа.
- [ ] **Документация:** `API.md` (уведомление СН, закрытие АП), мастер-план §2.6 и §5.
- [ ] **Коммиты:**
  - `feat(bpp): жизненный цикл альтернатив и контракт выбора для B5.1 (A5.1, часть 3)`;
  - отдельно — `feat(bpp): счёт и договор закрывают альтернативы и зовут снабженцев (зона B)`.

## Task 4: Лента L-09, сравнение, карточка АП

**Files:**
- Create: `backend/apps/bpp/services/alternatives/read.py`.
- Modify: `views_alternatives.py`, `urls_alternatives.py`, `schemas/alternatives.py`.
- Tests: `backend/apps/bpp/tests/alternatives/test_read.py`.

**Interfaces:**
- Consumes: задачи 1–3; `refdata.interface.article_brief`, `users.interface.get_users_brief`.
- Produces: `can_view(actor, offer) -> bool` (журнал, файлы); ручки ниже — контракт экранов задачи 6.

**Видимость:**
- **АП видят:**
  - автор;
  - ФД, ТД, ОД, ГД (`bpp.alternatives` view, кроме ПМ);
  - ПМ — только АП к своим документам (матрица: «V (свои документы)»);
  - автор исходного документа.

  Чужая АП — 404.
- **Черновик** видит только автор.

**Ручки:**

| Метод и путь | Что делает |
|---|---|
| `GET alternatives/feed` | Лента L-09 `{items, total, page, page_size}` (ТЗ §12.2): договоры «На согласовании» и счета без договора «На рассмотрении ФД» без решения ФД, в том числе свои. Колонки: документ (номер, вид), автор, проект, статья, контрагент, позиции (кратко: первые 3 наименования + «ещё N»), сумма, отправлен, альтернатив подано, моя альтернатива (номер и статус или `null`). Фильтры: `kind`, `author_id`, `project_id` (повторяемый), `article_id` (повторяемый), `counterparty_id`, `q` (по наименованию позиций), `amount_from` / `amount_to`, `sent_from` / `sent_to`, `without_offers=1`, `mine=yes|no`, `source=<type>:<id>`. Сортировка — «отправлен», новые сверху. Право `bpp.alternatives` view |
| `GET alternatives/sources/<source_type>/<source_id>/comparison` | Сравнение (ТЗ §12.4 п.2): исходный документ и каждая видимая АП (кроме черновиков чужих) в колонках. Строки: контрагент, страна, сумма, НДС, экономия (KZT и %, отрицательная — `more_expensive: true`), срок, условия оплаты, КП (список файлов из папки), автор, статус. Позиции — таблица «исходная цена / цена АП» по каждой позиции. Плюс `limit`, `submitted_count`, `can_propose` (кнопка «Предложить альтернативу» по BR-090 и лимитам), `my_offer_id` |
| `GET alternatives/offers/<id>` | Карточка: поля F-07, строки с исходной ценой и отклонением %, `allowed_actions`, `version` |
| `GET alternatives/offers?mine=1&status=` | «Мои альтернативы» автора |

- [ ] **Step 1: Падающие тесты:**
  - `test_feed_lists_open_sources_only` — счёт по договору, решённый счёт, договор-черновик в ленту не попадают.
  - `test_feed_filters_without_offers_and_mine`.
  - `test_feed_counts_live_offers_only` — «Отозвано» и «Аннулировано» не считаются.
  - `test_comparison_ac014` — строка экономии `350000.00` / `12.50`.
  - `test_comparison_hides_foreign_drafts`.
  - `test_pm_sees_offers_to_own_documents_only` — чужая АП → 404.
  - `test_history_of_offer_requires_view` — журнал `bpp/v1/history/bpp.alternativeoffer/<id>` чужому СН → 404.
  - Права: БУХ → 403 на ленту.
- [ ] **Step 2: Реализация.** Счётчики ленты — одним запросом (подзапрос `Count` по АП), без N+1.
- [ ] **Step 3: Прогон** (контроллер): `apps/bpp/tests/alternatives`, сторожа.
- [ ] **Документация:** `API.md`.
- [ ] **Коммит** — `feat(bpp): лента «Закупки для альтернатив» L-09 и сравнение предложений (A5.1, часть 4)`.

## Task 5: KPI — запись, подтверждение, аннулирование, отчёт R-01 (A5.2)

**Files:**
- Create:
  - `backend/apps/bpp/services/alternatives/kpi.py` — `create_preliminary`, `sync_for_document`, `annul`, `can_view`;
  - `backend/apps/bpp/services/alternatives/report.py` — R-01.
- Modify: `views_alternatives.py`, `urls_alternatives.py` (префикс `kpi/`).
- Modify (зона B, отдельный коммит): вызов `kpi.sync_for_document(<тип>, <id>)` после смены статуса в:
  - `services/invoices/payments.py` — `mark_paid`, `unmark`;
  - `services/invoices/decisions.py` — `decide`;
  - `services/invoices/invoices.py` — `cancel`, `on_rejected`, `on_cancelled`;
  - `services/agreements/agreements.py` — `on_approved`, `on_rejected`, `on_cancelled`, `fulfil`, `terminate`.

  До выбора (B5.1) вызов — пустой запрос: у документа нет записи KPI.
- Tests: `backend/apps/bpp/tests/alternatives/test_kpi.py`, `test_report.py`.

**Interfaces:**
- Consumes: модели задачи 1, `lifecycle.mark_selected` (в тестах — вместо B5.1), `services/core/export.write_xlsx`.
- Produces: `create_preliminary`, `sync_for_document` — контракт B5.1; ручки — контракт экрана задачи 7.

**`create_preliminary(offer_id, *, result_type, result_id, selected_by_id)`:**
- АП «Выбрано», записи ещё нет.
- Снимок: покупатель, роль, `own_document`, проект и статья исходного документа, исходный номер, контрагент, `source_amount_kzt` АП, результат (номер и сумма в KZT текущие), экономия, `selected_at = now`.
- `status=preliminary`, `audit.record`.

**`sync_for_document(doc_type, doc_id)`** — `select_for_update` записи с `result_type/result_id`, по статусу нового документа (D-S5-7):

| Новый документ | Статус документа | KPI |
|---|---|---|
| счёт | `paid`, `awaiting_docs`, `docs_provided`, `closed` | «Подтверждён», сумма и экономия заморожены |
| счёт | `not_payable`, `cancelled`, `replaced` | «Аннулирован» |
| договор | `active`, `fulfilled` | «Подтверждён» |
| договор | `rejected` | «Аннулирован» |
| договор | `terminated` и нет счетов в группе «Оплачено» | «Аннулирован» |
| любой | прочие | если «Предварительный» — пересчитать `result_amount_kzt` и экономию |

«Аннулирован» — финальный. «Подтверждён» не откатывается в «Предварительный». Каждое изменение — `audit.record` и `status_changed_at`.

**`annul(actor, kpi_id, *, comment, expected_version)`:**
- право `bpp.kpi` edit (ФД);
- статус не «Аннулирован»;
- комментарий ≥ 10 символов, иначе `BR-060`;
- `annulled_by_id`, `annul_comment`, `audit.record`.

**R-01 (`report.py`)** — фильтры `period_from` / `period_to` (по дате выбора; «подано» — по `submitted_at`), `buyer_id`, `project_id`, `article_id`. Строки — по покупателю:

| Колонка | Что считает |
|---|---|
| `buyer_id`, `name`, `role` | покупатель и роль |
| `submitted` | АП «Подано», «Выбрано», «Не выбрано» за период, по `submitted_at` |
| `selected` | записи KPI любого статуса |
| `confirmed` | KPI-001 |
| `share_pct` | KPI-004: `confirmed / submitted × 100`; при нулевом знаменателе — `null` |
| `saving` | KPI-002: Σ положительной экономии «Подтверждён» |
| `overspend` | KPI-003: Σ модуля отрицательной экономии «Подтверждён» |
| `own_document_count` | записи с признаком «К своему документу» |

Итоговая строка — по всем покупателям. СН видит только свою строку и свои записи (D-S5-9, ТЗ §12.6).

**Ручки:**

| Метод и путь | Что делает |
|---|---|
| `GET kpi/report` | R-01 `{rows, total, filters}`; право `bpp.kpi` view |
| `GET kpi/records?buyer_id=&status=&…` | записи KPI для перехода из ячейки, с номерами и ссылками на документы |
| `GET kpi/records/<id>` | карточка записи KPI |
| `POST kpi/records/<id>/annul` | `{comment, version}` |
| `GET kpi/report/export` | xlsx: лист «KPI снабжения» (строки отчёта) и лист «Записи KPI»; суммы — числа |

- [ ] **Step 1: Падающие тесты** (`test_kpi.py`). Выбор имитирует `lifecycle.mark_selected` + черновик нового счёта через `invoices.create_from_plan` + `kpi.create_preliminary` — так же, как сделает B5.1.
  - `test_ac015_preliminary_then_confirmed_on_paid` — отметка «Оплачено» по новому счёту → «Подтверждён», экономия `350000.00`.
  - `test_partially_paid_keeps_preliminary`.
  - `test_ac019_not_payable_annuls_and_excludes_from_kpi`.
  - `test_preliminary_recomputes_saving_on_new_amount` — сумма черновика нового счёта меняется, экономия пересчитана; после «Подтверждён» — нет.
  - `test_sync_is_idempotent_and_unmark_does_not_revert` — Review Focus 4.
  - `test_supplement_does_not_change_confirmed_saving` — договор «Действует», допсоглашение увеличило сумму → экономия прежняя.
  - `test_terminated_without_paid_invoices_annuls`.
  - `test_manual_annul_requires_fd_and_10_chars`.
  - `test_own_document_flag_in_record_ac018`.
- [ ] **Step 2: Падающие тесты** (`test_report.py`):
  - `test_r01_counts_and_share` — два СН, пять АП (одна отозвана, одна аннулирована), две подтверждены: `share_pct` без отозванной и аннулированной (Review Focus 5).
  - `test_r01_saving_and_overspend_separate` — KPI-003 не вычитается из KPI-002.
  - `test_buyer_sees_only_own_rows_and_records` — чужая запись → 404, выгрузка — только своё.
  - `test_export_two_sheets_numeric`.
  - `test_period_filters_by_selected_at`.
  - Права: ТД → 403, БУХ → 403, ОД и ГД видят всё, СН не может аннулировать → 403.
- [ ] **Step 3: Реализация.**
- [ ] **Step 4: Прогон** (контроллер): `apps/bpp/tests/alternatives`, `apps/bpp/tests/test_invoices.py`, `apps/bpp/tests/test_agreements.py`, `apps/bpp/tests/test_export.py`, сторожа.
- [ ] **Документация:** `API.md` — раздел «KPI (A5.2)».
- [ ] **Коммиты:**
  - `feat(bpp): KPI снабжения — запись, подтверждение по оплате, аннулирование, отчёт R-01 (A5.2)`;
  - отдельно — `feat(bpp): счёт и договор синхронизируют KPI при смене статуса (зона B)`.

## Task 6: Экраны альтернатив — лента L-09, форма F-07, блок сравнения

**Files** (`frontend/src/features/bpp/alternatives/`):
- Create:
  - `module.tsx` — пункт меню «Альтернативы» (`order: 65`, между «Счета» 60 и «Оплаты факт» 70), видимость по `bpp.alternatives` view;
  - `api.ts` — ключи `['bpp','alternatives',…]`, запросы задач 2–4;
  - `AlternativesFeedPage.tsx` — лента L-09 на `BppRegistry`, фильтры §12.2, фильтр `source` из адреса (ссылка уведомления);
  - `OfferFormPage.tsx` — F-07 (§12.3):
    - read-only блок исходного документа;
    - контрагент — общий `CounterpartyPicker`;
    - таблица позиций с галочкой «входит в АП» и ценой;
    - на лету: сумма строки, отклонение %, сумма АП, экономия (отрицательная — оранжевым «Дороже на …»);
    - срок, условия оплаты, обоснование со счётчиком (30 символов при удорожании);
    - КП — общая панель файлов подсистемы, как у заявки;
    - кнопки «Сохранить черновик», «Подать», «Отозвать», «Удалить черновик» по `allowed_actions`;
  - `AlternativesBlock.tsx` — блок «Альтернативы» для F-04/F-05:
    - таблица сравнения (исходный + АП в колонках);
    - кнопка «Предложить альтернативу» (`can_propose`);
    - «Моя альтернатива»;
    - слот `renderSelect?: (offer) => ReactNode` для кнопки «Выбрать» B5.1;
    - поле лимита с «Поднять» для автора-СН;
  - `money.ts` — расчёты в целых копейках (`bigint`), как `bank/amounts.ts`;
  - тесты.
- Modify (зона B, отдельный коммит): `features/bpp/invoices/InvoiceFormPage.tsx` и `features/bpp/agreements/AgreementFormPage.tsx` — вставить `<AlternativesBlock sourceType=… sourceId=… />` под позициями, только у счёта без договора и у договора. Плюс тест, что блок появился.
- Modify: `core/statusDictionaries.ts` — словарь `alternative_offer` (шесть статусов) и `kpi_record` (три).

- [ ] **Step 1: Тесты vitest:**
  - лента: фильтры уходят в запрос, «без альтернатив» и «моя альтернатива»;
  - форма:
    - экономия и отклонение считаются на лету без `float`: 2 800 000 − 2 450 000 → «350 000,00 KZT (12,50 %)»;
    - удорожание подсвечено, «Подать» не отправляет обоснование короче 30 символов;
    - снятая галочка позиции исключает её из суммы и из запроса;
    - ошибка `E-VAL-01` с `fields` показывается у поля;
  - блок:
    - `can_propose=false` прячет кнопку;
    - чужой черновик не показывается;
    - слот `renderSelect` вызывается для каждой «Подано»;
  - пункт меню скрыт без права.
- [ ] **Step 2: Реализация.** Полный `npx vitest run`, `eslint src/features/bpp`, `tsc` не выше 148.
- [ ] **Документация:** `STRUCTURE.md` — дерево `features/bpp/alternatives`.
- [ ] **Коммиты:**
  - `feat(bpp): экраны альтернатив — лента L-09, форма F-07, блок сравнения (A5.1, часть 5)`;
  - отдельно — `feat(bpp): блок «Альтернативы» в формах счёта и договора (зона B)`.

## Task 7: Экран отчёта R-01 и записи KPI

**Files** (`frontend/src/features/bpp/kpi/`):
- Create:
  - `module.tsx` — пункт меню «Отчёты» (`order: 85`, после «Дашборд оплат» 80), видимость по `bpp.kpi` view;
  - `api.ts`;
  - `KpiReportPage.tsx`:
    - фильтры: период, СН, проект, статья — выборы с `PrerequisiteNotice`;
    - таблица R-01 с итогом; клик по ячейке открывает список записей с этим отбором (`KpiRecordsDrawer`);
    - «Экспорт xlsx»;
  - `KpiRecordPage.tsx` — карточка записи:
    - ссылки на исходный документ, АП и новый документ;
    - статус, признак «К своему документу», история;
    - «Аннулировать» (ФД, диалог комментария ≥ 10 — общий `CommentDialog` из `bank/` вынести в `core/`, если он там ещё не лежит);
  - тесты.

- [ ] **Step 1: Тесты vitest:**
  - фильтр перечитывает отчёт;
  - доля `null` показывается «—»;
  - суммы — `formatMoney` из строк;
  - клик по ячейке «подтверждено» открывает записи с `status=confirmed` и `buyer_id`;
  - «Аннулировать» скрыта без `bpp.kpi` edit;
  - комментарий из 9 символов не отправляется;
  - после аннулирования отчёт и карточка перечитываются.
- [ ] **Step 2: Реализация.** Полный `npx vitest run`, `eslint`, `tsc`.
- [ ] **Коммит** — `feat(bpp): отчёт «KPI снабжения» R-01 и карточка записи KPI (A5.2, часть 2)`.

## Task 8: Сквозная проверка этапа, прогон, ревью, PR

- [ ] **Сквозной тест** `backend/apps/bpp/tests/test_stage5_e2e.py` — одна история:
  1. ПМ отправляет счёт без договора на 2 800 000. СН получают уведомление.
  2. СН-1 подаёт АП на 2 450 000 с КП. СН-2 подаёт АП дороже, с обоснованием.
  3. Сравнение: экономия 350 000 (12,5 %) и удорожание у второй.
  4. Выбор АП-1 — имитация B5.1: `mark_selected` + черновик нового счёта + `create_preliminary`. АП-2 «Не выбрано», KPI «Предварительный».
  5. Новый счёт отправлен, ФД «К оплате», БУХ «Оплачено» → KPI «Подтверждён». R-01: у СН-1 подано 1, подтверждено 1, экономия 350 000; у СН-2 подано 1, доля 0 %.
  6. Второй счёт: ФД «К оплате» без выбора → его АП «Не выбрано» (AC-017).
- [ ] **Прогоны:**
  - весь бэкенд без `ci-known-failures.txt`, по аппкам, по одному (контроллер);
  - полный `npx vitest run`, `tsc`, `eslint`.
- [ ] **CLAUDE.md** — абзац про альтернативы и KPI в разделе «Модуль БЗО», рядом с абзацем про выписку: что сделано, контракт B5.1, зона B.
- [ ] **Итоговое ревью** ветки отдельным ревьюером. Critical и Important исправить, мелочи — в журнал.
- [ ] **PR** в `new-module-BPP-merge`.

---

## Сведение с B

- **Общие файлы:**
  - `InvoiceFormPage.tsx`, `AgreementFormPage.tsx` — вставка блока;
  - `services/invoices/{decisions,invoices,payments}.py`, `services/agreements/agreements.py` — вызовы хуков, по одной строке;
  - `models/invoices.py` — `alt_limit`;
  - `API.md`, `STRUCTURE.md`.
- **Миграции:** у A — `bpp/0015_alternatives`. Если у B к сведению есть своя `0015`, нужна merge-миграция.

## Остаток B на этапе 5 (Руслан) — справочно

| # | Что | На чём стоит |
|---|---|---|
| B-1 | **B5.1 «Выбрать»** по счёту: ФД, комментарий. В одной транзакции: `mark_selected` → исходный «Заменён альтернативой», этапы аннулированы, позиции освобождены → черновик(и) нового документа (часть позиций → два черновика, D-25; > 1000 МРП → договор, BR-094; разница ≤ остатка статьи, BR-093; автор — автор заявки) → `kpi.create_preliminary` | задачи 3, 5 |
| B-2 | **B5.1 по договору:** варианты signoff — `options_for` / `check_option`; `votes_option` у этапов ФД и ГД; решающий голос ГД. Новый договор по АП: предсогласован только этап ГД (D-26, `start_process(preapproved=…)`). Уведомление уже проголосовавшим о новой АП (ТЗ §12.4 п.1) | задача 3 |
| B-3 | Сумма нового документа отличается от АП не более чем на 5 % без повторного выбора (ТЗ §12.4 п.5) — проверка при отправке нового документа | B-1 |
| B-4 | Кнопка «Выбрать» в слоте `renderSelect` блока «Альтернативы» (задача 6) | задача 6 |
| B-5 | Сверка: хуки закрытия АП и синхронизации KPI в своих сервисах — проверить, что ни одна новая точка смены статуса их не обходит | задачи 3, 5 |

## Ждёт решения пользователя (вопросы Алгазы)

- **ПМ подаёт АП?** D-25 разрешает до трёх своих, а матрица 27.09 даёт ПМ только просмотр. План идёт по матрице (D-S5-1). Если ПМ подаёт — одна строка `create` в правах, правило лимита уже в коде.
- **АП к открытому договору** запрещена (D-S5-5). Нужна ли?
- **KPI ПМ** (вопрос №18). Засчитывать ли ему KPI, если выбрана его альтернатива?
- **«Время ожидания альтернатив»** (§12.1, 0 часов). Не делаем (D-S5-10). Нужно ли вообще?
