/** Form renderer (v2, Lark parity). Renders every widget type produced by the
 *  builder: text/paragraph/description, number, amount (currency + value),
 *  single-select, reference (Data-from-Base lookup with dependent filtering),
 *  budget line (администратор → программа из раздела «Договоры»), date,
 *  attachment, serial, repeatable group (Копировать/Удалить), formula,
 *  checkbox. Honours form-level conditional visibility (display_conditions). */

import { Copy, Plus, Trash2 } from 'lucide-react';
import { useMemo, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { DateInput } from '@/components/ui/date-input';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';

import { useBudgetLines, useReferenceOptions } from '@/features/requests/hooks';
import type { DisplayCondition, FormField, FormSchema, SupplierQuote, SupplierQuotesValue,
} from '@/features/requests/types';
import type { BudgetLineFlat } from '@/types/contracts';
import { useTranslation } from 'react-i18next';

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

interface CtrlProps {
  field: FormField; value: unknown; setValue: (v: unknown) => void;
  readOnly: boolean; values: Record<string, unknown>;
  /** Путь до поля для DOM-id: у вложенных полей ключ не уникален на
   *  странице («name» есть и в позициях, и в поставщике; строки списка
   *  повторяют его N раз), а одинаковые id ломают подписи. */
  idPrefix?: string;
}
const domId = (prefix: string | undefined, key: string) => `field-${prefix ? `${prefix}-` : ''}${key}`;

function ReferenceControl({ field, value, setValue, readOnly, values }: CtrlProps) {
  const { t } = useTranslation();
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
  if (!f.source) return <p className="text-xs text-muted-foreground">{t('requests.form.noReference')}</p>;
  return (
    <Select disabled={readOnly} value={typeof value === 'string' ? value : ''} onValueChange={(v) => setValue(v || null)}>
      <SelectTrigger><SelectValue placeholder={opts.isLoading ? t('signoff.loadingEllipsis') : '—'} /></SelectTrigger>
      <SelectContent>
        {list.length === 0 && <div className="px-2 py-1.5 text-xs text-muted-foreground">{t('requests.form.noOptions')}</div>}
        {list.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}
      </SelectContent>
    </Select>
  );
}

/** Та же подпись, что бэкенд пишет в таблицу данных
 *  (`budget_line_refs.label_for`): форма и таблица должны читаться одинаково. */
function budgetLineLabel(line: BudgetLineFlat): string {
  return `${line.administrator_name} — ${line.program_name} (${line.period_year}, ${line.currency})`;
}

function BudgetLineRefControl({ field, value, setValue, readOnly, idPrefix }: CtrlProps) {
  const { t } = useTranslation();
  const lines = useBudgetLines();
  const all = useMemo(() => lines.data ?? [], [lines.data]);
  const selectedId = typeof value === 'number' ? value : null;
  const selected = all.find((line) => line.id === selectedId);
  // Администратор — производная от выбранной строки (в значении его нет).
  // Пока строка не выбрана, каскад держится на локальном состоянии.
  const [pickedAdmin, setPickedAdmin] = useState('');
  const adminId = selected ? String(selected.administrator_id) : pickedAdmin;
  // Тот же фильтр, что в форме заявки на подотчётные средства: заявка
  // оформляется только по действующему бюджету (бэкенд проверит то же).
  const active = useMemo(() => all.filter((line) => line.budget_status === 'active'), [all]);
  const administrators = useMemo(() => {
    const seen = new Map<number, string>();
    active.forEach((line) => seen.set(line.administrator_id, line.administrator_name));
    return [...seen].map(([id, label]) => ({ id, label }));
  }, [active]);
  const programLines = useMemo(() => {
    const rows = active.filter((line) => String(line.administrator_id) === adminId);
    // Черновик мог ссылаться на строку уже закрытого бюджета — показать её,
    // чтобы человек увидел, что выбрано, и смог заменить.
    if (selected && !rows.some((line) => line.id === selected.id)) rows.unshift(selected);
    return rows;
  }, [active, adminId, selected]);

  if (readOnly) {
    return (
      <div className="text-sm">
        {selected ? budgetLineLabel(selected) : selectedId != null ? `#${selectedId}` : '—'}
      </div>
    );
  }
  if (lines.isError) {
    return <p className="text-xs text-muted-foreground">{t('requests.form.budgetLinesUnavailable')}</p>;
  }
  if (!lines.isLoading && active.length === 0 && !selected) {
    return <p className="text-xs text-muted-foreground">{t('requests.form.noBudgetLines')}</p>;
  }
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      <Select value={adminId} onValueChange={(v) => { setPickedAdmin(v); setValue(null); }}>
        <SelectTrigger id={domId(idPrefix, field.key)} aria-label={t('requests.form.budgetAdministrator')}>
          <SelectValue placeholder={lines.isLoading ? t('signoff.loadingEllipsis') : t('requests.form.pickAdministrator')} />
        </SelectTrigger>
        <SelectContent>
          {administrators.map((a) => <SelectItem key={a.id} value={String(a.id)}>{a.label}</SelectItem>)}
        </SelectContent>
      </Select>
      <Select value={selectedId != null ? String(selectedId) : ''} onValueChange={(v) => setValue(v ? Number(v) : null)} disabled={!adminId}>
        <SelectTrigger aria-label={t('requests.form.budgetProgram')}>
          <SelectValue placeholder={adminId ? '—' : t('requests.form.pickAdministratorFirst')} />
        </SelectTrigger>
        <SelectContent>
          {programLines.length === 0 && <div className="px-2 py-1.5 text-xs text-muted-foreground">{t('requests.form.noBudgetProgramsForAdmin')}</div>}
          {programLines.map((line) => (
            <SelectItem key={line.id} value={String(line.id)}>{line.program_name} — {line.period_year}, {line.currency}</SelectItem>
          ))}
        </SelectContent>
      </Select>
      {/* Администратор выбран, программа — нет: значения у поля ещё НЕТ.
          Самое частое место, где это застаёт врасплох: первый список
          заполнен, и форма выглядит заполненной. */}
      {adminId && selectedId == null && (
        <p className="text-xs text-muted-foreground sm:col-span-2">
          {t('requests.form.pickBudgetProgram')}
        </p>
      )}
    </div>
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

function GroupControl({ field, value, setValue, readOnly, idPrefix }: CtrlProps) {
  const { t } = useTranslation();
  const f = field as any;
  const children: FormField[] = f.fields ?? [];

  // Блок (repeatable: false) — одна запись, значение-объект, без «+»/«−»:
  // «Поставщик», «Счёт на оплату» — не список, а карточка из нескольких
  // полей. Значение хранится объектом, а не списком из одного элемента,
  // чтобы серверу и таблице данных не приходилось гадать, что это.
  if (f.repeatable === false) {
    const obj = (value && typeof value === 'object' && !Array.isArray(value)
      ? value : {}) as Record<string, unknown>;
    return (
      <div className="rounded-lg border bg-muted/20 p-3 space-y-3">
        {children.map((c) => (
          <FieldRow
            key={c.key}
            field={c}
            value={obj[c.key]}
            setValue={(v) => setValue({ ...obj, [c.key]: v })}
            readOnly={readOnly}
            values={obj}
            idPrefix={domId(idPrefix, field.key).slice('field-'.length)}
          />
        ))}
      </div>
    );
  }

  const rows: Record<string, unknown>[] = Array.isArray(value) ? (value as any) : [];

  const setRows = (next: Record<string, unknown>[]) => setValue(next);
  const addRow = () => setRows([...rows, {}]);
  const copyRow = (i: number) => setRows([...rows.slice(0, i + 1), { ...rows[i] }, ...rows.slice(i + 1)]);
  const delRow = (i: number) => setRows(rows.filter((_, idx) => idx !== i));
  const patchRow = (i: number, key: string, v: unknown) =>
    setRows(rows.map((r, idx) => (idx === i ? { ...r, [key]: v } : r)));

  return (
    <div className="space-y-3">
      {rows.length === 0 && <p className="text-xs text-muted-foreground">{t('requests.form.noRows')}</p>}
      {rows.map((row, i) => (
        <div key={i} className="rounded-lg border bg-muted/20 p-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-xs font-medium text-muted-foreground">{field.label} #{i + 1}</span>
            {!readOnly && (
              <div className="flex items-center gap-2">
                <button type="button" onClick={() => copyRow(i)} className="flex items-center gap-1 text-xs text-primary" aria-label={t('requests.form.copyRow')}><Copy className="h-3.5 w-3.5" /> {t('requests.form.copyRow')}</button>
                <button type="button" onClick={() => delRow(i)} className="flex items-center gap-1 text-xs text-destructive" aria-label={t('common.delete')}><Trash2 className="h-3.5 w-3.5" /> {t('common.delete')}</button>
              </div>
            )}
          </div>
          <div className="space-y-3">
            {children.map((c) => (
              <FieldRow key={c.key} field={c} value={row[c.key]} setValue={(v) => patchRow(i, c.key, v)} readOnly={readOnly} values={row} idPrefix={`${domId(idPrefix, field.key).slice('field-'.length)}-${i}`} />
            ))}
          </div>
        </div>
      ))}
      {!readOnly && (
        <Button type="button" variant="outline" size="sm" onClick={addRow}>
          <Plus className="mr-1 h-4 w-4" /> {t('requests.form.addRow')}
        </Button>
      )}
    </div>
  );
}

/**
 * Сравнительная таблица поставщиков.
 *
 * Строки — позиции заявки (из `items_field`), колонки — поставщики. В
 * клетке цена ЗА ЕДИНИЦУ: так подписана колонка и так считает сервер
 * (`quotes.derive`), поэтому здесь показывается ИМЕННО она, а итог — снизу
 * и только чтением: два места, где можно ввести сумму, рано или поздно
 * разойдутся, а утверждают деньги по одному.
 *
 * Итоги в подвале берутся из `totals`, посчитанных сервером; пока значение
 * не сохранено, их ещё нет — там прочерк, а не самодельная арифметика,
 * которая могла бы разойтись с серверной.
 */
function SupplierQuotesControl({ field, value, setValue, readOnly, values }: CtrlProps) {
  const f = field as unknown as { items_field: string; quantity_key?: string; currency?: string };
  const table = (value && typeof value === 'object' && !Array.isArray(value)
    ? value : {}) as SupplierQuotesValue;
  const suppliers: SupplierQuote[] = table.suppliers ?? [];
  const rows = Array.isArray(values?.[f.items_field])
    ? (values[f.items_field] as Record<string, unknown>[]) : [];

  const patch = (next: Partial<SupplierQuotesValue>) => setValue({ ...table, ...next });
  const setSupplier = (i: number, s: SupplierQuote) =>
    patch({ suppliers: suppliers.map((x, idx) => (idx === i ? s : x)) });
  const addSupplier = () => patch({ suppliers: [...suppliers, { name: '', prices: [] }] });
  const delSupplier = (i: number) => patch({
    suppliers: suppliers.filter((_, idx) => idx !== i),
    // Выбранный сдвигается вместе со списком, иначе «выбран» окажется
    // другой поставщик, чем был.
    chosen: table.chosen == null ? table.chosen
      : table.chosen === i ? null : table.chosen > i ? table.chosen - 1 : table.chosen,
  });
  const setPrice = (i: number, row: number, raw: string) => {
    const prices = [...(suppliers[i].prices ?? [])];
    while (prices.length < rows.length) prices.push(null);
    prices[row] = raw === '' ? null : raw;
    setSupplier(i, { ...suppliers[i], prices });
  };

  if (rows.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        Сначала заполните позиции — строки таблицы берутся из них.
      </p>
    );
  }

  const rowLabel = (row: Record<string, unknown>, i: number) => {
    const first = Object.values(row).find((v) => typeof v === 'string' && v.trim());
    const qty = f.quantity_key ? row[f.quantity_key] : undefined;
    return `${first ?? `Позиция ${i + 1}`}${qty != null && qty !== '' ? ` × ${qty}` : ''}`;
  };

  return (
    <div className="space-y-2">
      {/* Таблица шире экрана на телефоне — прокручиваем её, а не страницу. */}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[32rem] border-separate border-spacing-0 text-sm">
          <thead>
            <tr>
              <th className="sticky left-0 z-10 bg-background border-b p-2 text-left font-medium">
                Позиция
              </th>
              {suppliers.map((s, i) => (
                <th key={i} className="border-b p-2 text-left font-medium align-top">
                  <div className="flex items-start gap-1">
                    <Input
                      aria-label={`Поставщик ${i + 1}`}
                      value={s.name ?? ''}
                      disabled={readOnly}
                      placeholder="Поставщик"
                      onChange={(e) => setSupplier(i, { ...s, name: e.target.value })}
                      className="h-8 min-w-[9rem]"
                    />
                    {!readOnly && (
                      <button
                        type="button"
                        onClick={() => delSupplier(i)}
                        aria-label={`Убрать поставщика ${i + 1}`}
                        className="mt-1 text-destructive"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    )}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, r) => (
              <tr key={r}>
                <td className="sticky left-0 z-10 bg-background border-b p-2 text-muted-foreground">
                  {rowLabel(row, r)}
                </td>
                {suppliers.map((s, i) => (
                  <td key={i} className="border-b p-2">
                    <Input
                      type="number"
                      aria-label={`Цена за единицу, ${s.name || `поставщик ${i + 1}`}, ${rowLabel(row, r)}`}
                      value={(s.prices ?? [])[r] == null ? '' : String((s.prices ?? [])[r])}
                      disabled={readOnly}
                      onChange={(e) => setPrice(i, r, e.target.value)}
                      className="h-8 min-w-[7rem]"
                    />
                  </td>
                ))}
              </tr>
            ))}
            <tr>
              <td className="sticky left-0 z-10 bg-background p-2 font-medium">Итого</td>
              {suppliers.map((s, i) => (
                <td key={i} className="p-2">
                  <label className="flex items-center gap-2">
                    <input
                      type="radio"
                      name={`chosen-${field.key}`}
                      checked={table.chosen === i}
                      disabled={readOnly}
                      onChange={() => patch({ chosen: i })}
                      aria-label={`Выбрать ${s.name || `поставщика ${i + 1}`}`}
                    />
                    <span className="font-medium">
                      {(table.totals ?? [])[i] ?? '—'}
                    </span>
                  </label>
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>

      {!readOnly && suppliers.length < 10 && (
        <Button type="button" variant="outline" size="sm" onClick={addSupplier}>
          <Plus className="mr-1 h-4 w-4" /> Поставщик
        </Button>
      )}
      <p className="text-xs text-muted-foreground">
        Цена — за единицу. Итог по выбранному поставщику считает сервер при
        сохранении; отметьте его радиокнопкой.
      </p>
    </div>
  );
}

function ScalarControl({ field, value, setValue, readOnly, idPrefix }: CtrlProps) {
  const { t } = useTranslation();
  const inputId = domId(idPrefix, field.key);
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
      // Одна ветка — и маска появляется во ВСЕХ формах заявок, какие бы
      // администраторы ни собрали в конструкторе.
      return <DateInput id={inputId} disabled={readOnly} value={typeof value === 'string' ? value : ''} onChange={(next) => setValue(next || null)} />;
    case 'checkbox':
      return <Checkbox id={inputId} disabled={readOnly} checked={Boolean(value)} onCheckedChange={(c) => setValue(Boolean(c))} />;
    case 'serial':
      return <Input id={inputId} disabled value={typeof value === 'string' ? value : t('requests.form.autoGenerated')} />;
    case 'file':
      return readOnly
        ? <div className="text-sm text-muted-foreground">{Array.isArray(value) ? (value as string[]).join(', ') : (value ? String(value) : '—')}</div>
        : <Input id={inputId} type="file" multiple onChange={(e) => setValue(Array.from(e.target.files ?? []).map((x) => x.name))} />;
    case 'formula':
      return <Input id={inputId} disabled value={value == null ? t('requests.form.computed') : String(value)} />;
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

function FieldRow({ field, value, setValue, readOnly, values, idPrefix }: CtrlProps) {
  // static text: no label / no input, just the content
  if (field.type === 'static_text') {
    return <p className="text-sm font-medium text-foreground">{(field as any).content}</p>;
  }
  const showLabelMark = field.type !== 'checkbox';
  const control =
    field.type === 'reference' ? <ReferenceControl field={field} value={value} setValue={setValue} readOnly={readOnly} values={values} idPrefix={idPrefix} />
    : field.type === 'budget_line_ref' ? <BudgetLineRefControl field={field} value={value} setValue={setValue} readOnly={readOnly} values={values} idPrefix={idPrefix} />
    : field.type === 'amount' ? <AmountControl field={field} value={value} setValue={setValue} readOnly={readOnly} values={values} idPrefix={idPrefix} />
    : field.type === 'group' ? <GroupControl field={field} value={value} setValue={setValue} readOnly={readOnly} values={values} idPrefix={idPrefix} />
    : field.type === 'supplier_quotes' ? <SupplierQuotesControl field={field} value={value} setValue={setValue} readOnly={readOnly} values={values} idPrefix={idPrefix} />
    : <ScalarControl field={field} value={value} setValue={setValue} readOnly={readOnly} values={values} idPrefix={idPrefix} />;

  return (
    <div className="space-y-1.5">
      <Label htmlFor={domId(idPrefix, field.key)} className="text-sm">
        {field.label}
        {showLabelMark && field.required ? <span className="ml-1 text-destructive">*</span> : null}
      </Label>
      {control}
    </div>
  );
}

export function FormRenderer({ schema, values, onChange, readOnly = false }: Props) {
  const { t } = useTranslation();
  if (schema.fields.length === 0) {
    return <p className="text-sm text-muted-foreground">{t('requests.form.empty')}</p>;
  }
  const dcs = schema.display_conditions ?? [];
  return (
    <div className="space-y-4">
      {schema.fields
        .filter((field) => isVisible(field.key, values, dcs))
        // Поля согласующего (`filled_by: approver`) в РЕДАКТИРУЕМОЙ форме
        // не показываем: их заполняет не инициатор, а закупщик на своём
        // шаге — на карточке согласования, отдельной панелью. В режиме
        // чтения показываем: CFO и инициатор должны видеть, что вписано.
        .filter((field) => readOnly || field.filled_by !== 'approver')
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
