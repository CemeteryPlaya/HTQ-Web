# Signoff business rules

## Route selection

There can be only one active route for a given subject type. When a subject is submitted, Signoff reads facts from its owner and selects stages from that active route.

- Stages with the same numeric `order` run in parallel.
- Orders run sequentially: the next order is activated only after the current order completes.
- An unconditional non-fallback stage is always selected.
- Conditional stages are selected when their predicates match the subject facts.
- If no conditional stage matches, a fallback stage at that order is selected when configured.
- If an order has no unconditional stage, no matching condition, and no fallback, submission fails instead of creating a process with no valid path.

The facts, selected stages, assignees, requirements, and conditions are copied to the process at launch. Route or reference-data edits cannot silently rewrite a live approval.

## Assignees and quorums

Each stage gets its approvers in one of two ways:

- **Named** — specifically configured user IDs are copied to the process tasks.
- **Initiator** — the user who submitted the subject becomes the approver for that stage, useful for a final acknowledgement or signature step.

Stage quorum determines when approval passes:

- `any`: one approver is sufficient.
- `all`: every assigned approver must approve.

An approver can decide only their own active task. Elevated platform access does not allow a user to approve somebody else’s task.

## Decisions and outcomes

| Decision | Process result | Subject editability |
| --- | --- | --- |
| Approve | Advances the stage when its quorum is met; the process becomes approved after the final stage. | Locked until the process ends. |
| Reject | Immediately rejects the entire process; untouched later work is skipped. | Locked. |
| Return for rework | Immediately ends the process as rework; the owner can correct the subject. | Editable. |
| Cancel | The initiator or an administrator may cancel a running process. | Returns to draft/editable state. |

A rejected process is deliberately different from rework: rejection remains locked, while rework is an explicit request to correct and resubmit. Resubmission always starts a new process with a fresh route snapshot.

## Evidence and comments

A route stage can require a comment, an attachment, or both before approval. Attachments are uploaded to the task before the decision is submitted. They must be a valid PDF, and only the assignee may attach a document to their task. Clients should therefore upload first and then make the approval decision.

## Reopening a closed process

`rework` on a process is for a process that has already finished. It is not available while the process is running; an active assignee should instead decide **Return for rework**, and an initiator can cancel their running process.

After completion, an elevated administrator or an approver who actually made a decision in that process can return it for rework. Merely having had a task that was skipped does not grant that ability. Reopening unlocks the subject but does not resume old tasks; a later resubmission creates a new process.

## State synchronization and audit

Approval-capable subjects carry a denormalized `approval_state` so their owning applications can filter and protect records without repeatedly querying Signoff. The engine updates that state and runs the registered subject callback in the same transaction that closes or changes the process. `ApprovalEvent` records the associated actions for auditing.
