/**
 * Вкладка «Поля» настроек доски (Trello «Настраиваемые поля», решение K-35,
 * этап S3): поля доски отдела или проекта — текст, число, дата, флажок,
 * список с цветными вариантами; «показывать на карточке». Каждое действие
 * сохраняется сразу, как в Trello. Тип после создания не меняется.
 */
import { useState } from 'react';
import type { TFunction } from 'i18next';
import { ArrowDown, ArrowUp, Pencil, Plus, Trash2, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { Switch } from '@/components/ui/switch';
import { cn } from '@/lib/utils';
import type { BoardFieldDef, BoardFieldType } from '@/types/tasks';

import type { OptionDraft } from '../api';
import { chipStyle, swatchStyle } from '../boardColors';
import { FIELD_TYPE_ICON, FIELD_TYPES, fieldTypeLabel } from '../fields/fieldFormat';
import { useBoardFieldDefs, useFieldActions } from '../hooks/useBoardFields';
import { BOARD_COLORS, type BoardColor, type SharedBoardKey } from '../types';

/** Пределы сервера: полей на доске и вариантов в списке. */
const FIELD_LIMIT = 50;
const OPTION_LIMIT = 50;

interface Draft {
  name: string;
  type: BoardFieldType;
  options: OptionDraft[];
  show_on_card: boolean;
}

function OptionColor({ color, onChange }: { color: BoardColor | null; onChange: (color: BoardColor | null) => void }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const pick = (next: BoardColor | null) => { onChange(next); setOpen(false); };
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button type="button" aria-label={t('tasks.fields.optionColor', 'Цвет варианта')}
          className="h-9 w-9 shrink-0 rounded-md border" style={color ? swatchStyle(color) : undefined} />
      </PopoverTrigger>
      <PopoverContent align="start" className="w-56 p-2">
        <div className="grid grid-cols-5 gap-1.5">
          {BOARD_COLORS.map((item) => (
            <button key={item} type="button" aria-label={t(`tasks.board.colors.${item}`, item)}
              aria-pressed={color === item}
              className={cn('h-7 rounded ring-offset-2 ring-offset-background', color === item && 'ring-2 ring-foreground')}
              style={swatchStyle(item)} onClick={() => pick(item)} />
          ))}
        </div>
        <button type="button" onClick={() => pick(null)}
          className="mt-2 w-full rounded border px-2 py-1 text-xs text-muted-foreground hover:bg-muted">
          {t('tasks.board.column.noColor', 'Без цвета')}
        </button>
      </PopoverContent>
    </Popover>
  );
}

/** Ошибка формы до отправки — сервер ответил бы тем же, но дороже. */
function draftProblem(draft: Draft, t: TFunction): string | null {
  if (!draft.name.trim()) return t('tasks.fields.nameRequired', 'Назовите поле');
  if (draft.type !== 'list') return null;
  const names = draft.options.map((option) => option.name.trim().toLowerCase());
  if (names.some((name) => !name)) return t('tasks.fields.optionRequired', 'У каждого варианта должно быть название');
  if (new Set(names).size !== names.length) return t('tasks.fields.optionDuplicate', 'Варианты списка не должны повторяться');
  return null;
}

function FieldForm({ initial, pending, onSubmit, onCancel }: {
  initial?: BoardFieldDef;
  pending: boolean;
  onSubmit: (draft: Draft) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState<Draft>(() => ({
    name: initial?.name ?? '',
    type: initial?.type ?? 'text',
    options: initial?.options.map((option) => ({
      id: option.id, name: option.name, color: option.color as BoardColor | null,
    })) ?? [],
    show_on_card: initial?.show_on_card ?? false,
  }));
  const problem = draftProblem(draft, t);
  // Ошибку формы показываем после попытки сохранить, а не на первой букве.
  const [tried, setTried] = useState(false);
  // Новый вариант сразу принимает ввод.
  const [focusOption, setFocusOption] = useState<number | null>(null);
  const setOption = (index: number, change: Partial<OptionDraft>) => setDraft((current) => ({
    ...current,
    options: current.options.map((option, at) => (at === index ? { ...option, ...change } : option)),
  }));
  const submit = () => {
    setTried(true);
    if (problem) return;
    onSubmit({ ...draft, name: draft.name.trim(),
      options: draft.options.map((option) => ({ ...option, name: option.name.trim() })) });
  };

  return (
    <div className="space-y-3 rounded-lg border bg-muted/30 p-3">
      <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_11rem]">
        <Input autoFocus value={draft.name} maxLength={100}
          aria-label={t('tasks.fields.name', 'Название поля')}
          placeholder={t('tasks.fields.namePlaceholder', 'Например, «Причина ожидания»')}
          onChange={(event) => setDraft({ ...draft, name: event.target.value })} />
        {initial ? (
          <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
            {fieldTypeLabel(draft.type, t)}
            <span className="text-xs">({t('tasks.fields.typeFixed', 'тип не меняется')})</span>
          </p>
        ) : (
          <Select value={draft.type}
            onValueChange={(type) => setDraft({ ...draft, type: type as BoardFieldType })}>
            <SelectTrigger aria-label={t('tasks.fields.type.label', 'Тип поля')}><SelectValue /></SelectTrigger>
            <SelectContent>
              {FIELD_TYPES.map((type) => {
                const Icon = FIELD_TYPE_ICON[type];
                return (
                  <SelectItem key={type} value={type}>
                    <span className="inline-flex items-center gap-2"><Icon className="h-4 w-4" />
                      {fieldTypeLabel(type, t)}</span>
                  </SelectItem>
                );
              })}
            </SelectContent>
          </Select>
        )}
      </div>

      {draft.type === 'list' && (
        <div className="space-y-1.5">
          <p className="text-xs font-medium text-muted-foreground">{t('tasks.fields.options', 'Варианты')}</p>
          {draft.options.length === 0 && (
            <p className="text-xs text-muted-foreground">
              {t('tasks.fields.optionsEmpty', 'Добавьте варианты, из которых будут выбирать в карточке.')}
            </p>
          )}
          {draft.options.map((option, index) => (
            <div key={option.id ?? `new-${index}`} className="flex items-center gap-1.5">
              <OptionColor color={option.color} onChange={(color) => setOption(index, { color })} />
              <Input value={option.name} maxLength={100} autoFocus={index === focusOption}
                aria-label={t('tasks.fields.optionName', 'Вариант {{number}}', { number: index + 1 })}
                onChange={(event) => setOption(index, { name: event.target.value })} />
              <button type="button"
                aria-label={t('tasks.fields.optionRemove', 'Убрать вариант {{number}}', { number: index + 1 })}
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-muted"
                onClick={() => setDraft((current) => ({
                  ...current, options: current.options.filter((_item, at) => at !== index),
                }))}>
                <X className="h-4 w-4" />
              </button>
            </div>
          ))}
          {initial && draft.options.length < initial.options.length && (
            <p className="text-xs text-muted-foreground">
              {t('tasks.fields.optionRemovedHint', 'У задач с убранным вариантом значение очистится.')}
            </p>
          )}
          <Button type="button" variant="ghost" size="sm" disabled={draft.options.length >= OPTION_LIMIT}
            onClick={() => {
              setFocusOption(draft.options.length);
              setDraft((current) => ({
                ...current, options: [...current.options, { name: '', color: null }],
              }));
            }}>
            <Plus className="mr-1.5 h-4 w-4" />{t('tasks.fields.optionAdd', 'Вариант')}
          </Button>
        </div>
      )}

      <label className="flex items-center gap-2 text-sm">
        <Switch checked={draft.show_on_card}
          onCheckedChange={(show_on_card) => setDraft({ ...draft, show_on_card })} />
        {t('tasks.fields.showOnCard', 'Показывать на карточке')}
      </label>

      {tried && problem && <p role="alert" className="text-xs text-destructive">{problem}</p>}
      <div className="flex gap-2">
        <Button size="sm" disabled={pending} onClick={submit}>
          {initial ? t('tasks.fields.save', 'Сохранить') : t('tasks.fields.create', 'Создать')}
        </Button>
        <Button size="sm" variant="outline" onClick={onCancel}>{t('tasks.board.cancel', 'Отмена')}</Button>
      </div>
    </div>
  );
}

export function FieldsTab({ boardKey }: { boardKey: SharedBoardKey }) {
  const { t } = useTranslation();
  const { data: fields, isLoading } = useBoardFieldDefs(boardKey);
  const actions = useFieldActions(boardKey);
  const [editing, setEditing] = useState<number | 'new' | null>(null);
  const [deleting, setDeleting] = useState<number | null>(null);
  const list = fields ?? [];

  const move = (index: number, step: -1 | 1) => {
    const target = index + step;
    if (target < 0 || target >= list.length) return;
    // Вверх — между соседом выше него и ним; вниз — между соседом ниже и следующим.
    const before = step === -1 ? list[target - 1] ?? null : list[target];
    const after = step === -1 ? list[target] : list[target + 1] ?? null;
    actions.update.mutate({ id: list[index].id, before_id: before?.id ?? null, after_id: after?.id ?? null });
  };

  if (isLoading) return <Skeleton className="h-24 w-full" />;
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        {t('tasks.fields.hint', 'Поля появляются в окне каждой задачи этой доски. Задачи вложенных отделов берут поля своих досок.')}
      </p>
      {list.length === 0 && editing !== 'new' && (
        <p className="rounded-lg border border-dashed p-4 text-center text-sm text-muted-foreground">
          {t('tasks.fields.empty', 'Полей пока нет — например, «Причина ожидания» или «Этап».')}
        </p>
      )}
      <ul className="space-y-2">
        {list.map((field, index) => {
          const Icon = FIELD_TYPE_ICON[field.type];
          if (editing === field.id) {
            return (
              <li key={field.id}>
                <FieldForm initial={field} pending={actions.update.isPending}
                  onCancel={() => setEditing(null)}
                  onSubmit={(draft) => actions.update.mutate({
                    id: field.id, name: draft.name, show_on_card: draft.show_on_card,
                    ...(field.type === 'list' ? { options: draft.options } : {}),
                  }, { onSuccess: () => setEditing(null) })} />
              </li>
            );
          }
          return (
            <li key={field.id} className="rounded-lg border p-2" data-testid={`board-field-${field.id}`}>
              <div className="flex flex-wrap items-center gap-2">
                <Icon className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
                <span className="min-w-0 flex-1 truncate text-sm font-medium">{field.name}</span>
                <span className="text-xs text-muted-foreground">{fieldTypeLabel(field.type, t)}</span>
                <label className="flex items-center gap-1.5 text-xs">
                  <Switch checked={field.show_on_card}
                    aria-label={t('tasks.fields.showOnCardOf', 'Показывать «{{name}}» на карточке', { name: field.name })}
                    onCheckedChange={(show_on_card) => actions.update.mutate({ id: field.id, show_on_card })} />
                  {t('tasks.fields.onCard', 'На карточке')}
                </label>
                <Button variant="ghost" size="icon" className="h-8 w-8" disabled={index === 0}
                  aria-label={t('tasks.fields.up', 'Выше')} onClick={() => move(index, -1)}>
                  <ArrowUp className="h-4 w-4" /></Button>
                <Button variant="ghost" size="icon" className="h-8 w-8" disabled={index === list.length - 1}
                  aria-label={t('tasks.fields.down', 'Ниже')} onClick={() => move(index, 1)}>
                  <ArrowDown className="h-4 w-4" /></Button>
                <Button variant="ghost" size="icon" className="h-8 w-8"
                  aria-label={t('tasks.fields.edit', 'Изменить «{{name}}»', { name: field.name })}
                  onClick={() => { setEditing(field.id); setDeleting(null); }}>
                  <Pencil className="h-4 w-4" /></Button>
                <Button variant="ghost" size="icon" className="h-8 w-8"
                  aria-label={t('tasks.fields.delete', 'Удалить «{{name}}»', { name: field.name })}
                  onClick={() => setDeleting(field.id)}>
                  <Trash2 className="h-4 w-4" /></Button>
              </div>
              {field.type === 'list' && field.options.length > 0 && (
                <div className="mt-1.5 flex flex-wrap gap-1 pl-6">
                  {field.options.map((option) => (
                    <span key={option.id} className={cn('rounded px-1.5 py-0.5 text-xs', !option.color && 'bg-muted')}
                      style={chipStyle(option.color as BoardColor | null)}>{option.name}</span>
                  ))}
                </div>
              )}
              {deleting === field.id && (
                <div role="alert" className="mt-2 flex flex-wrap items-center gap-2 rounded-md bg-destructive/10 p-2 text-sm">
                  <span className="flex-1">
                    {t('tasks.fields.deleteConfirm', 'Удалить поле «{{name}}»? Его значения у всех задач доски тоже удалятся.',
                      { name: field.name })}
                  </span>
                  <Button size="sm" variant="destructive" disabled={actions.remove.isPending}
                    onClick={() => actions.remove.mutate(field.id, { onSuccess: () => setDeleting(null) })}>
                    {t('tasks.fields.deleteYes', 'Удалить')}
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => setDeleting(null)}>
                    {t('tasks.board.cancel', 'Отмена')}
                  </Button>
                </div>
              )}
            </li>
          );
        })}
      </ul>
      {editing === 'new' ? (
        <FieldForm pending={actions.create.isPending} onCancel={() => setEditing(null)}
          onSubmit={(draft) => actions.create.mutate({
            name: draft.name, type: draft.type, show_on_card: draft.show_on_card,
            options: draft.type === 'list' ? draft.options : [],
          }, { onSuccess: () => setEditing(null) })} />
      ) : (
        <Button variant="outline" size="sm" disabled={list.length >= FIELD_LIMIT}
          onClick={() => { setEditing('new'); setDeleting(null); }}>
          <Plus className="mr-1.5 h-4 w-4" />{t('tasks.fields.new', 'Новое поле')}
        </Button>
      )}
    </div>
  );
}
