/**
 * «Поля доски» в окне карточки (Trello «Настраиваемые поля», этап S3): поля
 * домашних досок задачи — отдела и проекта. Значение правит тот, кто ведёт
 * задачу (`soft_edit`); текст и число сохраняются по Enter или уходу из
 * поля, Esc возвращает прежнее; флажок, дата и список — сразу.
 */
import { useEffect, useRef, useState } from 'react';
import { ChevronDown, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Checkbox } from '@/components/ui/checkbox';
import { DateInput } from '@/components/ui/date-input';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import type { Task, TaskBoardField } from '@/types/tasks';

import { chipStyle, swatchStyle } from '../boardColors';
import { FIELD_TYPE_ICON } from '../fields/fieldFormat';
import type { BoardColor } from '../types';
import { useFieldValue } from './hooks';

type Save = (value: string | boolean | null) => void;

/** Число как его примет сервер: пробелы — разряды, запятая — дробная часть. */
const NUMBER_RE = /^-?\d+([.,]\d+)?$/;

function TextValue({ field, disabled, onSave, numeric }: {
  field: TaskBoardField; disabled: boolean; onSave: Save; numeric?: boolean;
}) {
  const { t } = useTranslation();
  const current = typeof field.value === 'string' ? field.value : '';
  const [draft, setDraft] = useState(current);
  // Enter и уход из поля сразу за ним — одна отправка, а не две.
  const sent = useRef<string | null>(null);
  useEffect(() => setDraft(current), [current]);
  // `\s` в JS ловит и неразрывный пробел — разделитель разрядов.
  const compact = draft.replace(/\s/g, '');
  const invalid = Boolean(numeric && compact && !NUMBER_RE.test(compact));

  const commit = () => {
    const next = draft.trim();
    if (invalid || next === current || next === sent.current) return;
    sent.current = next;
    onSave(next || null);
  };
  return (
    <div className="space-y-1">
      <Input value={draft} disabled={disabled} maxLength={numeric ? 40 : 500}
        inputMode={numeric ? 'decimal' : undefined}
        aria-label={field.name} aria-invalid={invalid || undefined}
        placeholder={disabled ? '—' : t('tasks.fields.placeholder', 'Добавить значение…')}
        onChange={(event) => { sent.current = null; setDraft(event.target.value); }}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === 'Enter') { event.preventDefault(); commit(); }
          if (event.key === 'Escape') setDraft(current);
        }} />
      {invalid && (
        <p role="alert" className="text-xs text-destructive">
          {t('tasks.fields.notNumber', 'Введите число, например 1250,5')}
        </p>
      )}
    </div>
  );
}

function DateValue({ field, disabled, onSave }: { field: TaskBoardField; disabled: boolean; onSave: Save }) {
  const { t } = useTranslation();
  const current = typeof field.value === 'string' ? field.value : '';
  const [draft, setDraft] = useState(current);
  const [invalid, setInvalid] = useState(false);
  useEffect(() => setDraft(current), [current]);
  return (
    <div className="flex items-center gap-1">
      <div className="min-w-0 flex-1">
        <DateInput value={draft} disabled={disabled} aria-label={field.name} invalid={invalid}
          onValidityChange={setInvalid}
          onChange={(iso) => {
            setDraft(iso);
            if (iso && iso !== current) onSave(iso);
          }} />
      </div>
      {current && !disabled && (
        <button type="button" onClick={() => onSave(null)}
          aria-label={t('tasks.fields.clear', 'Очистить «{{name}}»', { name: field.name })}
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-muted">
          <X className="h-4 w-4" />
        </button>
      )}
    </div>
  );
}

function ListValue({ field, disabled, onSave }: { field: TaskBoardField; disabled: boolean; onSave: Save }) {
  const { t } = useTranslation();
  const chosen = field.options.find((option) => option.id === field.value) ?? null;
  const empty = field.options.length === 0;
  return (
    <div className="space-y-1">
      <DropdownMenu>
        <DropdownMenuTrigger asChild disabled={disabled || empty}>
          <button type="button" disabled={disabled || empty} aria-label={field.name}
            className="flex h-9 w-full items-center gap-2 rounded-md border bg-background px-3 text-left text-sm disabled:cursor-default disabled:opacity-70">
            {chosen ? (
              <span className={cn('truncate rounded px-2 py-0.5 text-xs font-medium',
                !chosen.color && 'bg-muted')}
                style={chipStyle(chosen.color as BoardColor | null)}>
                {chosen.name}
              </span>
            ) : <span className="text-muted-foreground">{disabled ? '—' : t('tasks.fields.choose', 'Выбрать…')}</span>}
            <ChevronDown className="ml-auto h-4 w-4 shrink-0 text-muted-foreground" />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="min-w-[12rem]">
          {field.options.map((option) => (
            <DropdownMenuItem key={option.id} onSelect={() => onSave(option.id)}>
              <span className="mr-2 h-3 w-3 shrink-0 rounded-sm border"
                style={option.color ? swatchStyle(option.color as BoardColor) : undefined} />
              {option.name}
            </DropdownMenuItem>
          ))}
          {chosen && (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={() => onSave(null)}>
                {t('tasks.fields.clearValue', 'Очистить')}
              </DropdownMenuItem>
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
      {empty && (
        <p className="text-xs text-muted-foreground">
          {t('tasks.fields.noOptions', 'В списке нет вариантов — их добавляет администратор доски в её настройках.')}
        </p>
      )}
    </div>
  );
}

function FieldValue({ field, disabled, onSave }: { field: TaskBoardField; disabled: boolean; onSave: Save }) {
  const Icon = FIELD_TYPE_ICON[field.type];
  if (field.type === 'checkbox') {
    return (
      <label className="flex h-9 items-center gap-2 text-sm">
        <Checkbox checked={field.value === true} disabled={disabled}
          onCheckedChange={(checked) => onSave(checked === true)} />
        <Icon className="h-4 w-4 text-muted-foreground" />
        {field.name}
      </label>
    );
  }
  return (
    <div className="space-y-1">
      <p className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
        <Icon className="h-3.5 w-3.5" />{field.name}
      </p>
      {field.type === 'date' && <DateValue field={field} disabled={disabled} onSave={onSave} />}
      {field.type === 'list' && <ListValue field={field} disabled={disabled} onSave={onSave} />}
      {(field.type === 'text' || field.type === 'number') && (
        <TextValue field={field} disabled={disabled} onSave={onSave} numeric={field.type === 'number'} />
      )}
    </div>
  );
}

export function FieldsBlock({ task, canEdit }: { task: Task; canEdit: boolean }) {
  const { t } = useTranslation();
  const setValue = useFieldValue(task.id);
  const boards = (task.home_boards ?? []).filter((board) => board.fields.length > 0);
  if (boards.length === 0) return null;
  return (
    <>
      {boards.map((board) => (
        <section key={`${board.kind}:${board.id}`} className="space-y-1.5"
          data-testid={`card-fields-${board.kind}-${board.id}`}>
          <h4 className="text-xs font-semibold text-muted-foreground">
            {boards.length > 1 && board.title
              ? t('tasks.fields.blockOf', 'Поля доски «{{name}}»', { name: board.title })
              : t('tasks.fields.block', 'Поля доски')}
          </h4>
          <div className="grid gap-3 sm:grid-cols-2">
            {board.fields.map((field) => (
              <FieldValue key={field.id} field={field} disabled={!canEdit}
                onSave={(value) => setValue.mutate({ fieldId: field.id, value })} />
            ))}
          </div>
        </section>
      ))}
    </>
  );
}
