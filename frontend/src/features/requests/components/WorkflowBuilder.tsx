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
import type {
  Assignee, AssigneeKind, WorkflowEdge, WorkflowGraph, WorkflowNode,
} from '@/features/requests/types';

interface Props {
  graph: WorkflowGraph;
  onChange: (graph: WorkflowGraph) => void;
}

const APPROVER_KINDS: { kind: AssigneeKind; label: string }[] = [
  { kind: 'user', label: 'Указать согласующего' },
  { kind: 'initiator', label: 'Заявитель' },
  { kind: 'initiator_supervisor', label: 'Руководитель' },
  { kind: 'department_head', label: 'Начальник отдела' },
  { kind: 'role', label: 'Роль' },
  { kind: 'project_admins', label: 'Администраторы проекта' },
];

const CC_KINDS: { kind: AssigneeKind; label: string }[] = [
  { kind: 'initiator', label: 'Заявитель' },
  { kind: 'user', label: 'Указать получателя' },
  { kind: 'role', label: 'Роль' },
];

const KIND_LABEL: Record<string, string> = Object.fromEntries(
  [...APPROVER_KINDS, ...CC_KINDS].map((k) => [k.kind, k.label]),
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
  if (a.kind === 'role' && a.name) return `Роль «${a.name}»`;
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

const SUBMIT_LABEL: Record<string, string> = { all: 'Все', selected: 'Выбранные', none: 'Никто' };

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
    name: 'Согласование',
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
  return (
    <div className="w-72 overflow-hidden rounded-lg border shadow-[var(--shadow-soft)]">
      <div className={`flex items-center justify-between px-3 py-1.5 text-xs font-semibold text-white ${headerColor}`}>
        <span className="truncate">{header}</span>
        {onDelete && (
          <button type="button" onClick={onDelete} className="opacity-80 hover:opacity-100" aria-label="Удалить шаг">
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
      <button type="button" onClick={onClick} className="block w-full bg-card px-3 py-2 text-left hover:bg-muted/40">
        {lines.map((l, i) => (
          <div key={i} className="truncate text-sm text-muted-foreground">{l}</div>
        ))}
        <div className="mt-1 flex items-center gap-1 text-xs text-primary">
          <Pencil className="h-3 w-3" /> редактировать
        </div>
      </button>
    </div>
  );
}

function Insert({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="my-1 flex h-6 w-6 items-center justify-center rounded-full border bg-card text-primary hover:bg-primary hover:text-primary-foreground"
      aria-label="Добавить шаг согласования"
    >
      <Plus className="h-4 w-4" />
    </button>
  );
}

/* ─── main ──────────────────────────────────────────────────────────────── */

type EditTarget = { role: 'start' | 'approval' | 'end'; index: number };

export function WorkflowBuilder({ graph, onChange }: Props) {
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
        header="Начало"
        headerColor="bg-slate-500"
        lines={[
          `Кто подаёт: ${SUBMIT_LABEL[start.submit_scope ?? 'all']}`
          + (start.submit_scope === 'selected' ? ` — ${namesOf(start.submit_user_ids ?? [], names)}` : ''),
        ]}
        onClick={() => openEditor('start', -1, start)}
      />
      <Insert onClick={() => insertApproval(0)} />

      {approvals.map((a, i) => (
        <Fragment key={a.id}>
          <NodeCard
            header={a.name || 'Согласование'}
            headerColor="bg-orange-500"
            lines={[`Согласующий: ${assigneeSummary(a.assignee, names)}`, `CC: ${ccSummary(a.cc, names)}`]}
            onClick={() => openEditor('approval', i, a)}
            onDelete={() => deleteApproval(i)}
          />
          <Insert onClick={() => insertApproval(i + 1)} />
        </Fragment>
      ))}

      <NodeCard
        header="Подтверждение"
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
                  {edit.role === 'start' ? 'Начало' : edit.role === 'end' ? 'Подтверждение' : (draft.name || 'Согласование')}
                </SheetTitle>
              </SheetHeader>

              <div className="space-y-5 py-4">
                {edit.role === 'start' && <StartEditor draft={draft} patch={patch} />}
                {edit.role === 'approval' && <ApprovalEditor draft={draft} patch={patch} />}
                {edit.role === 'end' && <EndEditor draft={draft} patch={patch} />}
              </div>

              <SheetFooter>
                <Button variant="outline" onClick={() => { setEdit(null); setDraft(null); }}>Отмена</Button>
                <Button onClick={saveDraft}>Сохранить</Button>
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
  const scope = draft.submit_scope ?? 'all';
  return (
    <div className="space-y-3">
      <Label>Кто может подавать этот запрос</Label>
      <RadioGroup value={scope} onValueChange={(v) => patch({ submit_scope: v as WorkflowNode['submit_scope'] })}>
        {(['all', 'selected', 'none'] as const).map((v) => (
          <label key={v} className="flex items-center gap-2 text-sm">
            <RadioGroupItem value={v} /> {SUBMIT_LABEL[v]}
          </label>
        ))}
      </RadioGroup>
      {scope === 'selected' && (
        <div className="space-y-1.5">
          <Label className="text-xs">Кто подаёт</Label>
          <EmployeePicker value={draft.submit_user_ids ?? []} onChange={(ids) => patch({ submit_user_ids: ids })} />
        </div>
      )}
    </div>
  );
}

function ApprovalEditor({ draft, patch }: EditorProps) {
  const kind = (draft.assignee?.kind ?? 'user') as AssigneeKind;

  return (
    <>
      <div className="space-y-1.5">
        <Label className="text-xs">Название шага</Label>
        <Input value={draft.name ?? ''} onChange={(e) => patch({ name: e.target.value })} />
      </div>

      <div className="space-y-2">
        <Label>Тип согласования</Label>
        <RadioGroup
          value={draft.approval_type ?? 'manual'}
          onValueChange={(v) => patch({ approval_type: v as WorkflowNode['approval_type'] })}
          className="flex flex-wrap gap-4"
        >
          {([['manual', 'Ручное'], ['auto_approve', 'Авто-одобрение'], ['auto_reject', 'Авто-отклонение']] as const).map(([v, l]) => (
            <label key={v} className="flex items-center gap-2 text-sm"><RadioGroupItem value={v} /> {l}</label>
          ))}
        </RadioGroup>
      </div>

      <div className="space-y-2">
        <Label>Согласующий</Label>
        <RadioGroup
          value={kind}
          onValueChange={(v) => patch({ assignee: makeAssignee(v as AssigneeKind, assigneeIds(draft.assignee), draft.assignee?.name ?? '') })}
          className="grid grid-cols-2 gap-2"
        >
          {APPROVER_KINDS.map((k) => (
            <label key={k.kind} className="flex items-center gap-2 text-sm"><RadioGroupItem value={k.kind} /> {k.label}</label>
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
            placeholder="Название роли"
          />
        )}
      </div>

      <div className="space-y-1.5">
        <Label className="text-xs">Режим</Label>
        <Select value={draft.mode ?? 'any'} onValueChange={(v) => patch({ mode: v as WorkflowNode['mode'] })}>
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="any">Любой из согласующих</SelectItem>
            <SelectItem value="all">Все согласующие</SelectItem>
            <SelectItem value="sequential">Последовательно</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-2">
        <Label>CC (копии)</Label>
        <CcEditor value={draft.cc ?? []} onChange={(cc) => patch({ cc })} />
      </div>

      <div className="space-y-1.5">
        <Label className="text-xs">Если согласующий пуст</Label>
        <Select value={draft.empty_rule ?? 'auto_approve'} onValueChange={(v) => patch({ empty_rule: v as WorkflowNode['empty_rule'] })}>
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="auto_approve">Авто-одобрить</SelectItem>
            <SelectItem value="specify">Указать согласующего</SelectItem>
            <SelectItem value="transfer_admin">Передать администратору</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-1.5">
        <Label className="text-xs">Если согласующий = заявитель</Label>
        <Select value={draft.same_person_rule ?? 'review'} onValueChange={(v) => patch({ same_person_rule: v as WorkflowNode['same_person_rule'] })}>
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="review">Заявитель сам рассматривает</SelectItem>
            <SelectItem value="auto_skip">Авто-пропуск</SelectItem>
            <SelectItem value="forward_manager">Переслать руководителю</SelectItem>
            <SelectItem value="forward_department">Переслать начальнику отдела</SelectItem>
          </SelectContent>
        </Select>
      </div>
    </>
  );
}

function EndEditor({ draft, patch }: EditorProps) {
  return (
    <div className="space-y-2">
      <Label>CC-получатели (кто получит копию по завершении)</Label>
      <CcEditor value={draft.cc ?? []} onChange={(cc) => patch({ cc })} />
    </div>
  );
}

/** Multiple CC recipients of mixed kinds at once — Requester + specific people
 *  + a role, combined (Lark parity). */
function CcEditor({ value, onChange }: { value: Assignee[]; onChange: (cc: Assignee[]) => void }) {
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
        <Checkbox checked={hasInitiator} onCheckedChange={(v) => setInitiator(Boolean(v))} /> Заявитель
      </label>
      <div className="space-y-1.5">
        <Label className="text-xs">Указать получателей</Label>
        <EmployeePicker value={userIds} onChange={setUsers} />
      </div>
      <div className="space-y-1.5">
        <Label className="text-xs">Роль (необязательно)</Label>
        <Input value={roleEntry?.name ?? ''} onChange={(e) => setRole(e.target.value)} placeholder="напр. accounting" />
      </div>
      <p className="text-xs text-muted-foreground">Можно комбинировать: Заявитель + конкретные люди + роль.</p>
    </div>
  );
}
