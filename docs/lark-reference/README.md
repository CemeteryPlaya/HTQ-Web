# Lark Approval — reference capture (ground truth for the HTQWeb clone)

Goal: rebuild HTQWeb's **Запросы** (requests) so it matches Lark Approval — same look, same
functions, same request flow. This folder is the reverse-engineered ground truth used to spec that
work. It is **reference data only** (no product code).

## How it was captured (Phase 0)

Read-only, from the live Lark Approval **admin console** (larksuite.com) with the tenant owner's
session, on 2026-07-14/15:

1. A separate Chrome window was launched with `--remote-debugging-port=9222` (own profile), the
   owner logged into Lark there.
2. Playwright (`connectOverCDP`) drove **only reads**: screenshots, DOM dumps, and replaying the
   admin console's own `POST /approval/admin/api/approval/queryById {id, needConvert:true}` (with
   the `x-csrftoken` cookie) for each process. No process was opened in the editor for capture, and
   nothing was published/saved/deleted — the live definitions were never mutated.
3. `queryById` succeeded for **27 of 30** processes; 3 owner-locked ("high-level"/secret) returned
   `code 10022` (no permission).

The user-facing surfaces (submit catalog, dynamic form, approval center, efficiency dashboards, data
management) are **not reachable via the browser** for this tenant (app-only); they are documented
from 13 screenshots in [../../for tasks/](../../for%20tasks/).

## Contents

- **[data-model.md](data-model.md)** — the canonical synthesis: widget vocabulary, `fieldList`/
  `amount`/`mutableGroup` formats, conditional visibility, workflow node/edge/approver model,
  `otherSettings`, and a gap table vs. the current `services/requests` backend. **Start here.**
- **[inventory.md](inventory.md)** — all 5 groups / 30 processes (name, id, status, editability).
- **[processes-overview.md](processes-overview.md)** — per-process form fields + workflow, human-readable.
- **[normalized/](normalized/)** — one clean structured JSON per process (resolved i18n, typed fields,
  workflow nodes/edges).
- **[raw/](raw/)** — untouched API responses: `configs/*.json` (27 `queryById`),
  `currency-list.json`, `groups.json`, `admin-definition-list.json`, `definition-inventory.json`.

## Screenshot ↔ surface map (from `for tasks/`)

| Screenshot | Lark surface |
|---|---|
| 1 | Отправить запрос — catalog (Рекомендовано + groups) |
| 2–4 | Dynamic submit form (conditional branches, repeatable groups, amount+currency, attachments) |
| 5 | Центр подтверждений — 3-pane approval center + detail (Сведения/Отчёт/Комментарии + action bar) |
| 6 | Диагностика эффективности — My Efficiency (trend chart) |
| 7–8 | Диагностика — Process/Task Diagnosis (KPI cards, tables) |
| 9 | Управление данными — data table + filters + export |
| 10–13 | Консоль администратора — builder (Basic Info / Form Design / Process Design / More) |

## Caveats

- 3 processes uncaptured (owner-locked). Re-capture needs their approval owner.
- Approver `approverIds` are Lark user IDs; not yet resolved to names (optional follow-up via
  `user/queryUsers`).
- `mutableGroup` "Data from Base" binds to external Lark Base tables — the reference data itself
  (table rows) lives in Base, not in these configs; cloning needs an HTQWeb reference-data mechanism.
