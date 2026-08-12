# Contracts

The Contracts application manages the financial workflow around budgets, counterparties, agreements, payments, completion acts, invoices without an agreement, and accountable-funds requests.

## Start here

- [Overview](./overview.md) — scope, vocabulary, relationships, and approval model
- [Business rules](./business-rules.md) — budget impact and how approval changes a record’s domain state
- [User guide](./user-guide.md) — common end-to-end workflows
- [API reference](./api-reference.md) — HTTP resources, files, and integration conventions
- [Development guide](./development.md) — code ownership, tests, and safe change process

## Canonical implementation

| Concern | Location |
| --- | --- |
| Backend app | `backend/apps/contracts/` |
| HTTP routes | `backend/apps/contracts/urls.py` |
| Request/response schemas | `backend/apps/contracts/schemas.py` |
| Business rules | `backend/apps/contracts/services/` |
| Frontend API client | `frontend/src/api/contracts.ts` |
| Frontend pages | `frontend/src/pages/contracts/` |
| Shared frontend components | `frontend/src/components/contracts/` |

This documentation describes the currently implemented Django domain app and React interface. It includes the application’s business workflows and rules; source code and tests remain the authority for exact validation and permissions.
