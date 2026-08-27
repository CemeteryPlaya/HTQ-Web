# Signoff

Signoff is the platform’s shared approval engine. It defines reusable approval routes, creates an auditable approval process for a domain record, assigns tasks to named users, and reports the result back to the owning application.

## Start here

- [Overview](./overview.md) — domain model and relationship with application-owned records
- [Business rules](./business-rules.md) — route selection, quorums, decisions, locks, and lifecycle
- [User guide](./user-guide.md) — configure routes, review requests, and reopen a record
- [API reference](./api-reference.md) — HTTP resources and client conventions
- [Development guide](./development.md) — engine architecture, subject registration, and testing

## Canonical implementation

| Concern | Location |
| --- | --- |
| Backend app | `backend/apps/signoff/` |
| Models and reusable `Approvable` mixin | `backend/apps/signoff/models.py` |
| Approval engine | `backend/apps/signoff/services/engine.py` |
| Route and condition services | `backend/apps/signoff/services/route_service.py`, `conditions.py` |
| Subject registry | `backend/apps/signoff/services/registry.py` |
| HTTP routes | `backend/apps/signoff/urls.py` |
| Frontend API client | `frontend/src/api/signoff.ts` |
| Frontend pages and components | `frontend/src/pages/signoff/`, `frontend/src/components/signoff/` |

Signoff is deliberately domain-neutral. It knows an approval subject as a `(subject_type, subject_id)` pair, not as a foreign key to a particular application’s model.
