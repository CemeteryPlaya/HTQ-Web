# Contracts overview

## Purpose

Contracts is the platform domain for planning and recording contract-related spending. It covers both agreement-backed work and expenses that do not have an agreement.

## Core records

| Area | Records | Purpose |
| --- | --- | --- |
| Reference data | Countries, administrators, programs | Define the organisational and budget context used by financial records. |
| Planning | Budgets, budget lines | Allocate a budget period into program-level lines. |
| Counterparties | Counterparties and contacts | Maintain the registry of suppliers and other external parties. |
| Contract work | Agreements, advance payments, contract payments, completion acts | Record an agreement and its payment and completion evidence. |
| Non-contract expenses | Invoices, accountable-funds requests, advance reports | Manage expenses that are paid without an agreement or advanced to an accountable employee. |

## Relationship model

```text
Budget
  └─ Budget line (program)
       ├─ Agreement ──> Advance payment / Contract payment / Completion act
       ├─ Invoice (without an agreement)
       └─ Accountable-funds request ──> Advance report

Counterparty ────────────────> Agreement or invoice
```

An agreement belongs to a budget and budget line, and identifies a counterparty. Payments and completion acts reference an agreement. Non-contract invoices and accountable-funds requests are still assigned to the applicable budget context so their financial effect can be reflected there.

## Lifecycle and approval

The domain uses the shared [Signoff](../signoff/README.md) approval system for approval-capable records. A user creates or updates a record, submits it through the Contracts application, and then follows the shared signoff process. Approval decisions themselves are handled by the signoff domain. See [business rules](./business-rules.md) for the Contracts-specific effects of that process.

The Contracts navigation includes a **Waiting for me** work queue. It shows the current user’s Contracts actions; it intentionally does not replace the signoff decision queue.

Status values differ by record type. Retrieve the current enum values from `GET /api/contracts/v1/enums` rather than duplicating labels or transitions in another integration.

## Application boundaries

- The backend is a Django app mounted at `/api/contracts/v1/`.
- The browser UI lives below `/contracts`.
- Other backend apps must use `backend/apps/contracts/interface.py` instead of importing Contracts models or services directly.
- The Contracts service can be disabled through the platform service registry. When disabled, its HTTP endpoints return the platform’s service-disabled response.

## Files and private documents

Agreements, invoices, payment orders, completion acts, and advance reports may expose files through dedicated endpoints. Consumers should obtain a fresh URL from the matching `*-url` endpoint rather than persisting a returned URL.
