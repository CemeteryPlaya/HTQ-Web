# Contracts API reference

## Base URL and authentication

All resources are mounted below:

```text
/api/contracts/v1
```

The application uses the platform JWT API conventions. Send a Bearer access token, use JSON unless uploading a file, and handle errors using the standard platform error envelope.

Both trailing-slash and non-trailing-slash forms are registered by the backend. The first-party frontend uses paths without a trailing slash; integrations should choose one form and use it consistently.

## Resource groups

| Resource | Base path | Notes |
| --- | --- | --- |
| My work | `/tasks/mine` | Current user’s Contracts action queue. |
| Enums | `/enums` | Current domain status and choice values. |
| Reference data | `/countries`, `/programs`, `/administrators` | Lookup and maintenance resources. |
| Budgets | `/budgets`, `/budget-lines` | Includes `POST /budgets/full`, `/lines`, `/agreements`, and `/submit` actions. |
| Counterparties | `/counterparties` | Includes `POST /counterparties/full` and `/submit`. |
| Agreements | `/agreements` | Includes `/submit`, `/status`, `/file`, and `/file-url`. |
| Invoices | `/invoices` | Invoices without an agreement; includes `/submit`, `/status`, `/file`, and `/file-url`. |
| Advance payments | `/advance-payments` | Agreement-backed advance payments; includes submission and payment-order endpoints. |
| Contract payments | `/contract-payments` | Agreement-backed payments; includes submission, invoice, and payment-order endpoints. |
| Completion acts | `/completion-acts` | Includes submission, act, and payment-order endpoints. |
| Accountable funds | `/accountable-funds-requests` | Includes submission, budget-line assignment, accounting-paid action, and nested advance reports. |
| Advance reports | `/advance-reports` | Detail, submit, and file URL endpoints. |

Collection resources use the normal collection/detail pattern: `GET` lists, `POST` creates, and `GET`/update/delete operations target `/{id}` where implemented. The canonical list of routes is `backend/apps/contracts/urls.py`; request and response DTOs are defined in `backend/apps/contracts/schemas.py`.

## Approval submission

Submit an approval-capable record through its Contracts resource, for example:

```text
POST /api/contracts/v1/agreements/{agreement_id}/submit
```

The response represents the initiated shared signoff process. Do not create a signoff process directly for a Contracts record: doing so bypasses the domain’s ownership and permission checks.

## File endpoints

File-bearing records use two endpoint types:

- A file endpoint (for example, `/agreements/{id}/file` or `/contract-payments/{id}/payment-order`) accepts the relevant uploaded document.
- A corresponding URL endpoint (for example, `/agreements/{id}/file-url`) returns an access URL for a stored private file.

Treat returned URLs as temporary access credentials. Request a new URL when it is needed and do not store it as a durable identifier.

## Frontend integration

Use `frontend/src/api/contracts.ts` and `frontend/src/types/contracts.ts` for the current first-party client contract. They expose pagination and filtering parameters used by the UI, and prevent duplicate endpoint construction in React features.
