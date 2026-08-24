# Signoff overview

## Purpose

Signoff provides a configurable, auditable approval workflow for records owned by other applications. It owns approval configuration, active approval processes, assignee tasks, and the event history. The owning application continues to own the document, domain validation, permissions to submit it, and business consequences of approval.

Contracts is one current consumer; see its [Contracts documentation](../contracts/README.md) for the records and business transitions it contributes.

## Three layers

| Layer | Main records | Responsibility |
| --- | --- | --- |
| Route | Approval route, route stage, route-stage approver | Reusable template: stages, assignees, quorums, conditions, and requirements. |
| Process | Approval process, process stage, approval task | A running snapshot for one subject. |
| Audit | Approval event | Immutable history of start, task decisions, cancellation, and reopening. |

A process stages are copied from the selected route at submission time. Editing a route later does not alter processes that have already started.

## Subject protocol

An approval subject is identified by a string such as `contracts.agreement` plus the record’s ID. Signoff has no direct model import or cross-app foreign key to that record.

The subject-owning app registers the type at startup and supplies callbacks to:

- read route-selection facts and describe permitted fact fields;
- present a title and browser URL for the subject;
- apply approval-state changes to the subject’s `Approvable` mixin;
- apply domain-specific effects after approval, rejection, rework, or cancellation.

This keeps the dependency one-way: the owner integrates with Signoff, while Signoff never learns domain rules for budgets, agreements, or any other type.

## Interfaces

- Backend API: `/api/signoff/v1/`
- Browser UI: `/signoff`
- Cross-app backend interface: `backend/apps/signoff/interface.py`

The owning domain should expose its own submit action. Signoff’s generic process-creation endpoint is an operator tool and should not be used as the normal browser workflow, because direct use bypasses domain-specific authorization and validation.
