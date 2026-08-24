# Contracts business rules

This page records the implemented domain rules that matter when changing Contracts or integrating with it. It is not a substitute for the validation and authorization implemented in the backend services.

## Budget context

- A budget is divided into budget lines, each of which represents one program.
- Agreements, non-contract invoices, and accountable-funds requests are associated with the appropriate budget context.
- The budget detail view brings together agreements, invoices, and accountable-funds requests so users can understand the financial commitments against that budget.
- A record only affects the remaining budget amount when its own business status is committing. The UI deliberately identifies records that are currently outside the remaining balance; clients must not infer commitment from a label alone.

The authoritative calculation is `backend/apps/contracts/services/budget_calc.py`. Change that service and its tests together whenever a status, amount, or linked record starts or stops affecting the budget.

## Approval is separate from the record’s lifecycle

Approval state and a record’s own status answer different questions:

| Field | Meaning |
| --- | --- |
| `approval_state` | Whether the current approval round is draft, pending, approved, rejected, or returned for rework. |
| `status` | The business lifecycle of the specific record: for example draft, under review, awaiting accounting, paid, closed, or cancelled. Values vary by record type. |

While an approval-capable record is pending, approved, or rejected, it is locked for editing. A draft or a record returned for rework can be edited. A completed or rejected approval process must be explicitly returned for rework before the underlying record can be changed.

## Contracts-specific approval effects

Contracts registers its approval-capable subject types with Signoff. When Signoff starts, approves, rejects, returns, or cancels a process, it invokes Contracts callbacks in the same transaction. For the principal financial records, the callbacks move the business status as follows:

| Record | On submission | On approval | On rejection, rework, or cancellation |
| --- | --- | --- | --- |
| Agreement | `on_review` | `approved` | `draft` |
| Invoice without agreement | `on_review` | `approved` | `draft` |
| Advance payment | `on_review` | `awaiting_accounting` | `draft` |
| Contract payment | `on_review` | `awaiting_accounting` | `draft` |
| Accountable-funds request | `on_review` | `awaiting_accounting` | `draft` |
| Completion act | `on_review` | `awaiting_accounting` | `draft` |

Budgets and counterparties use approval state without an additional approval-driven lifecycle transition. Their `status` values remain independent of approval so a rejected record can be corrected and submitted again rather than being treated as permanently closed.

## Expense completion

- An approved advance payment, contract payment, accountable-funds request, or completion act may require follow-on accounting work; approval does not by itself mean the money has been paid or the work is closed.
- Accountable-funds requests have a distinct accounting-paid action and may have one or more advance reports. The request is not complete merely because its approval is complete.
- Attached files are part of the supporting record. Obtain access through the relevant `*-url` endpoint instead of retaining an old temporary URL.

## Safe changes

When changing one of these rules, update the relevant service, approval hook, user-facing status copy, and the focused tests under `backend/apps/contracts/tests/`. If it changes the meaning of a documented lifecycle or financial commitment, update this page too.
