# Developing Signoff

## Code map

| Responsibility | Location |
| --- | --- |
| Models, states, and `Approvable` | `backend/apps/signoff/models.py` |
| Process start, decisions, completion, cancellation, reopening | `backend/apps/signoff/services/engine.py` |
| Route mutation and validation | `backend/apps/signoff/services/route_service.py` |
| Conditional branch language | `backend/apps/signoff/services/conditions.py` |
| Subject registration | `backend/apps/signoff/services/registry.py` |
| PDF task attachments | `backend/apps/signoff/services/attachments.py` |
| API presentation | `backend/apps/signoff/services/presentation.py` |
| Cross-app interface | `backend/apps/signoff/interface.py` |
| React client and types | `frontend/src/api/signoff.ts`, `frontend/src/types/signoff.ts` |

## Add an approval-capable subject

The owner application—not Signoff—adds the integration:

1. Inherit `signoff.Approvable` and declare a stable `SIGNOFF_SUBJECT_TYPE`, such as `contracts.example`.
2. In the owner app’s startup hook, register the type with title/URL presentation, facts, fact-field metadata, and lifecycle callbacks.
3. Add a submit action to the owner’s API. It must enforce the owner’s permissions and record-specific prerequisites before calling Signoff.
4. Keep the owner’s business transitions in that owner’s callback code, not in the generic Signoff engine.
5. Add tests for registration, route selection, callbacks, and the owner’s submit endpoint.

The Contracts integration in `backend/apps/contracts/approval_hooks.py` is the reference implementation.

## Important invariants

- Do not add direct imports from Signoff to another domain’s models or services.
- Do not store a generic foreign key or Django `ContentType` for the subject; the `(subject_type, subject_id)` protocol preserves app isolation.
- Treat process stages and tasks as a snapshot. Never mutate a running process to reflect a route edit.
- Keep completion callbacks inside the engine transaction. If an owner callback fails, the approval completion must fail too rather than leaving a completed process over an unchanged subject.
- Preserve row locking and race-condition protections in `engine.py` when changing decisions or quorums.

## Testing

Focused backend tests are under `backend/apps/signoff/tests/`. Run them from `backend/`:

```powershell
pytest apps/signoff/tests
```

For changes that affect an owning application, run its approval integration tests too—for Contracts, that includes `backend/apps/contracts/tests/test_approval_*.py`.

## Documentation ownership

Update the [business rules](./business-rules.md) and API reference whenever a process state, decision, route-selection rule, permission, or endpoint contract changes.
