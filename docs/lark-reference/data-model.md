# Lark Approval — data model (ground truth)

Reverse-engineered from the live Lark Approval admin console (larksuite.com) on 2026-07-14/15
via read-only capture of the `queryById` API for 27 of the tenant's 30 processes. This is the
**canonical spec** of what an HTQWeb clone must reproduce. Raw source: [raw/configs/](raw/configs/).

> Naming: Lark stores a process as an **approval definition** (`queryById` → `data`). It has
> `form` (JSON string), `process` (JSON string), `info`, `otherSettings`, `i18nResources`.
> All user-facing text is an `@i18n@<uuid>` key resolved via `i18nResources[].texts`.

## 1. Catalog / inventory

- **5 groups** (categories), **30 processes**. See [inventory.md](inventory.md).
- Group + process names, icons (`iconUrl` from Lark iconLib), `status`, `processManager` (owner = "Берик").
- 3 processes are **owner-locked** ("high-level"/`isSecret`) → `queryById` returns `code 10022`
  (no permission): *Оплата РиУ по договору*, *Тестовый проект Договор*, *АВР / Накладная KZ*.
  Their config could not be captured.
- The submitter catalog ("Отправить запрос") also shows a **Рекомендовано** block and extra
  Workplace categories (e.g. "行政", "Предоставлены другими…") that don't appear as definition
  groups — those are Workplace-side tags, not approval groups.

## 2. Form model — `data.form` (JSON string)

Parses to `{ fields: [...], displayCondition: "<json-string>", widgetRelation: "<json-string>" }`.

### 2.1 Widget types (13 in use across the tenant)

| Lark `type` | Palette label | Notes / key props |
|---|---|---|
| `input` | Short answer | single-line text; `placeholder`, `defaultValue` |
| `textarea` | Paragraph | multi-line |
| `text` | Description | **static** display text (no input) |
| `number` | Number | `value` holds format opts |
| `amount` | Amount | **multi-currency money** — see §2.3 |
| `radioV2` | Single select | `value` = `[{text,value}]` options |
| `date` | Date | `option`, default value |
| `attachmentV2` | Attachment | file upload (max 9 / 50 MB per screenshots) |
| `serialNumber` | Serial no. | auto-generated running number |
| `formula` | Formula | computed from other widgets |
| `connect` | Link approvals | reference to another approval |
| `fieldList` | **Widget group (repeatable)** | "Копировать/Удалить/+Добавить" — see §2.2 |
| `mutableGroup` | **Data from Base (lookup)** | bound to an external Lark **Base** table — see §2.4 |

Every widget shares: `id` (`widget<ts>...`), `type`, `name` (i18n), `required`, `visible`,
`printable`, `displayCondStatus`, `displayCondition` (per-widget), `defaultValue`, `linkageConfigs`.

### 2.2 `fieldList` — repeatable widget group (THE core pattern)

Sub-widgets live in **`.value`** (array of full widget objects, arbitrarily typed incl. nested
`mutableGroup`, `amount`, `attachmentV2`). `.option` = `{inputType:"LIST", mobileDetailType:"CARD",
printType:"LIST", summarizeWidgets:[<id>]}` — `summarizeWidgets` marks which child amount is totalled
into the request summary. Example — *Счет на оплату KZ* → "Счет на оплату без договора" has **14**
sub-widgets. This is the screenshots 3–4 "Копировать / Удалить / + Добавить сведения" UI.

### 2.3 `amount` — multi-currency money

`.option` = `{ currencyRange:["USD","KZT","RUB","UZS","EUR"], keepDecimalPlaces:2,
isThousandSeparator:true, isCapital:<amount-in-words>, hideExchangeRate, hideEstimate, minValue, maxValue }`.
Submitter picks one currency from `currencyRange`; UI shows conversion + estimated amount
(screenshots 3/5/11). Full currency catalog: [raw/currency-list.json](raw/currency-list.json).

### 2.4 `mutableGroup` — "Data from Base" (external lookup) ⚠️ biggest dependency

Bound to a **Lark Base (bitable)** table via `bitableConfig = { url, appToken, tableName, tableID }`.
Its `.value` lists the fields it surfaces. This is how dependent dropdowns are populated
(Наименование администратора программы → Бюджет проекта → Номер спецификы, etc.). **Faithful
cloning requires an HTQWeb equivalent of "reference data tables"** that widgets can look up and
that support dependent/filtered selection. This does not exist in the current backend.

### 2.5 Conditional visibility — `displayCondition`

JSON string: array of `{ targetWidget:{id}, showCondition:{ conditional:"OR|AND",
conditions:[{ expressions:[{ sourceWidget:{id}, compareType:"is", standardValue }]}]}}`.
9 of 27 forms use it. Example: *Счет на оплату KZ* shows group "без договора" when
"Наличие договора" `is` the "Без договора" option, else group "по договору". `widgetRelation`
(dependent-select linkage) is **unused** (`{"groups":[]}` everywhere).

## 3. Process model — `data.process` (JSON string)

`{ nodeList:[...], lineList:[...], defaultCc, startCc, endCc, approvalCcType, allowAddCc,
positionInfo, zoom }`.

### 3.1 Node types (`nodeType`)

| # | kind | notes |
|---|---|---|
| 1 | Start / Submit | `starterAssignee`, `approverChosenRange` |
| 2 | End | terminal; may carry `defaultCc` |
| 3 | **Approval** | `approverGroup`, `approvalMethod`, `endCc` — 78 across tenant |
| 4 | Condition/branch | no name/approvers (routing) |
| 5 | Notify (CC) | "Уведомления" |
| 6 | Acknowledge | "Ознакомление", approverType 10 |
| 7 | Condition/branch | routing |
| 8 | Parallel-merge | "parallel-aggregation" |

### 3.2 Approver resolution — `approverGroup[].approverType`

`2` = specific users (`approverIds`, 65×), `10` = role/acknowledgers (7×), `8` = role/other (4×).
`approvalMethod`: `0` = any-one/single, `1` = all, `2` = sequential/notify.
Nodes also carry `defaultCc`, `endCc`/`endCcType`, `allowRollback`/`rollbackLimit`,
`allowAddApprover`, `allowDelivery` (transfer), `emptyAutoPass`, `signatureConfig`.

### 3.3 Edges — `lineList`

`{ srcId, dstId, priority, conditionGroupList:[], isDefault }`. `conditionGroupList` non-empty =
**conditional routing** (6 edges across tenant); otherwise linear. Example *Счет на оплату KZ*:
strictly linear Submit → 6 approval nodes → End (screenshot 12).

## 4. Advanced settings — `data.otherSettings` ("More" tab, screenshot 13)

All 27 processes carry the same 20 keys: `allowBatchOperate`, `allowInsteadCreate` (delegate
submission), `allowReApprove`, `modifyInterval` / `revertInterval` (revoke/modify windows, screenshot 13),
`rejectOption`, `revertOption` (return), `rollbackOption`, `secondApprovalOption` (approver
deduplication), `removeRepeatOption`, `quickApprovalOption`, `allowCustomPrint`(+`Type`),
`customTitle`, `customSummaryWidgets`, `instanceShareOption`, `disableShareToNonStakeholders`,
`enableOpAuth`, `excludeEfficiencyOption`, `supportBatchRead`.

## 5. Mapping to the current HTQWeb `requests` backend + gaps

The `services/requests` backend is already a Lark-style engine (`form_schema.py`,
`workflow_schema.py`, `request_runtime`, `condition_eval`, stats). Coverage vs. Lark:

| Lark feature | HTQWeb today | Gap |
|---|---|---|
| text/number/money/date/dropdown/file/formula | ✅ text/number/money/date/dropdown/file/formula | rename/align |
| `radioV2` single-select | ✅ dropdown | ok |
| `amount` **multi-currency** + conversion + in-words | ⚠️ `money` single currency | **extend** |
| `fieldList` **repeatable group** w/ nested widgets | ⚠️ only flat `table` (columns) | **new widget** |
| `mutableGroup` **Data from Base** lookup | ❌ none | **new: reference data source** |
| `serialNumber`, `text`(static), `textarea`, `connect` | ❌ / partial | add widgets |
| `displayCondition` conditional visibility | ⚠️ workflow `condition` only | **form-level visibility** |
| workflow start/approval/condition/notify/end | ✅ same node kinds | add CC-per-node, acknowledge, parallel-merge |
| CC per node, `defaultCc`/`endCc`, watchers | ⚠️ watchers exist | wire CC into nodes |
| approverType role/manager (8/10), method all/seq | ⚠️ any/all modes | add sequential + role resolution |
| `otherSettings` (revoke/modify windows, dedup…) | ❌ mostly | add settings surface |

Frontend today is a minimal Inbox/Sent list — the 5 Lark surfaces (catalog, dynamic form,
approval center, efficiency dashboards, data management) plus the admin builder are effectively
unbuilt. See screenshots in [../../for tasks/](../../for%20tasks/).
