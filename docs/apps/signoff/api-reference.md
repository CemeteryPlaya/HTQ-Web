# Signoff API reference

## Base URL and authentication

All Signoff endpoints are under:

```text
/api/signoff/v1
```

The API follows the platform JWT and error-envelope conventions. Both slash forms are registered; the first-party client uses paths without a trailing slash.

## Resources

| Resource | Endpoints | Notes |
| --- | --- | --- |
| Metadata | `GET /enums`, `GET /subjects` | States, choices, registered subject types, and route fact fields. |
| Routes | `/routes`, `/routes/{id}` | List, create, update, delete, and filter routes. |
| Route stages | `/routes/{route_id}/stages`, `/stages/{id}` | Configure a route’s stage order, rules, and approvers. |
| Processes | `/processes`, `/processes/{id}` | List and inspect approval history. `POST /processes` is operator-only. |
| Process actions | `/processes/{id}/cancel`, `/processes/{id}/rework` | Cancel a running process or reopen a completed one within the stated permissions. |
| Inbox | `GET /tasks/mine` | Current user’s active approval tasks only. |
| Task actions | `/tasks/{id}/attachment`, `/tasks/{id}/decision` | Upload required PDF evidence, then decide the assigned task. |

## Correct client sequence

For a required attachment, use multipart upload first:

```text
POST /api/signoff/v1/tasks/{task_id}/attachment
Content-Type: multipart/form-data
file=<PDF>
```

Then submit the JSON decision:

```text
POST /api/signoff/v1/tasks/{task_id}/decision
{ "decision": "approve", "comment": "..." }
```

The decision is rejected if a required attachment or comment is absent. The frontend helper is `signoffApi.attachDocument()` followed by `signoffApi.decide()`.

## Domain integration rule

Use the submit endpoint owned by the subject’s application for normal product flows, for example `POST /api/contracts/v1/agreements/{id}/submit`. Do not substitute `POST /processes`: it accepts generic identifiers and cannot enforce every domain owner’s eligibility and authorization rules.
