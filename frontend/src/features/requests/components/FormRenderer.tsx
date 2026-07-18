/** Form renderer (v2, Lark parity). Renders every widget type produced by the
 *  builder: text/paragraph/description, number, amount (currency + value),
 *  single-select, reference (Data-from-Base lookup with dependent filtering),
 *  date, attachment, serial, repeatable group (Копировать/Удалить), formula,
 *  checkbox. Honours form-level conditional visibility (display_conditions). */

import { Copy, Plus, Trash2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';

import { useReferenceOptions } from '@/features/requests/hooks';
import type { DisplayCondition, FormField, FormSchema } from '@/features/requests/types';

interface Props {
  schema: FormSchema;
  values: Record<string, unknown>;
  onChange: (values: Record<string, unknown>) => void;
  readOnly?: boolean;
}

/* ─── conditional visibility ────────────────────────────────────────────── */

function evalCond(c: { field: string; op?: string; value?: unknown }, values: Record<string, unknown>): boolean {
  const v = values[c.field];
  switch (c.op ?? 'is') {
    case 'is': return String(v ?? '') === String(c.value ?? '');
    case 'is_not': return String(v ?? '') !== String(c.value ?? '');
    case 'gt': return Number(v) > Number(c.value);
    case 'lt': return Number(v) < Number(c.value);
    case 'contains': return String(v ?? '').includes(String(c.value ?? ''));
    default: return true;
  }
}
function isVisible(key: string, values: Record<string, unknown>, dcs: DisplayCondition[]): boolean {
  const dc = dcs.find((d) => d.target === key);
  if (!dc) return true;
  const res = dc.conditions.map((c) => evalCond(c, values));
  return (dc.match ?? 'all') === 'any' ? res.some(Boolean) : res.every(Boolean);
}

/* ─── per-widget controls ───────────────────────────────────────────────── */

interface CtrlProps { field: FormField; value: unknown; setValue: (v: unknown) => void; readOnly: boolean; values: Record<string, unknown>; }

function ReferenceControl({ field, value, setValue, readOnly, values }: CtrlProps) {
  const f = field as any;
  const dep: string | undefined = f.depends_on || undefined;
  const parentVal = dep ? values[dep] : undefined;
  const opts = useReferenceOptions(
    f.source || undefined,
    f.column || undefined,
    dep,
    parentVal != null ? String(parentVal) : undefined,
  );
  const list = opts.data?.options ?? [];
  if (!f.source) return <p className="text-xs text-muted-foreground">Справочник не задан.</p>;
  return (
    <Select disabled={readOnly} value={typeof value === 'string' ? value : ''} onValueChange={(v) => setValue(v || null)}>
      <SelectTrigger><SelectValue placeholder={opts.isLoading ? 'Загрузка…' : '—'} /></SelectTrigger>
      <SelectContent>
        {list.length === 0 && <div className="px-2 py-1.5 text-xs text-muted-foreground">Нет вариантов</div>}
        {list.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}
      </SelectContent>
    </Select>
  );
}

function AmountControl({ field, value, setValue, readOnly }: CtrlProps) {
  const f = field as any;
  const currencies: string[] = f.currencies?.length ? f.currencies : ['KZT'];
  const cur = (value as any)?.currency ?? currencies[0];
  const amt = (value as any)?.amount ?? (typeof value === 'number' ? value : '');
  return (
    <div className="flex gap-2">
      <Input
        type="number"
        step={`0.${'0'.repeat(Math.max(0, (f.decimals ?? 2) - 1))}1`}
        disabled={readOnly}
        value={amt === '' || amt == null ? '' : String(amt)}
        onChange={(e) => setValue({ currency: cur, amount: e.target.value === '' ? null : Number(e.target.value) })}
        placeholder="0"
        className="flex-1"
      />
      <Select disabled={readOnly} value={cur} onValueChange={(v) => setValue({ currency: v, amount: amt === '' ? null : Number(amt) })}>
        <SelectTrigger className="w-28"><SelectValue /></SelectTrigger>
        <SelectContent>{currencies.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}</SelectContent>
      </Select>
    </div>
  );
}

function GroupControl({ field, value, setValue, readOnly }: CtrlProps) {
  const f = field as any;
  const children: FormField[] = f.fields ?? [];
  const rows: Record<string, unknown>[] = Array.isArray(value) ? (value as any) : [];

  const setRows = (next: Record<string, unknown>[]) => setValue(next);
  const addRow = () => setRows([...rows, {}]);
  const copyRow = (i: number) => setRows([...rows.slice(0, i + 1), { ...rows[i] }, ...rows.slice(i + 1)]);
  const delRow = (i: number) => setRows(rows.filter((_, idx) => idx !== i));
  const patchRow = (i: number, key: string, v: unknown) =>
    setRows(rows.map((r, idx) => (idx === i ? { ...r, [key]: v } : r)));

  return (
    <div className="space-y-3">
      {rows.length === 0 && <p className="text-xs text-muted-foreground">Нет записей.</p>}
      {rows.map((row, i) => (
        <div key={i} className="rounded-lg border bg-muted/20 p-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-xs font-medium text-muted-foreground">{field.label} #{i + 1}</span>
            {!readOnly && (
              <div className="flex items-center gap-2">
                <button type="button" onClick={() => copyRow(i)} className="flex items-center gap-1 text-xs text-primary" aria-label="Копировать"><Copy className="h-3.5 w-3.5" /> Копировать</button>
                <button type="button" onClick={() => delRow(i)} className="flex items-center gap-1 text-xs text-destructive" aria-label="Удалить"><Trash2 className="h-3.5 w-3.5" /> Удалить</button>
              </div>
            )}
          </div>
          <div className="space-y-3">
            {children.map((c) => (
              <FieldRow key={c.key} field={c} value={row[c.key]} setValue={(v) => patchRow(i, c.key, v)} readOnly={readOnly} values={row} />
            ))}
          </div>
        </div>
      ))}
      {!readOnly && (
        <Button type="button" variant="outline" size="sm" onClick={addRow}>
          <Plus className="mr-1 h-4 w-4" /> Добавить сведения
        </Button>
      )}
    </div>
  );
}

function ScalarControl({ field, value, setValue, readOnly }: CtrlProps) {
  const inputId = `field-${field.key}`;
  const f = field as any;
  switch (field.type) {
    case 'paragraph':
      return (
        <textarea
          id={inputId} rows={3} disabled={readOnly}
          value={typeof value === 'string' ? value : value == null ? '' : String(value)}
          onChange={(e) => setValue(e.target.value || null)}
          className="w-full rounded-md border bg-background px-3 py-1.5 text-sm disabled:opacity-60"
        />
      );
    case 'number':
    case 'money':
      return (
        <Input id={inputId} type="number" step={field.type === 'money' ? '0.01' : 'any'} disabled={readOnly}
          value={value == null ? '' : String(value)}
          onChange={(e) => setValue(e.target.value === '' ? null : Number(e.target.value))} />
      );
    case 'date':
      return <Input id={inputId} type="date" disabled={readOnly} value={typeof value === 'string' ? value : ''} onChange={(e) => setValue(e.target.value || null)} />;
    case 'checkbox':
      return <Checkbox id={inputId} disabled={readOnly} checked={Boolean(value)} onCheckedChange={(c) => setValue(Boolean(c))} />;
    case 'serial':
      return <Input id={inputId} disabled value={typeof value === 'string' ? value : '(генерируется автоматически)'} />;
    case 'file':
      return readOnly
        ? <div className="text-sm text-muted-foreground">{Array.isArray(value) ? (value as string[]).join(', ') : (value ? String(value) : '—')}</div>
        : <Input id={inputId} type="file" multiple onChange={(e) => setValue(Array.from(e.target.files ?? []).map((x) => x.name))} />;
    case 'formula':
      return <Input id={inputId} disabled value={value == null ? '(вычисляется)' : String(value)} />;
    case 'dropdown': {
      const opts: string[] = f.options ?? [];
      return (
        <Select disabled={readOnly} value={typeof value === 'string' ? value : ''} onValueChange={(v) => setValue(v || null)}>
          <SelectTrigger id={inputId}><SelectValue placeholder="—" /></SelectTrigger>
          <SelectContent>{opts.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}</SelectContent>
        </Select>
      );
    }
    case 'text':
    default:
      return <Input id={inputId} type="text" disabled={readOnly} value={typeof value === 'string' ? value : value == null ? '' : String(value)} onChange={(e) => setValue(e.target.value || null)} />;
  }
}

function FieldRow({ field, value, setValue, readOnly, values }: CtrlProps) {
  // static text: no label / no input, just the content
  if (field.type === 'static_text') {
    return <p className="text-sm font-medium text-foreground">{(field as any).content}</p>;
  }
  const showLabelMark = field.type !== 'checkbox';
  const control =
    field.type === 'reference' ? <ReferenceControl field={field} value={value} setValue={setValue} readOnly={readOnly} values={values} />
    : field.type === 'amount' ? <AmountControl field={field} value={value} setValue={setValue} readOnly={readOnly} values={values} />
    : field.type === 'group' ? <GroupControl field={field} value={value} setValue={setValue} readOnly={readOnly} values={values} />
    : <ScalarControl field={field} value={value} setValue={setValue} readOnly={readOnly} values={values} />;

  return (
    <div className="space-y-1.5">
      <Label htmlFor={`field-${field.key}`} className="text-sm">
        {field.label}
        {showLabelMark && field.required ? <span className="ml-1 text-destructive">*</span> : null}
      </Label>
      {control}
    </div>
  );
}

export function FormRenderer({ schema, values, onChange, readOnly = false }: Props) {
  if (schema.fields.length === 0) {
    return <p className="text-sm text-muted-foreground">В этой форме пока нет полей.</p>;
  }
  const dcs = schema.display_conditions ?? [];
  return (
    <div className="space-y-4">
      {schema.fields
        .filter((field) => isVisible(field.key, values, dcs))
        .map((field) => (
          <FieldRow
            key={field.key}
            field={field}
            value={values[field.key]}
            setValue={(v) => onChange({ ...values, [field.key]: v })}
            readOnly={readOnly}
            values={values}
          />
        ))}
    </div>
  );
}
