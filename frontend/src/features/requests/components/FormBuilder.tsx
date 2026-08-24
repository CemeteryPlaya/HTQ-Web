/** Lark-style form builder (Form Design, step 2). The "Поля формы" list is a
 *  TREE with nested drag-and-drop: drag any field to reorder it; a "Группа"
 *  renders its children in a bordered drop zone that HIGHLIGHTS when you drag
 *  over it — drop inside the border → the field enters that group, drop outside
 *  → it stays at the outer level. Add fields into a group with "+ поле в группу".
 *  Every field (top-level or nested) is selected in the list and edited in the
 *  side panel. Output is a `FormSchema`. */

import { DragDropContext, Draggable, Droppable, type DropResult } from '@hello-pangea/dnd';
import { CornerUpLeft, GripVertical, Trash2 } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';

import { useReferenceSources } from '@/features/requests/hooks';
import type { FormField, FormFieldType, FormSchema } from '@/features/requests/types';
import { translatedMap } from '@/lib/i18n/translatedMap';
import { useTranslation } from 'react-i18next';
import i18next from '@/i18n';

const FIELD_TYPES: { type: FormFieldType; labelKey: string }[] = [
  { type: 'text', labelKey: 'requests.fieldTypes.text' },
  { type: 'paragraph', labelKey: 'requests.fieldTypes.paragraph' },
  { type: 'static_text', labelKey: 'requests.fieldTypes.static_text' },
  { type: 'number', labelKey: 'requests.fieldTypes.number' },
  { type: 'amount', labelKey: 'requests.fieldTypes.amount' },
  { type: 'dropdown', labelKey: 'requests.fieldTypes.dropdown' },
  { type: 'reference', labelKey: 'requests.fieldTypes.reference' },
  { type: 'date', labelKey: 'requests.fieldTypes.date' },
  { type: 'file', labelKey: 'requests.fieldTypes.file' },
  { type: 'serial', labelKey: 'requests.fieldTypes.serial' },
  { type: 'group', labelKey: 'requests.fieldTypes.group' },
  { type: 'formula', labelKey: 'requests.fieldTypes.formula' },
  { type: 'checkbox', labelKey: 'requests.fieldTypes.checkbox' },
  { type: 'link_ref', labelKey: 'requests.fieldTypes.link_ref' },
];
const TYPE_LABEL: Record<string, string> = translatedMap(
  Object.fromEntries(FIELD_TYPES.map((f) => [f.type, f.labelKey])),
);

let seq = 0;
function makeField(type: FormFieldType): FormField {
  const key = `field_${Date.now().toString(36)}${seq++}`;
  const base = { key, label: i18next.t('requests.builder.newField'), required: false } as const;
  switch (type) {
    case 'amount':      return { ...base, type, currencies: ['KZT', 'USD'], decimals: 2, amount_in_words: false, contributes_to_total: false };
    case 'number':      return { ...base, type, contributes_to_total: false } as FormField;
    case 'money':       return { ...base, type, currency: 'KZT', contributes_to_total: false } as FormField;
    case 'dropdown':    return { ...base, type, options: [i18next.t('requests.builder.option1')], multiple: false } as FormField;
    case 'reference':   return { ...base, type, source: '', column: 'name', multiple: false };
    case 'static_text': return { ...base, type, content: i18next.t('requests.builder.staticTextDefault') };
    case 'serial':      return { ...base, type, prefix: '' };
    case 'group':       return { ...base, type, fields: [], repeatable: true, summarize_keys: [] };
    case 'formula':     return { ...base, type, expr: 'sum(items[].amount)', contributes_to_total: false } as FormField;
    case 'link_ref':    return { ...base, type, multiple: false };
    default:            return { ...base, type } as FormField;
  }
}

/* ─── immutable tree ops keyed by index path ────────────────────────────── */

type Path = number[];
const childrenOf = (f: FormField): FormField[] => (f as any).fields ?? [];

function getField(fields: FormField[], path: Path): FormField | null {
  let list = fields; let node: FormField | null = null;
  for (let k = 0; k < path.length; k++) {
    node = list[path[k]] ?? null;
    if (!node) return null;
    if (k < path.length - 1) list = childrenOf(node);
  }
  return node;
}
function mapAt(fields: FormField[], path: Path, fn: (f: FormField) => FormField): FormField[] {
  const [head, ...rest] = path;
  return fields.map((f, i) => {
    if (i !== head) return f;
    if (rest.length === 0) return fn(f);
    return { ...(f as any), fields: mapAt(childrenOf(f), rest, fn) };
  });
}
function removeAt(fields: FormField[], path: Path): FormField[] {
  const [head, ...rest] = path;
  if (rest.length === 0) return fields.filter((_, i) => i !== head);
  return fields.map((f, i) => (i === head ? { ...(f as any), fields: removeAt(childrenOf(f), rest) } : f));
}
function insertAt(fields: FormField[], path: Path, node: FormField): FormField[] {
  const [head, ...rest] = path;
  if (rest.length === 0) { const a = fields.slice(); a.splice(head, 0, node); return a; }
  return fields.map((f, i) => (i === head ? { ...(f as any), fields: insertAt(childrenOf(f), rest, node) } : f));
}
function addChildAt(fields: FormField[], groupPath: Path, child: FormField): FormField[] {
  return mapAt(fields, groupPath, (g) => ({ ...(g as any), fields: [...childrenOf(g), child] }));
}
/** After removing `from`, shift a navigation component of `to` that sits after
 *  the removed sibling (same-level reorder needs no shift — splice semantics). */
function adjustAfterRemoval(to: Path, from: Path): Path {
  const parent = from.slice(0, -1);
  const idx = from[from.length - 1];
  const isPrefix = parent.every((v, k) => v === to[k]);
  if (isPrefix && to.length > parent.length + 1 && to[parent.length] > idx) {
    const t = to.slice(); t[parent.length] -= 1; return t;
  }
  return to;
}
const samePath = (a: Path | null, b: Path) => a != null && a.length === b.length && a.every((v, i) => v === b[i]);
const startsWith = (a: Path, prefix: Path) => prefix.length <= a.length && prefix.every((v, i) => v === a[i]);

function findGroupPath(fields: FormField[], key: string, base: Path = []): Path | null {
  for (let i = 0; i < fields.length; i++) {
    const f = fields[i]; const p = [...base, i];
    if (f.type === 'group') {
      if (f.key === key) return p;
      const r = findGroupPath(childrenOf(f), key, p);
      if (r) return r;
    }
  }
  return null;
}
const parentOfDroppable = (fields: FormField[], id: string): Path =>
  id === 'root' ? [] : (findGroupPath(fields, id.slice(4)) ?? []);

/* ─── component ──────────────────────────────────────────────────────────── */

interface Props {
  schema: FormSchema;
  onChange: (schema: FormSchema) => void;
}

export function FormBuilder({ schema, onChange }: Props) {
  const { t } = useTranslation();
  const [sel, setSel] = useState<Path | null>(schema.fields.length ? [0] : null);
  const setFields = (fields: FormField[]) => onChange({ ...schema, fields });
  const selected = sel ? getField(schema.fields, sel) : null;

  function addTop(type: FormFieldType) {
    setFields([...schema.fields, makeField(type)]);
    setSel([schema.fields.length]);
  }
  function addChild(groupPath: Path, type: FormFieldType) {
    const g = getField(schema.fields, groupPath);
    const at = g ? childrenOf(g).length : 0;
    setFields(addChildAt(schema.fields, groupPath, makeField(type)));
    setSel([...groupPath, at]);
  }
  function remove(path: Path) {
    setFields(removeAt(schema.fields, path));
    if (sel && startsWith(sel, path)) setSel(null);
  }
  /** Move a group child out to the top level, right after its group. */
  function moveOut(path: Path) {
    const node = getField(schema.fields, path);
    if (!node || path.length < 2) return;
    const next = insertAt(removeAt(schema.fields, path), [path[0] + 1], node);
    setFields(next);
    setSel(null);
  }
  /** Move a top-level field into the chosen group. */
  function moveInto(path: Path, groupKey: string) {
    const node = getField(schema.fields, path);
    if (!node) return;
    const without = removeAt(schema.fields, path);
    const gp = findGroupPath(without, groupKey);
    if (!gp) return;
    setFields(addChildAt(without, gp, node));
    setSel(null);
  }

  const topGroups = schema.fields
    .filter((f) => f.type === 'group')
    .map((f) => ({ key: f.key, label: f.label }));

  function onDragEnd(r: DropResult) {
    if (!r.destination) return;
    // Same `type` guarantees src/dst are on the same level (root <-> root or a
    // group <-> group); no overlapping-droppable ambiguity.
    const srcParent = parentOfDroppable(schema.fields, r.source.droppableId);
    const dstParent = parentOfDroppable(schema.fields, r.destination.droppableId);
    if (samePath(srcParent, dstParent) && r.source.index === r.destination.index) return;
    const from = [...srcParent, r.source.index];
    if (startsWith(dstParent, from)) return; // never into own subtree
    const node = getField(schema.fields, from);
    if (!node) return;
    const to = adjustAfterRemoval([...dstParent, r.destination.index], from);
    setFields(insertAt(removeAt(schema.fields, from), to, node));
    setSel(null);
  }

  return (
    <div className="grid gap-4 md:grid-cols-[1fr_360px]">
      <div className="space-y-3">
        <div className="rounded-lg border bg-card">
          <div className="border-b px-3 py-2 text-xs font-semibold uppercase text-muted-foreground">{t('requests.builder.fields')}</div>
          {schema.fields.length === 0 && (
            <div className="px-3 py-6 text-center text-sm text-muted-foreground">{t('requests.builder.noFields')}</div>
          )}
          <DragDropContext onDragEnd={onDragEnd}>
            <FieldList
              fields={schema.fields} basePath={[]} droppableId="root"
              sel={sel} onSelect={setSel} onDelete={remove} onAddChild={addChild}
              groups={topGroups} onMoveOut={moveOut} onMoveInto={moveInto}
            />
          </DragDropContext>
        </div>

        <div className="flex flex-wrap gap-2">
          {FIELD_TYPES.map((ft) => (
            <button key={ft.type} type="button" onClick={() => addTop(ft.type)}
              className="rounded-md border bg-card px-3 py-1.5 text-xs font-medium hover:bg-muted">
              + {t(ft.labelKey)}
            </button>
          ))}
        </div>
      </div>

      {selected && sel ? (
        <aside className="rounded-lg border bg-card p-4">
          <div className="mb-3 text-xs font-semibold uppercase text-muted-foreground">
            {t('requests.builder.fieldProps', { type: TYPE_LABEL[selected.type] ?? selected.type })}
          </div>
          <FieldEditor field={selected} onChange={(next) => setFields(mapAt(schema.fields, sel, () => next))} />
        </aside>
      ) : (
        <aside className="rounded-lg border bg-card p-4 text-sm text-muted-foreground">
          {t('requests.builder.pickField')}
        </aside>
      )}
    </div>
  );
}

/* ─── recursive nested drag-and-drop list ───────────────────────────────── */

interface ListProps {
  fields: FormField[];
  basePath: Path;
  droppableId: string;
  sel: Path | null;
  onSelect: (p: Path) => void;
  onDelete: (p: Path) => void;
  onAddChild: (groupPath: Path, type: FormFieldType) => void;
  groups: { key: string; label: string }[];
  onMoveOut: (p: Path) => void;
  onMoveInto: (p: Path, groupKey: string) => void;
}

function FieldList({ fields, basePath, droppableId, sel, onSelect, onDelete, onAddChild, groups, onMoveOut, onMoveInto }: ListProps) {
  const { t } = useTranslation();
  const isGroupZone = droppableId !== 'root';
  return (
    <Droppable droppableId={droppableId} type={isGroupZone ? 'FIELD_CHILD' : 'FIELD_TOP'}>
      {(provided, snap) => (
        <ul
          ref={provided.innerRef}
          {...provided.droppableProps}
          className={
            isGroupZone
              ? `space-y-1 rounded-md border-2 border-dashed p-2 transition-colors ${snap.isDraggingOver ? 'border-primary bg-primary/10' : 'border-muted-foreground/25'}`
              : `divide-y ${snap.isDraggingOver ? 'bg-primary/5' : ''}`
          }
        >
          {fields.length === 0 && isGroupZone && (
            <li className="px-1 py-1 text-xs text-muted-foreground">{t('requests.builder.dropHere')}</li>
          )}
          {fields.map((f, i) => {
            const path = [...basePath, i];
            return (
              <Draggable key={f.key} draggableId={f.key} index={i}>
                {(dp, snap) => {
                  const row = (
                    <li ref={dp.innerRef} {...dp.draggableProps} className={snap.isDragging ? 'rounded bg-card shadow-lg ring-1 ring-primary/40' : ''}>
                      <div className={`flex items-center gap-2 rounded px-2 py-2 text-sm ${samePath(sel, path) ? 'bg-primary/10' : ''}`}>
                        <span {...dp.dragHandleProps} className="cursor-grab text-muted-foreground hover:text-foreground" aria-label={t('hr.positions.drag')}>
                          <GripVertical className="h-4 w-4" />
                        </span>
                        <button type="button" onClick={() => onSelect(path)} className="min-w-0 flex-1 text-left">
                          <span className="font-medium">{f.label}</span>
                          <span className="ml-2 text-xs text-muted-foreground">[{TYPE_LABEL[f.type] ?? f.type}]</span>
                          {f.required && <span className="ml-1 text-rose-600">*</span>}
                        </button>
                        {basePath.length === 0 && f.type !== 'group' && groups.length > 0 && (
                          <MoveIntoSelect groups={groups} onPick={(gk) => onMoveInto(path, gk)} />
                        )}
                        {basePath.length > 0 && (
                          <button type="button" onClick={() => onMoveOut(path)} className="text-muted-foreground hover:text-foreground" aria-label={t('requests.builder.moveOut')} title={t('requests.builder.moveOut')}>
                            <CornerUpLeft className="h-4 w-4" />
                          </button>
                        )}
                        <button type="button" onClick={() => onDelete(path)} className="text-muted-foreground hover:text-destructive" aria-label={t('common.delete')}>
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                      {/* Nested group zone is hidden while dragging this group (it's portaled). */}
                      {f.type === 'group' && !snap.isDragging && (
                        <div className="ml-6 mt-1 space-y-1">
                          <FieldList
                            fields={childrenOf(f)} basePath={path} droppableId={`grp:${f.key}`}
                            sel={sel} onSelect={onSelect} onDelete={onDelete} onAddChild={onAddChild}
                            groups={groups} onMoveOut={onMoveOut} onMoveInto={onMoveInto}
                          />
                          <div className="pl-2">
                            <AddSelect placeholder={t('requests.builder.addToGroup')} onAdd={(type) => onAddChild(path, type)} />
                          </div>
                        </div>
                      )}
                    </li>
                  );
                  // While dragging, render the item in a body portal so it escapes
                  // any transformed ancestor (fixes the offset + wrong-group detection
                  // for fields that live inside a group).
                  return snap.isDragging ? createPortal(row, document.body) : row;
                }}
              </Draggable>
            );
          })}
          {provided.placeholder}
        </ul>
      )}
    </Droppable>
  );
}

/* ─── per-field editor ──────────────────────────────────────────────────── */

const csv = (a?: string[]) => (a ?? []).join(', ');
const toCsv = (s: string) => s.split(',').map((x) => x.trim()).filter(Boolean);

function FieldEditor({ field, onChange }: { field: FormField; onChange: (next: FormField) => void }) {
  const { t } = useTranslation();
  const f = field as any;
  const set = (patch: Record<string, unknown>) => onChange({ ...(field as any), ...patch });
  const sources = useReferenceSources();
  const currentSource = sources.data?.find((s) => s.slug === f.source);

  return (
    <div className="space-y-3">
      <div className="space-y-1.5">
        <Label className="text-xs">{t('requests.builder.key')}</Label>
        <Input value={f.key} onChange={(e) => set({ key: e.target.value })} className="font-mono" />
      </div>
      <div className="space-y-1.5">
        <Label className="text-xs">{t('requests.builder.label')}</Label>
        <Input value={f.label} onChange={(e) => set({ label: e.target.value })} />
      </div>
      {field.type !== 'static_text' && (
        <label className="flex items-center gap-2 text-sm">
          <Checkbox checked={Boolean(f.required)} onCheckedChange={(v) => set({ required: Boolean(v) })} /> {t('requests.builder.required')}
        </label>
      )}

      {field.type === 'paragraph' && (
        <Field label={t('requests.builder.maxLength')}>
          <Input type="number" value={f.max ?? ''} onChange={(e) => set({ max: e.target.value ? Number(e.target.value) : undefined })} />
        </Field>
      )}
      {field.type === 'static_text' && (
        <Field label={t('requests.builder.text')}><Input value={f.content ?? ''} onChange={(e) => set({ content: e.target.value })} /></Field>
      )}
      {field.type === 'serial' && (
        <Field label={t('requests.builder.prefix')}><Input value={f.prefix ?? ''} onChange={(e) => set({ prefix: e.target.value })} placeholder={t('requests.builder.prefixPlaceholder')} /></Field>
      )}

      {(field.type === 'money' || field.type === 'number' || field.type === 'formula' || field.type === 'amount') && (
        <label className="flex items-center gap-2 text-sm">
          <Checkbox checked={Boolean(f.contributes_to_total)} onCheckedChange={(v) => set({ contributes_to_total: Boolean(v) })} /> {t('requests.builder.countInTotal')}
        </label>
      )}

      {field.type === 'amount' && (
        <>
          <Field label={t('requests.builder.currencies')}>
            <Input value={csv(f.currencies)} onChange={(e) => set({ currencies: toCsv(e.target.value).map((c) => c.toUpperCase()) })} placeholder="KZT, USD, EUR" />
          </Field>
          <Field label={t('requests.builder.decimals')}>
            <Input type="number" value={f.decimals ?? 2} onChange={(e) => set({ decimals: Number(e.target.value) })} />
          </Field>
          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={Boolean(f.amount_in_words)} onCheckedChange={(v) => set({ amount_in_words: Boolean(v) })} /> {t('requests.builder.amountInWords')}
          </label>
        </>
      )}

      {field.type === 'dropdown' && (
        <>
          <Field label={t('requests.builder.options')}>
            <textarea rows={4} value={(f.options ?? []).join('\n')}
              onChange={(e) => set({ options: e.target.value.split('\n').map((s: string) => s.trim()).filter(Boolean) })}
              className="w-full rounded-md border bg-background px-3 py-1.5 text-sm" />
          </Field>
          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={Boolean(f.multiple)} onCheckedChange={(v) => set({ multiple: Boolean(v) })} /> {t('requests.builder.multiple')}
          </label>
          <p className="text-xs text-muted-foreground">{t('requests.builder.referenceHint')}</p>
        </>
      )}

      {field.type === 'reference' && (
        <>
          <Field label={t('requests.fieldTypes.reference')}>
            <Select value={f.source || ''} onValueChange={(v) => set({ source: v, column: '' })}>
              <SelectTrigger><SelectValue placeholder={sources.isLoading ? t('signoff.loadingEllipsis') : t('requests.builder.pickReference')} /></SelectTrigger>
              <SelectContent>
                {(sources.data ?? []).map((s) => <SelectItem key={s.slug} value={s.slug}>{s.name}</SelectItem>)}
              </SelectContent>
            </Select>
          </Field>
          <Field label={t('requests.builder.column')}>
            <Select value={f.column || ''} onValueChange={(v) => set({ column: v })} disabled={!currentSource}>
              <SelectTrigger><SelectValue placeholder={currentSource ? t('requests.builder.pickColumn') : t('requests.builder.pickReferenceFirst')} /></SelectTrigger>
              <SelectContent>
                {(currentSource?.columns ?? []).map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}
              </SelectContent>
            </Select>
          </Field>
          <Field label={t('requests.builder.dependsOn')}>
            <Input value={f.depends_on ?? ''} onChange={(e) => set({ depends_on: e.target.value || undefined })} placeholder={t('requests.builder.dependsOnPlaceholder')} className="font-mono" />
          </Field>
          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={Boolean(f.multiple)} onCheckedChange={(v) => set({ multiple: Boolean(v) })} /> {t('requests.builder.multiple')}
          </label>
        </>
      )}

      {field.type === 'formula' && (
        <Field label={t('requests.builder.expression')}><Input value={f.expr ?? ''} onChange={(e) => set({ expr: e.target.value })} className="font-mono" /></Field>
      )}
      {field.type === 'link_ref' && (
        <Field label={t('requests.builder.templateSlug')}><Input value={f.template_slug ?? ''} onChange={(e) => set({ template_slug: e.target.value || undefined })} className="font-mono" /></Field>
      )}

      {field.type === 'group' && (
        <>
          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={f.repeatable !== false} onCheckedChange={(v) => set({ repeatable: Boolean(v) })} /> {t('requests.builder.repeatable')}
          </label>
          <Field label={t('requests.builder.sumFields')}>
            <Input value={csv(f.summarize_keys)} onChange={(e) => set({ summarize_keys: toCsv(e.target.value) })} className="font-mono" />
          </Field>
          <p className="text-xs text-muted-foreground">{t('requests.builder.groupHint')}</p>
        </>
      )}
    </div>
  );
}

function AddSelect({ placeholder, onAdd }: { placeholder: string; onAdd: (type: FormFieldType) => void }) {
  const { t } = useTranslation();

  return (
    <Select value="" onValueChange={(v) => v && onAdd(v as FormFieldType)}>
      <SelectTrigger className="h-8 w-56 text-xs"><SelectValue placeholder={placeholder} /></SelectTrigger>
      <SelectContent>
        {FIELD_TYPES.filter((ft) => ft.type !== 'group').map((ft) => (
          <SelectItem key={ft.type} value={ft.type}>{t(ft.labelKey)}</SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

/** Compact "move this top-level field into a group" picker. */
function MoveIntoSelect({ groups, onPick }: { groups: { key: string; label: string }[]; onPick: (groupKey: string) => void }) {
  const { t } = useTranslation();
  return (
    <Select value="" onValueChange={(v) => v && onPick(v)}>
      <SelectTrigger className="h-7 w-auto gap-1 border-dashed px-2 text-xs text-muted-foreground" aria-label={t('requests.builder.moveInto')}>
        <SelectValue placeholder={t('requests.builder.intoGroup')} />
      </SelectTrigger>
      <SelectContent>
        {groups.map((g) => (
          <SelectItem key={g.key} value={g.key}>{g.label || g.key}</SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label className="text-xs">{label}</Label>
      {children}
    </div>
  );
}
