# Тендерный модуль — спецификация этапа 5: сравнение, выбор, передача в БЗО, поставка (T5.1 … T5.7)

20.10.2026 · ветка `tender` (не пушится до конца модуля) · поверх [мастер-плана](2026-10-06-tender-master-plan.md) (решения T-01…T-31, пакет B-2 — §3.4), [ТЗ](../tz/TZ-tender-procurement-v1.0.md) (TND-020…TND-042, «Оплата и доставка») и состояния кода после этапа 3 ([план этапа 3](2026-10-07-tender-stage3-portal-plan.md)). Порядок старшинства — мастер-план → эта спека → ТЗ. Новые решения этапа — **S5-01…S5-20** (§6); где прямого ответа нет, стоит **[умолч.]** с вопросом к Алгазы или пользователю.

**Что есть в коде на 20.10.** Статусы тендера `opened`, `on_approval`, `awarded`, `handed_over`, `delivery`, `closed`, `failed`, `rework` объявлены (`models/tender.py:24-35`), но ни один код в них не переводит. Нет вскрытия, сравнения, модели выбора, предмета signoff, передачи, приёмки. У `Tender` нет `rate_date`, у `OfferExtra` — `amount_kzt` (мастер-план §3.2 их называет). Файлы КП (`tender.offer`) до вскрытия видит только суперпользователь (`file_owners.py:93`). Итог в портале всегда `awaiting` (`portal/serializers.py:52`). В `bpp` нет ни `Invoice.pay_after_receipt`, ни создания документов для tender, ни понятия «приёмка».

**Зависимость от этапа 4.** Этап 4 (письма, OTP, beat) не сделан. Спека построена так, чтобы этап 5 от него **не зависел**: вскрытие — ручное действие закупщика после срока (S5-02), закрытие приёма по сроку из beat (T4.3) потом зовёт ту же функцию; письма итога — событие, которое outbox этапа 4 подхватит (S5-17); до него поставщик видит итог в портале (TND-035).

---

## 1. Сквозные правила

**Деньги.** Все суммы — `Decimal`, округление до 0,01 `ROUND_HALF_UP` на каждой строке, затем суммирование (как CALC-* БЗО); никакого `float` ни на сервере, ни на фронте (копейки `BigInt`, `features/bpp/budgets/cents.ts`).

**Курс (T-12).** Курс валюты предложения — НБРК **последнего дня не позже даты вскрытия** (`Tender.rate_date` = местная дата `opened_at`). Функция — `refdata.interface.exchange_rate_on_or_before(currency, on_date) -> RateOut | None` (`{rate, on_date}`, KZT → `1` на ту же дату). Нет курса ни на одну дату ≤ `rate_date` — сравнение показывает «нет курса» у этого поставщика, его суммы в KZT `null`, а выбор с ним не уходит на утверждение (422 `E-TND-10`).

**НДС [умолч., S5-03].** `Offer.with_vat=True` — цены поставщика **включают** НДС по `vat_rate`. `with_vat=False` и `vat_rate` задан — цены без НДС, полная стоимость = цена × (1 + ставка/100). `with_vat=False` и ставки нет — поставщик не плательщик НДС, полная стоимость = цена. Сравнение идёт по полной стоимости с НДС; ставка и признак показываются у поставщика.

**Полная стоимость и общий набор (TND-020, TND-021).**
- Строка позиции поставщика: `amount = price × qty` (количество — предложенное, ≤ запрошенного), в валюте предложения; `amount_kzt = gross(amount) × rate`.
- Доставка и СМР (`OfferExtra`) берутся **целиком**: «включена в цену» — 0 с пометкой; сумма — `gross(amount) × rate`. Делить пропорционально нельзя.
- **Общий набор** — позиции, которые предложили **все** участвующие поставщики (участвует, цена есть). Итог «по общему набору» = Σ строк общего набора + доставка + СМР. Итог «полный» = Σ всех своих строк + доставка + СМР. Покрытие — «N из M позиций».
- Плановая стоимость позиции = `plan_price × qty` заявки (KZT, с НДС, как у ЗЗ); доставки и СМР — `delivery_plan_amount`/`works_plan_amount`. Экономия = план − предложение (по строке, по поставщику, по выбору); отрицательная — удорожание.
- Предложение с `valid_until` раньше сегодняшней даты — предупреждение «срок действия истёк», выбор не блокирует (Q-T12, T-12 §3.5).
- Количество меньше запрошенного — строка сравнивается по цене за единицу, а сумма считается от предложенного количества; в сравнении видна пометка «N из M ед.».

**Видимость.** Предложения, их цены, файлы КП и сравнение — только после вскрытия (`Tender.opened_at` не пуст). До вскрытия `comparison`, `award`, `export` и файлы КП — **409 `E-TND-07` «Предложения откроются после вскрытия» даже ФД и суперпользователю** (кроме панели файлов, где суперпользователь сохраняет обход платформы). После вскрытия — всем, кто видит тендер (`tenders.can_view`: автор; держатели `tender.tenders.all` — ФД, ТД с `tender-quality`, `tender-viewer`). Назначенный лично проверяющий качества получает роль `tender-quality` (у неё `tenders.all` view) — отдельного правила не нужно.

**Статусы тендера (переходы этапа 5).**

```
intake ──open──▶ opened ──award/submit──▶ on_approval ──approved──▶ awarded ──handover──▶ handed_over ──первая приёмка/оплата до отгрузки──▶ delivery ──всё получено и счета закрыты──▶ closed
   │                │                          │ rework/reject
   │                │                          ▼
   │                │                       rework ──award/submit──▶ on_approval
   └─open без предложений──▶ failed        opened|rework ──cancel──▶ cancelled
```
`failed` и `cancelled` возвращают заявку в «Утверждена» (`release_request`, как отмена этапа 2). Отмена после `awarded` — нельзя (409): документы БЗО уже на подходе; отказ от поставки — средствами БЗО (отклонение/отмена документа).

**Коды ошибок этапа.** `E-TND-07` предложения до вскрытия · `E-TND-10` нет курса · `E-TND-11` дефицит бюджета статьи · `E-TND-12` нужен комментарий выбора · `E-TND-13` приёмка сверх выбранного · `E-TND-14` нет реквизитов для карточки контрагента · прочие — штатные (`E-STS-01` статус, `E-CON-01` версия, `E-VAL-01` поля).

**Журнал.** Каждое действие этапа — `audit.record(tender, …)`: `opened`, `failed`, `award_saved`, `award_submitted`, `award_approved`, `award_returned`, `handover`, `receipt_added`, `receipt_cancelled`, `closed`.

---

## 2. Модель данных

Миграция **`tender/0006_award_delivery`** (expand; на стенде и в бою — `migrate_companies`):

| Модель / поле | Состав |
|---|---|
| `Tender` + `signoff.Approvable` | колонка `approval_state` (примесь), `SIGNOFF_SUBJECT_TYPE = "tender.award"`; `rate_date` (date, null); `award_comment` (text); `status_comment` (text — комментарий возврата с утверждения); версия выбора — `Tender.version` |
| `Award` (новая) | `tender` FK CASCADE, `offer` FK PROTECT (отправленная версия, зафиксированная вскрытием), `line` FK `OfferLine` null **XOR** `extra` FK `OfferExtra` null (`CheckConstraint`), `part_id` UUID (часть заявки — какая ЗЗ), `qty` Decimal(15,3) (строка — ≤ предложенного; доставка/СМР — 1), `amount` (валюта предложения, с НДС), `amount_kzt`, `plan_amount_kzt`, `is_cheapest` (bool, на момент выбора); уникальность (`tender`, `line`) и (`tender`, `extra`) |
| `Handover` (новая) | результат передачи: `tender`, `invitation`, `part_id`, `bpp_document_type` (`agreement`/`invoice`), `bpp_document_id`, `bpp_number`, `created_at`; уникальность (`tender`, `invitation`, `part_id`) — идемпотентность |
| `Receipt` (новая) | приёмка: `tender`, `invitation`, `received_at` (date), `kind` (`goods`/`works`), `comment`, `originals_at` (date, null), `originals_to` (text), `cancelled_at`/`cancelled_by`/`cancel_comment` (ошибочную приёмку отменяют, не удаляют) |
| `ReceiptLine` (новая) | `receipt` FK CASCADE, `award` FK PROTECT, `qty` > 0 |

Модели снимка предложения не нужно: вскрытие фиксирует **ссылку** на отправленную версию (`Offer.status=submitted`), а портал после вскрытия правку не принимает (статус ≠ `intake` → 409 `E-TND-05`, уже так).

**Файлы.** Владелец `tender.receipt` (`file_owners.py`, `model=Receipt`), типы в `public` — миграция **`files/0008_tender_receipt_types`**: `waybill`, `act`, `vat_invoice` (те же коды, что у счёта БЗО — сканы уходят туда без перекодировки), `tender_photo` (JPG/PNG/HEIC до 20 МБ). Видят сканы — автор, ФД, БУХ, ГД (T-17): автор и держатели `tender.receipts` view, **кроме** `tender-viewer` ОД и проверяющего качества — для них `can_view_type` скрывает закрывающие типы, фото видно. Менять — автор, пока приёмка не отменена.

**БЗО (зона B, `bpp(B):`)** — миграция **`bpp/0022_invoice_receipt`**: `Invoice.pay_after_receipt` (bool), `Invoice.postpay_days` (smallint, null), `Invoice.received_at` (date, null), `Invoice.originals_at` (date, null), `Invoice.originals_to` (text), `Invoice.source_tender` (char 32, номер ТН — для показа «из тендера»).

---

## 3. Задачи

### T5.4 — зона A: курс «не позже даты» и контрагент из потенциального поставщика (первой)

- `refdata.interface.exchange_rate_on_or_before(currency: str, on_date: date) -> RateOut | None` — `ExchangeRate` с `on_date <= on_date` по убыванию, первая; KZT → `RateOut(rate=1, on_date=on_date)`. `exchange_rate` (строго на дату) не меняется. Тесты: выходной → пятничный курс; курса нет вовсе → `None`; ручной курс приоритетнее загруженного на ту же дату (как сейчас).
- `bpp.interface.create_counterparty_from_prospect(data: ProspectIn, *, actor: TenderActor) -> CounterpartyRef` (`apps/bpp/schemas/tender.py`):
  - `ProspectIn`: `name`, `country_code`, `reg_number`, `is_vat_payer`, `contact_name`, `phone`, `email`, `kind` (`legal`/`ip`/`nonresident`, [умолч.] — по длине и стране: KZ 12 цифр → `legal`, иначе `nonresident`).
  - Поиск по (`country_code`, нормализованный `reg_number`, `uq_bpp_counterparty_reg`): найден — `CounterpartyRef(id, created=False, status)`; заблокирован/архив — `E-CTR-01` (наружу — 422 `E-TND-14` с причиной). Не найден — `counterparties.service.create(...)` от имени закупщика, право — узел `bpp.counterparties` create (у СН и ПМ есть, `access/0014`); нет права — 403. Метки «Проверенный» не ставит (D-20), подтверждение E-CTR-05 — штатно при отправке документа.
  - Пустой рег. номер — 422 `E-TND-14` «Укажите БИН/ИИН или рег. номер поставщика»: дозаполняет поставщик в портале или закупщик в карточке потенциального поставщика.
- DoD: тесты `apps/refdata` и `apps/bpp/tests/test_tender_counterparty.py` зелёные; повторный вызов — та же карточка, не дубль.

### T5.1 — вскрытие и сравнение

**Вскрытие** — `services/comparison/opening.py::open_tender(tender_id, *, ctx | None) -> dict`:
- Только `intake`, только после `deadline_at` по времени сервера, под `select_for_update` тендера; кнопка — у автора (`allowed_actions` + `"open"` после срока). Досрочно [умолч., S5-02] — если каждое живое приглашение уже «Предложение подано» или «Отказ»: иначе тому, кто ещё заполняет, закрыли бы приём раньше обещанного.
- Ставит `opened_at=now`, `rate_date=localdate`, статус `opened`; приглашения без отправленной версии → `expired`; черновики предложений остаются как есть (их не видно).
- Ни одного отправленного предложения → статус `failed`, `release_request`, журнал `failed` (TND «Не состоялся»).
- `ctx=None` — вызов из beat этапа 4 (T4.3) с системным актором `tender-portal`; в этапе 5 — только ручной.

**Сравнение** — `services/comparison/table.py::comparison(ctx, tender_id) -> dict` и ручка `GET tenders/<id>/comparison`:
- Ответ: `{rate_date, opened_at, suppliers: [...], items: [...], extras: [...], totals: {...}, warnings: [...]}`.
- `suppliers[]`: `invitation_id`, `name`, `counterparty_id|prospect_id`, `offer_id`, `offer_number`, `currency_code`, `rate`, `rate_on`, `with_vat`, `vat_rate`, `valid_until`, `valid_expired`, `payment_scheme` (шаблон поставщика), `coverage {offered, total}`, `total_common_kzt`, `total_full_kzt`, `saving_common_kzt`, `files [{id, name, size}]`, `requisites` (только чтение), `extra_terms`.
- `items[]`: `item_id`, `line_no`, `name`, `specs`, `uom`, `qty`, `plan_price`, `plan_amount`, `in_common_set`, `offers {invitation_id: {line_id, participates, price, qty, amount, amount_kzt, unit_price_kzt, delivery_date, is_analog, analog_note, comment}}`, `cheapest_invitation_id` (по `unit_price_kzt`).
- `extras[]`: `kind`, `plan_amount`, `offers {invitation_id: {extra_id, included_in_price, amount, amount_kzt, note}}`, `cheapest_invitation_id`.
- Отозванные предложения и отказавшиеся в таблицу не входят; отказ виден строкой «Отказались: N» с причинами.
- Файл КП: `GET tenders/<id>/offers/<offer_id>/files/<doc_id>` → 302 на `files.download_link` (журнал выдачи, как у ТЗ); `file_owners._offer_can_view` открывается после вскрытия для тех, кто видит тендер.

**Экспорт** — `GET tenders/<id>/comparison/export` (xlsx) — та же таблица: лист «Сравнение» (позиции × поставщики, строки доставки и СМР, итоги, экономия), лист «Поставщики» (условия). Санитайзер формул — общий **`htqweb/xlsx_safe.py::safe_cell(value)`**: строке, начинающейся с `= + - @ \t \r`, — префикс `'` и тип «текст» (T-27); в той же задаче им начинает пользоваться `bpp/services/core/export.py::_cell` (там сейчас только `=`), тест на шесть префиксов у обоих.

DoD: `comparison`/`export` до вскрытия — 409 `E-TND-07` и для ФД; частичное предложение — итог по общему набору, покрытие «N из M»; доставка «включена в цену» — 0 и пометка; поставщик в USD при курсе на субботу — пятничный курс; нет курса — `null` и предупреждение; формулы в xlsx нейтрализованы; сторож: открытие без предложений → `failed`, заявка «Утверждена»; приглашения без версии → `expired`.

### T5.2 — выбор и утверждение `tender.award`

**Выбор** — `PUT tenders/<id>/award` `{version, comment, lines: [{line_id, qty}], extras: [extra_id]}` (`services/award/selection.py`):
- Только `opened` и `rework`, только автор. Позиции — строки отправленных версий этого тендера; на одну позицию — **один** поставщик (S5-05) [умолч.; дробление позиции между поставщиками — этап 6]; `qty` ≤ предложенного.
- Доставка и СМР выбираются строкой `OfferExtra` поставщика, который выиграл **хотя бы одну позицию** той же части (S5-06): чужую доставку к чужому товару не возят. «Включена в цену» выбирается автоматически вместе с позициями поставщика — сумма 0, часть ЗЗ закроется при передаче (§3.5 мастер-плана).
- `is_cheapest` — для позиции: `unit_price_kzt` выбранного ≤ минимального среди предложивших; для доставки/СМР — сумма ≤ минимальной. Есть хоть одна не самая дешёвая — **один общий комментарий ≥ 10 символов** (`award_comment`), иначе 422 `E-TND-12` с перечнем таких строк (S5-07).
- Ответ — тот же, что `GET tenders/<id>/award`: строки выбора, итоги по поставщикам и частям в KZT, экономия, `budget_check` (ниже), `allowed_actions`.

**Отправка на утверждение** — `POST tenders/<id>/award/submit` `{version}`:
- Выбор не пуст; по каждой части с выбором — проверка курса (`E-TND-10`).
- **Бюджет (T-13):** по каждой статье: `Σ выбранного KZT по частям статьи − Σ плана этих частей ≤ budget_available(project, article).available`. Иначе 422 `E-TND-11`, `details.deficits = [{article_id, article_code, over, available}]`; сравнение показывает дефицит до отправки.
- Старт `signoff.start_process(subject_type="tender.award", subject_id=tender.id, initiator_id=author)`; статус `on_approval`; нет маршрута — 409 «Маршрут не настроен» (как у кадров).

**Предмет signoff** — `apps/tender/approval_hooks.py`, регистрация из `ready()`:
- `register_subject("tender.award", label="Выбор поставщиков", model=Tender, approvers=…, approver_fields=…, on_started, on_approved, on_rejected, on_rework, on_cancelled, describe, summary)`.
- `approver_fields()` → `[{"key": "quality_reviewer", "label": "Проверяющий качество тендера"}]`; `approvers(id, "quality_reviewer")` → `[quality_reviewer_user_id]`, если задан и у него `tender.award.quality` edit; иначе держатели должности «Технический директор» (`hr.positions_by_title` → `resolve_position_users`, своя компания, затем вышестоящая — как `bpp_configure_routes`). Пусто — `RouteUnusable` с понятной причиной (signoff так и сообщает).
- Маршрут — `manage.py tender_configure_route --company <slug> [--fd ID] [--dry-run]`: этап 1 «Проверка качества» (`approver_kind="subject"`, `approver_key="quality_reviewer"`), этап 2 «Утверждение ФД» (должность «Финансовый директор», как у `bpp_configure_routes`); флаги `reject_comment_min=10`, `forbid_self_approval=True` (автор не утверждает свой выбор). Этапа ГД нет (T-11). Идемпотентна.
- `on_started` → `on_approval`; `on_approved` → `awarded`, приглашения победителей `awarded`, прочих участвовавших — `not_awarded`, событие `award_approved` для писем (S5-17); `on_rework`/`on_rejected` → `rework`, комментарий решения — в `Tender.status_comment`; `on_cancelled` → `opened`.
- `summary(id)` — поставщики, суммы KZT, экономия, дефицит — для «Ждёт меня» и решения из холдинга.
- Проверяющий видит сравнение, аналоги, файлы КП (правила §1) и может вернуть с комментарием — это `rework` движка.

**Смена проверяющего** (хвост этапов 0–2): действие `reviewer` в `allowed_actions`, пока статус в `REVIEWER_EDITABLE` и процесса нет; на идущем процессе — нельзя (этап уже назначен) [умолч., S5-08].

DoD: не самый дешёвый без комментария — 422 `E-TND-12`; дефицит — 422 `E-TND-11` с суммами; ТД по должности (без назначенного) и назначенный проверяющий получают задачу; возврат → `rework`, повторная отправка — новый раунд процесса; утверждение ФД → `awarded`, статусы приглашений; `apps/signoff` и сторож `test_gate` зелёные.

### T5.3 [B] — пакет B-2 в `bpp.interface` (зона Руслана, коммиты `bpp(B):`)

Схемы — `apps/bpp/schemas/tender.py`, функции — `apps/bpp/services/requests/tender_documents.py` по образцу `services/selection/documents.py` (B5.1):

```python
class HandoverLineIn(BaseModel):     # одна строка документа
    bpp_request_item_id: str; qty: Decimal; amount: Decimal       # amount — с НДС, в валюте документа
class HandoverDocIn(BaseModel):      # поставщик × ЗЗ
    key: str                          # "<invitation_id>:<part_id>" — ключ идемпотентности
    bpp_request_id: str; counterparty_id: str
    currency_code: str; with_vat: bool; vat_rate: Decimal | None
    kind: Literal["agreement", "invoice"]
    payment: Literal["prepay", "advance", "postpay"]; postpay_days: int | None
    lines: list[HandoverLineIn]
    offer_media_file_ids: list[str]   # КП победителя — в документ файлом (adopt)
class TenderHandover(BaseModel):
    actor: TenderActor; tender_number: str; docs: list[HandoverDocIn]
class DocumentRef(BaseModel):
    key: str; doc_type: Literal["agreement", "invoice"]; doc_id: str; number: str; status: str

create_documents_from_tender(data: TenderHandover) -> list[DocumentRef]
documents_status(request_ids: list[str]) -> list[DocumentStatusOut]
set_acceptance(invoice_ids: list[str], *, received_at: date, originals_at: date | None,
               originals_to: str, actor: TenderActor) -> None
attach_closing_docs(invoice_id: str, files: list[ClosingFileIn], *, actor: TenderActor) -> list[str]
register_document_listener(fn: Callable[[DocumentStatusOut], None]) -> None
```

- **`create_documents_from_tender`** — в одной транзакции; черновики через `new_agreement`/`new_invoice` от имени закупщика (`TenderActor`, T-20), затем контрагент, валюта, НДС, `source_tender`; идемпотентно по `key` (повтор отдаёт уже созданный документ — поиск по `source_tender` + строкам). Проверки ЗЗ: `source="tender"`, статус «Утверждена», позиции принадлежат ЗЗ, `qty`/`amount` в пределах остатка (BR-042) — иначе `DomainError` как есть. Права — **не** проверяются через план (позиции tender в Плане скрыты, T-07): это единственный путь документов на такие ЗЗ, право закупщика — его авторство ЗЗ.
  - `kind="invoice"`: основание «без договора»; `prepay` → `is_advance=True`; `advance` → `is_advance=True` (один счёт с частичными отметками БУХ, T-15); `postpay` → `pay_after_receipt=True`, `postpay_days`.
  - `kind="agreement"`: договор-черновик; счета по нему закупщик создаёт в БЗО штатно (`create_from_agreement` — путь через договор не заперт T-07, признаки оплаты по схеме — подсказка в карточке договора «из тендера ТН-…, схема …»).
  - КП победителя — `files.adopt_media_file` в приложения документа (`invoice` у счёта не заменяет обязательный файл счёта поставщика: его прикладывает закупщик при получении счёта).
- **`documents_status(request_ids)`** → `[{request_id, doc_type, doc_id, number, status, amount, currency_code, counterparty_id, paid_amount (Σ живых отметок БУХ), is_advance, pay_after_receipt, due_date, docs_required, docs_requested_at, received_at, replaced_by {doc_type, doc_id, number} | None, invoices: [...] (для договора — его счета)}]`.
- **`set_acceptance`** — пишет `received_at`/`originals_at`/`originals_to` на счета; у `pay_after_receipt` — `due_date = received_at + postpay_days` (календарных, [умолч., S5-12]) и `planned_pay_date`, если её нет. Карточка счёта и очередь БУХ показывают «Товар принят <дата>, оригиналы переданы <дата, кому>»; счёт `pay_after_receipt` без `received_at` — в очереди БУХ с пометкой «ждёт приёмки» (Q-T05: отметка, не запрет).
- **`attach_closing_docs`** — держит D-13 сам: счёт `awaiting_docs`, тип файла в `docs_required`, иначе 409; прикладывает через `files.adopt_media_file` (байты уже в хранилище tender), журнал счёта; повтор того же файла не дублирует.
- **`register_document_listener`** — зовётся в транзакции смены статуса счёта и договора (в т.ч. `request_docs` → `awaiting_docs`, `closed`, `replaced`), как `register_request_listener` B-1.
- DoD: тесты `apps/bpp/tests/test_tender_documents.py`: два вызова — одни документы; автор — закупщик; `postpay` → `pay_after_receipt`, срок от приёмки; закрывающие вне `awaiting_docs` или незапрошенного типа — 409; заменённый альтернативой документ — `replaced_by`; `apps/bpp` зелёный целиком (зона B).

### T5.5 — передача и поставка

**Передача** — `POST tenders/<id>/handover` `{version}` (`services/award/handover.py`), статус `awarded`, автор:
1. Контрагенты: у приглашения контрагента — он; у потенциального — `create_counterparty_from_prospect(offer.requisites)`, `prospect.counterparty_id` записывается.
2. Порог (T-14, S5-10): по поставщику Σ выбранного KZT (товар + доставка + СМР) **> `contract_threshold(сегодня)`** → `kind="agreement"` по каждой его части; иначе `kind="invoice"`. Граница — как BR-040 (строго больше).
3. Документы по поставщику × части: строки — `bpp_request_item_id` позиций (доставка/СМР — единственная позиция своей ЗЗ), суммы — выбранные (валюта и НДС поставщика), схема — **схема поставщика** из его предложения (S5-11), если её нет — схема тендера.
4. `Handover` по каждому документу; повтор ручки — те же документы (идемпотентно и в tender, и в bpp).
5. Части без единого выбора (доставка «включена в цену», невыбранные части) → `cancel_requests_from_tender` (закрытие остатка, резерв освобождается). Невыбранные позиции частично выбранной части остаются в ЗЗ открытыми; у закупщика действие «Закрыть остаток» (`cancel_requests_from_tender` той ЗЗ после согласования её документов) — [умолч., S5-13]; «Новый тендер на остаток» — этап 6.
6. Статус `handed_over`, заявка `handed_over`, журнал.

**Стадии поставки** — `GET tenders/<id>/delivery` (`services/delivery/stages.py`), по поставщику; данные — `documents_status` + приёмки tender:

| Стадия | Условие |
|---|---|
| Ожидает документов | есть документ, ни один счёт не «К оплате» и далее, договор не «Действует» |
| Ожидает оплаты для отгрузки | оплачено по отметкам БУХ < доли этапов `before_shipment` схемы × сумма поставщика |
| В доставке | оплачено ≥ доли «до отгрузки» (для схемы 3 доля 0 — сразу после согласования документа), приёмок нет |
| Получено частично / Получено | Σ `ReceiptLine.qty` по выбору < / = выбранного по всем позициям; СМР — «Работы приняты» |
| Ожидает окончательной оплаты | всё получено, оплачено < суммы |
| Закрыто | всё получено, все счета поставщика «Закрыт» |
| Заменён альтернативой | документ БЗО `replaced` — ссылка на новый (`replaced_by`), дальше стадии — по новому документу (T-18) |

Статус тендера: `handed_over` → `delivery` при первой стадии «В доставке» или приёмке; → `closed`, когда все поставщики «Закрыто» (тогда заявка `closed`).

**Приёмка** — `POST tenders/<id>/receipts` `{invitation_id, received_at, kind, lines: [{award_id, qty}], originals_at?, originals_to?, comment}` (узел `tender.receipts` create, автор тендера):
- `received_at` ≤ сегодня; `Σ qty` по выбору ≤ выбранного — иначе 422 `E-TND-13`; СМР — `kind="works"`, строка выбора СМР, `qty=1`.
- Сканы и фото — панель `/api/files/v1` владельца `tender.receipt` после создания приёмки (как у документов БЗО); «оригиналы переданы» — `PATCH tenders/<id>/receipts/<rid>` `{originals_at, originals_to}`.
- После приёмки — `set_acceptance` для счетов этого поставщика по частям приёмки (дата — последняя приёмка; полная/частичная — признак в tender).
- Отмена ошибочной — `POST …/receipts/<rid>/cancel` `{comment ≥ 10}`; на счёте БЗО дата приёмки пересчитывается по оставшимся.

**Закрывающие на счёт (T-16).** Слушатель `register_document_listener` в tender: счёт тендера перешёл в `awaiting_docs` → для запрошенных типов (`docs_required`) прикладываются сканы приёмок этого поставщика и части (`attach_closing_docs`, D-13 — в БЗО); то же сразу после загрузки скана, если счёт уже `awaiting_docs`. «Документы предоставлены» нажимает закупщик в БЗО штатно. Слушатель же переводит тендер в `closed`, когда закрылся последний счёт.

**Портал (TND-035).** `portal/serializers._result(tender)`: `awaiting` (до `awarded`), `awarded` с перечнем выбранных позиций поставщика, `not_awarded`, `cancelled`, `failed`. Сторож белого списка (`test_portal_whitelist.py`) — без сумм других поставщиков.

DoD: передача на трёх схемах создаёт счёт (аванс, частичные отметки, постоплата) или договоры по порогу; повтор не дублирует; потенциальный поставщик получает карточку контрагента без дубля; стадии на схемах 1–3 (`pinned_clock`, отметки БУХ через сервис БЗО); приёмка ставит срок схемы 3; скан уходит на счёт только в `awaiting_docs` и только запрошенного типа; тендер «Закрыт» после закрытия последнего счёта.

### T5.6 — метрики, фронт, сквозные сценарии

**Метрики** (`apps/tender/metrics.py`, тенантная — по компании; дашборд — новый `htqweb-tender.json` или раздел `htqweb-bpp`):
- `htqweb_tender_tenders{status}` — тендеры по статусам;
- `htqweb_tender_award_approval_stale` — выборы на утверждении дольше 3 рабочих дней (`refdata.working_days_between`);
- `htqweb_tender_delivery_overdue` — поставщики «В доставке» дольше срока поставки из предложения (максимальная `delivery_date` строк + 0 дней).
Правило алертинга — только на `award_approval_stale > 0` в `channel=business`; `test_metrics_are_observed` зелёный.

**Фронт** (`features/tender/tenders/`, все тексты — `t('tender.…', 'фолбэк')`):
- карточка тендера: кнопка «Вскрыть» (после срока), вкладки «Сравнение» (после вскрытия), «Выбор», «Оплата и доставка» (после передачи);
- `ComparisonTable` — общий компонент: из `features/bpp/alternatives/AlternativesBlock.tsx` вынести таблицу в `features/bpp/core/ComparisonGrid.tsx` (колонки — поставщики, строки — позиции/доставка/СМР/итоги) и использовать в обоих местах, чтобы не держать две таблицы сравнения; подсветка самого дешёвого, экономия, пометки «аналог», «N из M ед.», «срок истёк», «нет курса»; экспорт — кнопка на `comparison/export`;
- выбор: переключатель поставщика в строке, количество, автоматический выбор «включено в цену», поле комментария (обязательное, если есть не самые дешёвые — сервер скажет `E-TND-12` с перечнем), блок «Бюджет» с дефицитом по статьям, кнопки «Сохранить выбор» и «На утверждение»;
- процесс согласования — блок «Ход согласования» (`SubjectProcesses` из signoff), «Ждёт меня» — через `summary`;
- «Оплата и доставка»: по поставщику — документы БЗО ссылками, стадия, оплачено/сумма, приёмки с файлами (общая панель файлов), «Отметить получение», «Оригиналы переданы», «Закрыть остаток»;
- портал: итог TND-035 (`result`) вместо постоянного «Ожидается решение».

**Сквозные проверки:**
- pytest `apps/tender/tests/test_stage5_e2e.py` — сценарий ТЗ этапа 5: заявка (две статьи + доставка + СМР) → тендер → 2 поставщика по разным позициям, один с доставкой и СМР → вскрытие → выбор с комментарием → ТД → ФД → передача: договор (поставщик выше порога) + счёт без договора (ниже) → аванс 30 % отметкой БУХ → «В доставке» → приёмка с накладной → БУХ запрашивает закрывающие → скан на счёте → оплата остатка → закрыто;
- Playwright `frontend/tests/e2e/41_tender_award.spec.ts` — то же через UI до передачи и приёмки (отметки БУХ — API БЗО).

### T5.7 — ранбук и закрытие модуля в пилот

- Ранбук `docs/deploy/tender-rollout-runbook.md` по образцу `bpp-rollout-runbook.md`: репетиция на дампе → `migrate_shared` (`files/0006–0008`, `access/0026–0027`) → `migrate_companies` (`bpp/0021–0022`, `tender/0001–0006`) → `tender_assign_roles --company hi-tech-group` → `tender_configure_route --company hi-tech-group` → ClamAV (обязателен для портала) → ящик `tender@` (этап 4) → `manage.py service tender --on` и `CompanyModule` только у холдинга. Откат — выключить сервис, данные не трогать.
- Итоговое `harness-review` всего модуля, регрессия (сторожа CI + `apps/tender`, `apps/bpp`, `apps/signoff`, `apps/files`, `apps/refdata`), `nginx -t` (хвост T3.1). **Пуш и PR `tender` → `sanzhar` — только после этапа 5 и по команде пользователя** (правило 20.10).

---

## 4. Порядок и раскладка

Порядок: **T5.4 → T5.1 → T5.2 → T5.3 [B] → T5.5 → T5.6 → T5.7**. T5.3 можно вести параллельно с T5.1–T5.2 (контракт §3 T5.3 зафиксирован здесь): файлы не пересекаются, tender зовёт B-2 только в T5.5.

| Задача | Файлы |
|---|---|
| T5.4 | `apps/refdata/interface.py`, `refdata/services/lookup.py` (+тест); `apps/bpp/interface.py`, `bpp/schemas/tender.py`, `bpp/services/requests/tender_counterparty.py` (+тест) |
| T5.1 | `tender/migrations/0006_award_delivery.py` (общая на этап), `models/tender.py`, `services/comparison/{__init__,opening,table,money,export}.py`, `htqweb/xlsx_safe.py` (+тест), `bpp/services/core/export.py`, `file_owners.py` (`_offer_can_view`), ручки в `urls_tenders.py`/`views_tenders.py`, `tests/test_opening.py`, `tests/test_comparison.py` |
| T5.2 | `models/award.py`, `services/award/{__init__,selection,submit}.py`, `approval_hooks.py`, `apps.py` (`ready`), `management/commands/tender_configure_route.py`, `tests/test_award.py`, `tests/test_award_signoff.py` |
| T5.3 [B] | `bpp/migrations/0022_invoice_receipt.py`, `bpp/models/invoices.py`, `bpp/services/requests/tender_documents.py`, `bpp/services/invoices/{read,invoices}.py` (показ приёмки, «ждёт приёмки»), `bpp/interface.py`, `bpp/schemas/tender.py`, `bpp/tests/test_tender_documents.py`, фронт карточки счёта БЗО (строка «Товар принят…») |
| T5.5 | `models/delivery.py` (`Handover`, `Receipt`, `ReceiptLine`), `services/award/handover.py`, `services/delivery/{__init__,stages,receipts,closing}.py`, `file_owners.py` (`tender.receipt`), `files/migrations/0008_tender_receipt_types.py`, `portal/serializers.py` (`_result`), `tests/test_handover.py`, `tests/test_delivery.py` |
| T5.6 | `metrics.py`, `infra/logging/grafana-dashboards/htqweb-tender.json`, `alerting/rules.yml`; фронт `features/tender/tenders/{ComparisonTab,AwardTab,DeliveryTab,ReceiptDialog}.tsx`, `features/bpp/core/ComparisonGrid.tsx`, `features/tender/portal` (итог); `tests/test_stage5_e2e.py`, `frontend/tests/e2e/41_tender_award.spec.ts` |
| T5.7 | `docs/deploy/tender-rollout-runbook.md`, `API.md`, `STRUCTURE.md`, `CLAUDE.md` |

Документация (API.md, STRUCTURE.md, CLAUDE.md) обновляется в той же задаче, что и код (правило мастер-плана).

---

## 5. Проверки этапа

- pytest на `:55432`, Python 3.14, один прогон за раз; время — `pinned_clock`; файловые тесты с `transaction=True` пересевают справочник типов.
- Сторожа: `test_app_isolation` (tender зовёт bpp, refdata, signoff, hr, files, notifications только через `interface`), `test_invariants`, `test_gate` (новые ручки — `api_view(module="tender", level=…)`), `test_metrics_are_observed`, `test_portal_whitelist`, `test_periodic_tasks` (если появится расписание — нет).
- Фронт: vitest, eslint, `tsc -p tsconfig.app.json` ≤ 148.
- Каждая задача — `harness-review` по своему диффу; этап — итоговое ревью; Critical/Major — до коммита.

---

## 6. Решения этапа (S5) и вопросы

| № | Решение | Статус |
|---|---|---|
| S5-01 | Этап 5 не ждёт этапа 4: вскрытие ручное, письма итога — событие для outbox этапа 4 | умолч. (порядок этапов — пользователь) |
| S5-02 | Вскрытие — после срока; досрочно — только когда все живые приглашения подали или отказались | умолч. |
| S5-03 | `with_vat=True` — цены с НДС; `False` + ставка — без НДС, добавляем; `False` без ставки — неплательщик | умолч. (Алгазы) |
| S5-04 | Общий набор — позиции, предложенные всеми участвующими; доставка и СМР — целиком | ТЗ TND-021 |
| S5-05 | Позиция целиком у одного поставщика; дробление количества между поставщиками — этап 6 | умолч. |
| S5-06 | Доставка/СМР — только от поставщика, выигравшего позицию той же части | умолч. |
| S5-07 | Один общий комментарий выбора ≥ 10 символов, если хоть одна строка не самая дешёвая | умолч. (ТЗ TND-022 не уточняет) |
| S5-08 | Смена проверяющего — до старта процесса; на идущем процессе — нет | умолч. |
| S5-09 | Возврат и отклонение на утверждении — оба в «Возвращён на доработку»; отмена тендера после «Выбор утверждён» — нет | умолч. |
| S5-10 | Порог договора — на поставщика по тендеру, `contract_threshold(дата передачи)`, строго больше (BR-040) | T-14, Q-T03 |
| S5-11 | В документ БЗО — схема оплаты **поставщика**, нет её — схема тендера | ТЗ «Оплата и доставка» |
| S5-12 | Срок оплаты схемы 3 — `received_at + postpay_days` календарных дней | умолч. (Алгазы: банковских?) |
| S5-13 | Невыбранные позиции частично выбранной ЗЗ — открыты до «Закрыть остаток» закупщиком | умолч. |
| S5-14 | Документы по договору: счета закупщик создаёт в БЗО по договору штатно; tender считает стадии по ним | T-15, T-20 |
| S5-15 | Сканы приёмки — у tender, на счёт — при `awaiting_docs` слушателем (D-13 держит БЗО) | T-16 |
| S5-16 | Стадия «Заменён альтернативой» и дальнейшие стадии — по новому документу | T-18 |
| S5-17 | Письма итога (победителям и не выбранным) — событие `award_approved`; отправляет outbox этапа 4 | T-25 |
| S5-18 | Курс — последний ≤ даты вскрытия; нет курса — выбор с поставщиком не уходит (422) | T-12 |
| S5-19 | Предсогласования документов БЗО нет — штатные маршруты | T-19, Q-T04 |
| S5-20 | Пакет B-2 делаем сами коммитами `bpp(B):` на ревью Руслану, как B-1 | Q-T09 (как на этапе 1) |

**Вопросы к Алгазы до старта T5.2/T5.5:** S5-03 (как поставщики указывают НДС), S5-07 (комментарий на весь выбор или на строку), S5-12 (календарные или банковские дни отсрочки), Q-T02 (дефицит бюджета — только блок или ещё путь «ФД поднимает лимит» из карточки), Q-T03 (порог на поставщика — подтвердить).

**Вопрос пользователю:** делать ли этап 4 (письма, OTP, beat) до этапа 5 — спека этого не требует (S5-01), но без этапа 4 поставщик узнаёт итог только по ссылке.
