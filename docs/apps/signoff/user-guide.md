# Signoff user guide

## Configure an approval route

Route configuration is an administrative activity.

1. Open **Signoff → Routes** and select the subject type to approve.
2. Create an active route. Only one active route can exist for a subject type.
3. Add stages in the order the work should happen.
4. For each stage, choose named approvers or the initiator, then choose the `any` or `all` quorum.
5. Add conditions when the stage applies only to particular subject facts; add a fallback when a conditional branch needs a default path.
6. Mark a comment and/or PDF attachment as required where the approval evidence requires it.
7. Review coverage whenever reference-data values change, so a new value cannot leave a conditional order without a matching branch.

Use the same order number for parallel approvals. Use increasing order numbers for a sequential chain.

## Submit a record

Submit from the record’s own application, not from Signoff’s generic process endpoint. For example, submit an agreement from Contracts. The owning app validates that the record is eligible, starts Signoff, and opens the resulting process.

Once submitted, the record is locked while the process is pending.

## Make an approval decision

1. Open **Signoff → Waiting for me**.
2. Select the record and review its process and the linked domain record.
3. If required, attach the PDF before making the decision.
4. Add the required comment, if the stage calls for one.
5. Choose **Approve**, **Return for rework**, or **Reject**.

The inbox contains only tasks that are active now. A later sequential stage is not actionable until earlier stages have completed. You can decide only a task assigned to you.

## Cancel or reopen

- The initiator can cancel a running process; administrators can also do so. Cancellation returns the subject to an editable draft state.
- For a finished process, an administrator or an approver who made a decision in that process can return it for rework. Correct the subject in its owning app and submit it again.

Use **Return for rework** when the record can be corrected. Use **Reject** when the record should stay closed rather than being revised.
