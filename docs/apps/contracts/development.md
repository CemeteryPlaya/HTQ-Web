# Developing Contracts

## Code map

| Responsibility | Location |
| --- | --- |
| Django models and statuses | `backend/apps/contracts/models.py` |
| Pydantic DTOs | `backend/apps/contracts/schemas.py` |
| HTTP views | `backend/apps/contracts/views.py` |
| URL declarations | `backend/apps/contracts/urls.py` |
| Domain services | `backend/apps/contracts/services/` |
| Cross-app public interface | `backend/apps/contracts/interface.py` |
| Approval hooks | `backend/apps/contracts/approval_hooks.py` |
| React API client and types | `frontend/src/api/contracts.ts`, `frontend/src/types/contracts.ts` |
| React pages and reusable views | `frontend/src/pages/contracts/`, `frontend/src/components/contracts/` |

## Backend conventions

Contracts follows the repository’s standard Django app boundary:

- Keep HTTP parsing and response shaping in `views.py`.
- Put domain logic in the appropriate file under `services/`.
- Add or update Pydantic request and response shapes in `schemas.py`.
- Keep cross-app access behind `interface.py`; never import Contracts models or services from another domain app.
- Add both route spellings when a new HTTP route is exposed, because `APPEND_SLASH` is disabled.
- Use a Django migration for every model change.

See `backend/README.md` for the full platform conventions, including JWT, service gating, API error behavior, and cross-app isolation.

## Testing

The app has focused backend tests under `backend/apps/contracts/tests/`, covering reference data, budgets and calculations, agreements, approval wiring, invoices, payments, completion acts, accountable-funds requests, and work-queue behavior.

Run the affected backend tests from `backend/`:

```powershell
pytest apps/contracts/tests
```

For UI changes, also run the relevant frontend checks from `frontend/`. End-to-end coverage for Contracts-related workflows is under `frontend/tests/e2e/`.

## Change checklist

1. Identify whether the change affects a domain record, approval state, budget calculation, API contract, or UI workflow.
2. Update models, DTOs, service logic, views, and the frontend client together where the contract changes.
3. Add a migration when the database schema changes.
4. Add or adjust backend tests; update end-to-end tests when the user workflow changes.
5. Update this documentation when terminology, lifecycle, routes, files, or user-facing behavior changes.

## Documentation ownership

Keep this folder as the entry point for Contracts documentation. Add narrowly focused pages here (for example, `budget-calculation.md` or `migration-notes.md`) when a topic can no longer be maintained clearly in the existing pages.
