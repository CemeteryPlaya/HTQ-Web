/** Vertical, Lark-style approval route builder (Маршрут следования).
 *
 *  Linear flow: Начало (Submit) → Согласование (Approval)* → Подтверждение (End),
 *  with "+" buttons to insert approval steps. Clicking a node opens a right-hand
 *  drawer to edit it, mirroring Lark's node editors (screenshots 14–16).
 *  Serialises to/from the Pydantic `WorkflowGraph`: start / approval /
 *  end_approved, plus a hidden `end_rejected` that every approval's reject edge
 *  points at (keeps the graph valid without cluttering the vertical view).
 */

import { Fragment, useState } from 'react';
import { Pencil, Plus, Trash2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import {
  Sheet, SheetContent, SheetFooter, SheetHeader, SheetTitle,
} from '@/components/ui/sheet';

import { EmployeePicker } from '@/features/requests/components/EmployeePicker';
import { useEmployeeNames } from '@/features/requests/hooks';
import { translatedMap } from '@/lib/i18n/translatedMap';
import { useTranslation } from 'react-i18next';
import i18next from '@/i18n';
import type {
  Assignee, AssigneeKind, WorkflowEdge, WorkflowGraph, WorkflowNode,
} from '@/features/requests/types';

interface Props {
  graph: WorkflowGraph;
  onChange: (graph: WorkflowGraph) => void;
}

const APPROVER_KINDS: { kind: AssigneeKind; labelKey: string }[] = [
  { kind: 'user', labelKey: 'requests.approverKind.user' },
  { kind: 'initiator', labelKey: 'requests.approverKind.initiator' },
  { kind: 'initiator_supervisor', labelKey: 'requests.approverKind.supervisor' },
  { kind: 'department_head', labelKey: 'requests.approverKind.departmentHead' },
  { kind: 'role', labelKey: 'requests.approverKind.role' },
  { kind: 'project_admins', labelKey: 'requests.approverKind.projectAdmins' },
];

const CC_KINDS: { kind: AssigneeKind; labelKey: string }[] = [
  { kind: 'initiator', labelKey: 'requests.approverKind.initiator' },
  { kind: 'user', labelKey: 'requests.approverKind.recipient' },
  { kind: 'role', labelKey: 'requests.approverKind.role' },
];

const KIND_LABEL: Record<string, string> = translatedMap(
  Object.fromEntries([...APPROVER_KINDS, ...CC_KINDS].map((k) => [k.kind, k.labelKey])),
);

/* ─── assignee helpers ──────────────────────────────────────────────────── */

function assigneeIds(a?: Assignee | null): number[] {
  if (!a) return [];
  if (Array.isArray(a.ids)) return a.ids;
  if (typeof a.id === 'number') return [a.id];
  return [];
}
function makeAssignee(kind: AssigneeKind, ids: number[], name = ''): Assignee {
  if (kind === 'user') return ids.length > 1 ? { kind: 'users', ids } : { kind: 'user', id: ids[0] };
  if (kind === 'role') return { kind: 'role', name };
  return { kind };
}
function assigneeSummary(a: Assignee | null | undefined, names: Map<number, string>): string {
  if (!a) return '—';
  if (a.kind === 'role' && a.name) return i18next.t('requests.workflow.roleNamed', { name: a.name });
  const ids = assigneeIds(a);
  if (ids.length) return ids.map((id) => names.get(id) ?? `ID ${id}`).join(', ');
  return KIND_LABEL[a.kind] ?? a.kind;
}
function ccSummary(cc: Assignee[] | null | undefined, names: Map<number, string>): string {
  if (!cc || cc.length === 0) return '—';
  return cc.map((c) => assigneeSummary(c, names)).join('; ');
}
function namesOf(ids: number[], names: Map<number, string>): string {
  return ids.map((id) => names.get(id) ?? `ID ${id}`).join(', ');
}

const SUBMIT_LABEL: Record<string, string> = translatedMap({
  all: 'requests.submitScope.all',
  selected: 'requests.submitScope.selected',
  none: 'requests.submitScope.none',
});

/* ─── graph <-> parts ───────────────────────────────────────────────────── */

function graphToParts(graph: WorkflowGraph) {
  const start = graph.nodes.find((n) => n.type === 'start') ?? { id: 'n_start', type: 'start' as const };
  const end = graph.nodes.find((n) => n.type === 'end_approved') ?? { id: 'n_end', type: 'end_approved' as const };
  const approvals = graph.nodes.filter((n) => n.type === 'approval');
  return { start, approvals, end };
}

function partsToGraph(start: WorkflowNode, approvals: WorkflowNode[], end: WorkflowNode): WorkflowGraph {
  const rejected: WorkflowNode = { id: 'n_rejected', type: 'end_rejected' };
  const chain = [start, ...approvals, end];
  const edges: WorkflowEdge[] = [];
  for (let i = 0; i < chain.length - 1; i++) {
    edges.push({
      from: chain[i].id,
      to: chain[i + 1].id,
      on: chain[i].type === 'approval' ? 'approve' : undefined,
    });
  }
  for (const a of approvals) edges.push({ from: a.id, to: rejected.id, on: 'reject' });
  return { nodes: [...chain, rejected], edges };
}

function newApproval(): WorkflowNode {
  return {
    id: `n_${Math.random().toString(36).slice(2, 7)}`,
    type: 'approval',
    name: i18next.t('requests.workflow.approvalStep'),
    approval_type: 'manual',
    assignee: { kind: 'user' },
    mode: 'any',
    cc: [],
    empty_rule: 'auto_approve',
    same_person_rule: 'review',
  };
}

/* ─── vertical node card ────────────────────────────────────────────────── */

function NodeCard({
  header, headerColor, lines, onClick, onDelete,
}: {
  header: string;
  headerColor: string;
  lines: string[];
  onClick: () => void;
  onDelete?: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="w-72 overflow-hidden rounded-lg border shadow-[var(--shadow-soft)]">
      <div className={`flex items-center justify-between px-3 py-1.5 text-xs font-semibold text-white ${headerColor}`}>
        <span className="truncate">{header}</span>
        {onDelete && (
          <button type="button" onClick={onDelete} className="opacity-80 hover:opacity-100" aria-label={t('requests.workflow.deleteStep')}>
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
      <button type="button" onClick={onClick} className="block w-full bg-card px-3 py-2 text-left hover:bg-muted/40">
        {lines.map((l, i) => (
          <div key={i} className="truncate text-sm text-muted-foreground">{l}</div>
        ))}
        <div className="mt-1 flex items-center gap-1 text-xs text-primary">
          <Pencil className="h-3 w-3" /> {t('requests.workflow.editLower')}
        </div>
      </button>
    </div>
  );
}

function Insert({ onClick }: { onClick: () => void }) {
  const { t } = useTranslation();
  return (
    <button
      type="button"
      onClick={onClick}
      className="my-1 flex h-6 w-6 items-center justify-center rounded-full border bg-card text-primary hover:bg-primary hover:text-primary-foreground"
      aria-label={t('requests.workflow.addStep')}
    >
      <Plus className="h-4 w-4" />
    </button>
  );
}

/* ─── main ──────────────────────────────────────────────────────────────── */

type EditTarget = { role: 'start' | 'approval' | 'end'; index: number };

export function WorkflowBuilder({ graph, onChange }: Props) {
  const { t } = useTranslation();
  const { start, approvals, end } = graphToParts(graph);
  const names = useEmployeeNames();
  const [edit, setEdit] = useState<EditTarget | null>(null);
  const [draft, setDraft] = useState<WorkflowNode | null>(null);

  function openEditor(role: EditTarget['role'], index: number, node: WorkflowNode) {
    setDraft(JSON.parse(JSON.stringify(node)));
    setEdit({ role, index });
  }

  function insertApproval(at: number) {
    const next = approvals.slice();
    next.splice(at, 0, newApproval());
    onChange(partsToGraph(start, next, end));
  }
  function deleteApproval(i: number) {
    onChange(partsToGraph(start, approvals.filter((_, idx) => idx !== i), end));
  }
  function saveDraft() {
    if (!edit || !draft) return;
    if (edit.role === 'start') onChange(partsToGraph(draft, approvals, end));
    else if (edit.role === 'end') onChange(partsToGraph(start, approvals, draft));
    else {
      const next = approvals.slice();
      next[edit.index] = draft;
      onChange(partsToGraph(start, next, end));
    }
    setEdit(null);
    setDraft(null);
  }

  const patch = (p: Partial<WorkflowNode>) => setDraft((d) => (d ? { ...d, ...p } : d));

  return (
    <div className="flex flex-col items-center py-2">
      <NodeCard
        header={t('requests.workflow.start')}
        headerColor="bg-slate-500"
        lines={[
          t('requests.workflow.whoSubmitsValue', { scope: SUBMIT_LABEL[start.submit_scope ?? 'all'] })
          + (start.submit_scope === 'selected' ? ` — ${namesOf(start.submit_user_ids ?? [], names)}` : ''),
        ]}
        onClick={() => openEditor('start', -1, start)}
      />
      <Insert onClick={() => insertApproval(0)} />

      {approvals.map((a, i) => (
        <Fragment key={a.id}>
          <NodeCard
            header={a.name || t('requests.workflow.approvalStep')}
            headerColor="bg-orange-500"
            lines={[t('requests.workflow.approverValue', { value: assigneeSummary(a.assignee, names) }), `CC: ${ccSummary(a.cc, names)}`]}
            onClick={() => openEditor('approval', i, a)}
            onDelete={() => deleteApproval(i)}
          />
          <Insert onClick={() => insertApproval(i + 1)} />
        </Fragment>
      ))}

      <NodeCard
        header={t('requests.workflow.end')}
        headerColor="bg-slate-500"
        lines={[`CC: ${ccSummary(end.cc, names)}`]}
        onClick={() => openEditor('end', -1, end)}
      />

      <Sheet open={edit != null} onOpenChange={(o) => { if (!o) { setEdit(null); setDraft(null); } }}>
        <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-md">
          {draft && edit && (
            <>
              <SheetHeader>
                <SheetTitle>
                  {edit.role === 'start' ? t('requests.workflow.start') : edit.role === 'end' ? t('requests.workflow.end') : (draft.name || t('requests.workflow.approvalStep'))}
                </SheetTitle>
              </SheetHeader>

              <div className="space-y-5 py-4">
                {edit.role === 'start' && <StartEditor draft={draft} patch={patch} />}
                {edit.role === 'approval' && <ApprovalEditor draft={draft} patch={patch} />}
                {edit.role === 'end' && <EndEditor draft={draft} patch={patch} />}
              </div>

              <SheetFooter>
                <Button variant="outline" onClick={() => { setEdit(null); setDraft(null); }}>{t('common.cancel')}</Button>
                <Button onClick={saveDraft}>{t('common.save')}</Button>
              </SheetFooter>
            </>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}

/* ─── drawer editors ────────────────────────────────────────────────────── */

type EditorProps = { draft: WorkflowNode; patch: (p: Partial<WorkflowNode>) => void };

function StartEditor({ draft, patch }: EditorProps) {
  const { t } = useTranslation();
  const scope = draft.submit_scope ?? 'all';
  return (
    <div className="space-y-3">
      <Label>{t('requests.workflow.whoCanSubmit')}</Label>
      <RadioGroup value={scope} onValueChange={(v) => patch({ submit_scope: v as WorkflowNode['submit_scope'] })}>
        {(['all', 'selected', 'none'] as const).map((v) => (
          <label key={v} className="flex items-center gap-2 text-sm">
            <RadioGroupItem value={v} /> {SUBMIT_LABEL[v]}
          </label>
        ))}
      </RadioGroup>
      {scope === 'selected' && (
        <div className="space-y-1.5">
          <Label className="text-xs">{t('requests.workflow.whoSubmits')}</Label>
          <EmployeePicker value={draft.submit_user_ids ?? []} onChange={(ids) => patch({ submit_user_ids: ids })} />
        </div>
      )}
    </div>
  );
}

function ApprovalEditor({ draft, patch }: EditorProps) {
  const { t } = useTranslation();
  const kind = (draft.assignee?.kind ?? 'user') as AssigneeKind;

  return (
    <>
      <div className="space-y-1.5">
        <Label className="text-xs">{t('requests.workflow.stepName')}</Label>
        <Input value={draft.name ?? ''} onChange={(e) => patch({ name: e.target.value })} />
      </div>

      <div className="space-y-2">
        <Label>{t('requests.workflow.approvalType')}</Label>
        <RadioGroup
          value={draft.approval_type ?? 'manual'}
          onValueChange={(v) => patch({ approval_type: v as WorkflowNode['approval_type'] })}
          className="flex flex-wrap gap-4"
        >
          {([['manual', t('requests.workflow.manual')], ['auto_approve', t('requests.workflow.autoApprove')], ['auto_reject', t('requests.workflow.autoReject')]] as const).map(([v, l]) => (
            <label key={v} className="flex items-center gap-2 text-sm"><RadioGroupItem value={v} /> {l}</label>
          ))}
        </RadioGroup>
      </div>

      <div className="space-y-2">
        <Label>{t('requests.workflow.approver')}</Label>
        <RadioGroup
          value={kind}
          onValueChange={(v) => patch({ assignee: makeAssignee(v as AssigneeKind, assigneeIds(draft.assignee), draft.assignee?.name ?? '') })}
          className="grid grid-cols-2 gap-2"
        >
          {APPROVER_KINDS.map((k) => (
            <label key={k.kind} className="flex items-center gap-2 text-sm"><RadioGroupItem value={k.kind} /> {t(k.labelKey)}</label>
          ))}
        </RadioGroup>
        {kind === 'user' && (
          <EmployeePicker
            value={assigneeIds(draft.assignee)}
            onChange={(ids) => patch({ assignee: makeAssignee('user', ids) })}
          />
        )}
        {kind === 'role' && (
          <Input
            value={draft.assignee?.name ?? ''}
            onChange={(e) => patch({ assignee: { kind: 'role', name: e.target.value } })}
            placeholder={t('requests.workflow.roleNamePlaceholder')}
          />
        )}
      </div>

      <div className="space-y-1.5">
        <Label className="text-xs">{t('requests.workflow.mode')}</Label>
        <Select value={draft.mode ?? 'any'} onValueChange={(v) => patch({ mode: v as WorkflowNode['mode'] })}>
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="any">{t('requests.workflow.modeAny')}</SelectItem>
            <SelectItem value="all">{t('requests.workflow.modeAll')}</SelectItem>
            <SelectItem value="sequential">{t('requests.workflow.modeSequential')}</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-2">
        <Label>{t('requests.workflow.cc')}</Label>
        <CcEditor value={draft.cc ?? []} onChange={(cc) => patch({ cc })} />
      </div>

      <div className="space-y-1.5">
        <Label className="text-xs">{t('requests.workflow.emptyApprover')}</Label>
        <Select value={draft.empty_rule ?? 'auto_approve'} onValueChange={(v) => patch({ empty_rule: v as WorkflowNode['empty_rule'] })}>
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="auto_approve">{t('requests.workflow.emptyAutoApprove')}</SelectItem>
            <SelectItem value="specify">{t('requests.approverKind.user')}</SelectItem>
            <SelectItem value="transfer_admin">{t('requests.workflow.emptyToAdmin')}</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-1.5">
        <Label className="text-xs">{t('requests.workflow.selfApproval')}</Label>
        <Select value={draft.same_person_rule ?? 'review'} onValueChange={(v) => patch({ same_person_rule: v as WorkflowNode['same_person_rule'] })}>
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="review">{t('requests.workflow.selfDecides')}</SelectItem>
            <SelectItem value="auto_skip">{t('requests.workflow.selfSkip')}</SelectItem>
            <SelectItem value="forward_manager">{t('requests.workflow.selfToSupervisor')}</SelectItem>
            <SelectItem value="forward_department">{t('requests.workflow.selfToDeptHead')}</SelectItem>
          </SelectContent>
        </Select>
      </div>
    </>
  );
}

function EndEditor({ draft, patch }: EditorProps) {
  const { t } = useTranslation();

  return (
    <div className="space-y-2">
      <Label>{t('requests.workflow.ccRecipients')}</Label>
      <CcEditor value={draft.cc ?? []} onChange={(cc) => patch({ cc })} />
    </div>
  );
}

/** Multiple CC recipients of mixed kinds at once — Requester + specific people
 *  + a role, combined (Lark parity). */
function CcEditor({ value, onChange }: { value: Assignee[]; onChange: (cc: Assignee[]) => void }) {
  const { t } = useTranslation();
  const cc = value ?? [];
  const hasInitiator = cc.some((c) => c.kind === 'initiator');
  const usersEntry = cc.find((c) => c.kind === 'users' || c.kind === 'user');
  const roleEntry = cc.find((c) => c.kind === 'role');
  const userIds = usersEntry ? assigneeIds(usersEntry) : [];

  const setInitiator = (on: boolean) => {
    const rest = cc.filter((c) => c.kind !== 'initiator');
    onChange(on ? [{ kind: 'initiator' }, ...rest] : rest);
  };
  const setUsers = (ids: number[]) => {
    const rest = cc.filter((c) => c.kind !== 'users' && c.kind !== 'user');
    onChange(ids.length ? [...rest, { kind: 'users', ids }] : rest);
  };
  const setRole = (name: string) => {
    const rest = cc.filter((c) => c.kind !== 'role');
    onChange(name ? [...rest, { kind: 'role', name }] : rest);
  };

  return (
    <div className="space-y-3 rounded-md border p-3">
      <label className="flex items-center gap-2 text-sm">
        <Checkbox checked={hasInitiator} onCheckedChange={(v) => setInitiator(Boolean(v))} /> {t('requests.approverKind.initiator')}
      </label>
      <div className="space-y-1.5">
        <Label className="text-xs">{t('requests.workflow.pickRecipients')}</Label>
        <EmployeePicker value={userIds} onChange={setUsers} />
      </div>
      <div className="space-y-1.5">
        <Label className="text-xs">{t('requests.workflow.roleOptional')}</Label>
        <Input value={roleEntry?.name ?? ''} onChange={(e) => setRole(e.target.value)} placeholder={t('requests.workflow.rolePlaceholder')} />
      </div>
      <p className="text-xs text-muted-foreground">{t('requests.workflow.combineHint')}</p>
    </div>
  );
}
