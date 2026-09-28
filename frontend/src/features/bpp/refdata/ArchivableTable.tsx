/**
 * Таблица архивируемого справочника (страны, валюты, единицы измерения,
 * группы статей, статьи — задача 9, A2.4): добавление и правка, архив
 * вместо удаления (`is_active`), кнопки — по `can_edit` из ответа сервера.
 *
 * Правит только управляющая компания (D-03). Решает это сервер и кладёт
 * ответ в `can_edit` каждой строки — отдельного запроса прав экран не
 * делает. Кнопки видны всем, но у кого `can_edit=false`, они выключены, а
 * над таблицей — объяснение почему: спрятанная кнопка выглядела бы как
 * «функции нет», выключенная с подсказкой — как «не здесь».
 *
 * «Добавить» — по признаку ЛЮБОЙ строки: значение у всех строк одно (одна
 * роль, одна компания на запрос). Пустой список — кнопка выключена: гадать
 * втёмную не стоит, а справочники группы сидятся миграцией и пустыми не
 * бывают.
 *
 * Архивная запись остаётся в списке с меткой «Архив» и кнопкой
 * «Восстановить»: её видят старые документы, а выборы в новых документах
 * читают справочник с `?active=1` (`useActiveRefdata`) и её не предлагают.
 */
import { useRef, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Lock } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { reportApiError } from '@/lib/apiError';

import { useIdempotentAction } from '../core/useIdempotentAction';

import {
  NONE_OPTION, fieldOptions, type RefField, type RefRowBase,
} from './refFields';

type Values = Record<string, string>;

interface Props<R extends RefRowBase> {
  title: string;
  rows: R[] | undefined;
  isLoading: boolean;
  /** Колонки в порядке показа — код первый, затем название и что ещё есть. */
  fields: RefField<R>[];
  onCreate: (values: Values) => Promise<unknown>;
  onPatch: (id: string, values: Values) => Promise<unknown>;
  onToggleActive: (row: R, nextActive: boolean) => Promise<unknown>;
  onChanged: () => void;
  /** Что-то справа от «Добавить», например подсказка. */
  toolbarExtra?: ReactNode;
}

const emptyValues = <R,>(fields: RefField<R>[]): Values =>
  Object.fromEntries(fields.map((f) => [f.key, f.options && f.optional ? NONE_OPTION : '']));

const filled = (value: string | undefined) =>
  value !== undefined && value.trim() !== '' && value !== NONE_OPTION;

const cellText = (value: unknown) =>
  value === null || value === undefined || value === '' ? '—' : String(value);

/** Новое значение поля формы и сброс полей, зависящих от него (`resetOn`). */
const withChange = <R,>(fields: RefField<R>[], values: Values, key: string, value: string) => {
  const next = { ...values, [key]: value };
  for (const f of fields) {
    if (f.resetOn === key && values[key] !== value) next[f.key] = f.optional ? NONE_OPTION : '';
  }
  return next;
};

/** Поле диалога — текстовое или выпадающий список. */
function FieldInput<R>({
  field, id, value, values, onChange,
}: {
  field: RefField<R>; id: string; value: string; values: Values;
  onChange: (value: string) => void;
}) {
  const { t } = useTranslation();
  if (field.options) {
    return (
      <Select value={value || undefined} onValueChange={onChange}>
        <SelectTrigger id={id}>
          <SelectValue placeholder={t('bpp.refdata.choose', 'Выберите')} />
        </SelectTrigger>
        <SelectContent>
          {field.optional && (
            <SelectItem value={NONE_OPTION}>{t('bpp.refdata.none', '— нет —')}</SelectItem>
          )}
          {fieldOptions(field, values).map((option) => (
            <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
          ))}
        </SelectContent>
      </Select>
    );
  }
  return (
    <Input
      id={id}
      value={value}
      maxLength={field.maxLength}
      onChange={(event) => onChange(event.target.value)}
    />
  );
}

export function ArchivableTable<R extends RefRowBase>({
  title, rows, isLoading, fields, onCreate, onPatch, onToggleActive, onChanged, toolbarExtra,
}: Props<R>) {
  const { t } = useTranslation();
  const canEdit = (rows ?? []).some((row) => row.can_edit);
  const editableFields = fields.filter((f) => f.editable !== false);
  const readOnlyNotice = !isLoading && (rows?.length ?? 0) > 0 && !canEdit;

  const [createOpen, setCreateOpen] = useState(false);
  const [createValues, setCreateValues] = useState<Values>(() => emptyValues(fields));

  const [editing, setEditing] = useState<R | null>(null);
  const [editValues, setEditValues] = useState<Values>({});

  // Замок архива — по строке и в ref: два клика в одном такте оба увидели бы
  // пустое состояние, пока React не перерисовал кнопку.
  const togglingRef = useRef(new Set<string>());
  const [toggling, setToggling] = useState<ReadonlySet<string>>(new Set());

  // Защита от двойного нажатия «Сохранить» (ТЗ §05). Ключ идемпотентности
  // ручки справочников не принимают: повтор создания после обрыва сети
  // ответит 422 E-REF-02 «код уже есть» — дубля записи не будет и так.
  const createAction = useIdempotentAction(() => onCreate(createValues));
  const editAction = useIdempotentAction(() =>
    (editing ? onPatch(editing.id, editValues) : Promise.resolve(undefined)));

  const openCreate = () => {
    setCreateValues(emptyValues(fields));
    setCreateOpen(true);
  };

  const submitCreate = async () => {
    try {
      await createAction.run();
      setCreateOpen(false);
      onChanged();
    } catch (error) {
      reportApiError(error, t('bpp.refdata.createFailed', 'Не удалось добавить запись'));
    }
  };

  const openEdit = (row: R) => {
    setEditing(row);
    setEditValues(Object.fromEntries(
      editableFields.map((f) => [f.key, String((row as Record<string, unknown>)[f.key] ?? '')]),
    ));
  };

  const submitEdit = async () => {
    try {
      await editAction.run();
      setEditing(null);
      onChanged();
    } catch (error) {
      reportApiError(error, t('bpp.refdata.saveFailed', 'Не удалось сохранить изменения'));
    }
  };

  const setToggle = (id: string, on: boolean) => {
    if (on) togglingRef.current.add(id);
    else togglingRef.current.delete(id);
    setToggling(new Set(togglingRef.current));
  };

  const toggle = async (row: R) => {
    if (togglingRef.current.has(row.id)) return;
    setToggle(row.id, true);
    try {
      await onToggleActive(row, row.is_active === false);
      onChanged();
    } catch (error) {
      reportApiError(error, t('bpp.refdata.saveFailed', 'Не удалось сохранить изменения'));
    } finally {
      setToggle(row.id, false);
    }
  };

  const createReady = fields.every((f) => f.optional || filled(createValues[f.key]));
  const editReady = editableFields.every((f) => f.optional || filled(editValues[f.key]));
  const colSpan = fields.length + 2;

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-base font-semibold">{title}</h3>
        <div className="flex items-center gap-2">
          {toolbarExtra}
          <Button size="sm" onClick={openCreate} disabled={!canEdit}>
            {t('bpp.refdata.add', 'Добавить')}
          </Button>
        </div>
      </div>

      {readOnlyNotice && (
        <p className="flex items-center gap-2 text-sm text-muted-foreground" role="note">
          <Lock className="h-4 w-4 shrink-0" />
          {t(
            'bpp.refdata.readOnly',
            'Справочники ведёт управляющая компания: здесь — только просмотр. Изменить запись можно на её поддомене.',
          )}
        </p>
      )}

      <div className="overflow-x-auto rounded-lg border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              {fields.map((f) => <TableHead key={f.key}>{f.label}</TableHead>)}
              <TableHead>{t('bpp.refdata.status', 'Статус')}</TableHead>
              <TableHead className="w-40">
                <span className="sr-only">{t('bpp.refdata.actions', 'Действия')}</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow>
                <TableCell colSpan={colSpan}><Skeleton className="h-6 w-full" /></TableCell>
              </TableRow>
            ) : !rows || rows.length === 0 ? (
              <TableRow>
                <TableCell colSpan={colSpan} className="py-6 text-center text-muted-foreground">
                  {t('bpp.refdata.empty', 'Справочник пуст')}
                </TableCell>
              </TableRow>
            ) : (
              rows.map((row) => {
                const archived = row.is_active === false;
                return (
                  <TableRow key={row.id} className={archived ? 'text-muted-foreground' : undefined}>
                    {fields.map((f) => (
                      <TableCell key={f.key}>
                        {f.render
                          ? f.render(row)
                          : cellText((row as Record<string, unknown>)[f.key])}
                      </TableCell>
                    ))}
                    <TableCell>
                      {archived ? (
                        <Badge variant="outline">{t('bpp.refdata.archived', 'Архив')}</Badge>
                      ) : (
                        <Badge variant="secondary">{t('bpp.refdata.active', 'Действует')}</Badge>
                      )}
                    </TableCell>
                    <TableCell className="space-x-1 whitespace-nowrap text-right">
                      {editableFields.length > 0 && (
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={!row.can_edit}
                          onClick={() => openEdit(row)}
                        >
                          {t('bpp.refdata.edit', 'Изменить')}
                        </Button>
                      )}
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={!row.can_edit || toggling.has(row.id)}
                        onClick={() => toggle(row)}
                      >
                        {archived
                          ? t('bpp.refdata.restore', 'Восстановить')
                          : t('bpp.refdata.archive', 'В архив')}
                      </Button>
                    </TableCell>
                  </TableRow>
                );
              })
            )}
          </TableBody>
        </Table>
      </div>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('bpp.refdata.addTitle', 'Новая запись — {{title}}', { title })}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            {fields.map((f) => (
              <div key={f.key} className="space-y-1.5">
                <Label htmlFor={`ref-create-${f.key}`}>{f.label}</Label>
                <FieldInput
                  field={f}
                  id={`ref-create-${f.key}`}
                  value={createValues[f.key] ?? ''}
                  values={createValues}
                  onChange={(value) => setCreateValues((v) => withChange(fields, v, f.key, value))}
                />
              </div>
            ))}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setCreateOpen(false)}
              disabled={createAction.pending}
            >
              {t('bpp.refdata.cancel', 'Отмена')}
            </Button>
            <Button onClick={submitCreate} disabled={createAction.pending || !createReady}>
              {t('bpp.refdata.save', 'Сохранить')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={editing !== null} onOpenChange={(open) => { if (!open) setEditing(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('bpp.refdata.editTitle', 'Правка — {{title}}', { title })}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            {editableFields.map((f) => (
              <div key={f.key} className="space-y-1.5">
                <Label htmlFor={`ref-edit-${f.key}`}>{f.label}</Label>
                <FieldInput
                  field={f}
                  id={`ref-edit-${f.key}`}
                  value={editValues[f.key] ?? ''}
                  values={editValues}
                  onChange={(value) => setEditValues(
                    (v) => withChange(editableFields, v, f.key, value),
                  )}
                />
              </div>
            ))}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setEditing(null)}
              disabled={editAction.pending}
            >
              {t('bpp.refdata.cancel', 'Отмена')}
            </Button>
            <Button onClick={submitEdit} disabled={editAction.pending || !editReady}>
              {t('bpp.refdata.save', 'Сохранить')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}

export default ArchivableTable;
