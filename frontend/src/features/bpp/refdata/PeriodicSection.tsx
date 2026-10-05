/**
 * Раздел периодического справочника — курсы валют, ставки НДС, МРП
 * (ТЗ §18). У таких записей нет ни правки, ни архива
 * (`apps/refdata/urls.py`: только `GET`/`POST`): значение действует с даты,
 * и ошибку исправляют новой записью, а не правкой старой — документ,
 * посчитанный по старому значению, должен остаться объяснимым.
 *
 * Кнопка «Добавить» — по `can_edit` из ответа сервера, как у архивируемых
 * справочников (`ArchivableTable`): видна всем, выключена вне управляющей
 * компании, над таблицей — объяснение.
 */
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Lock } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';

import { useIdempotentAction } from '../core/useIdempotentAction';

interface Props {
  title: string;
  addLabel: string;
  canEdit: boolean;
  isLoading: boolean;
  /** Подписи колонок таблицы. */
  columns: string[];
  /** Строки таблицы (`<TableRow>`); пустой массив — «Справочник пуст». */
  rows: ReactNode[];
  /** Что-то между заголовком и кнопкой — например, фильтр. */
  toolbarExtra?: ReactNode;
  /** Строка под таблицей — например, «показаны последние 100». */
  footer?: ReactNode;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Поля диалога добавления. */
  form: ReactNode;
  /** Все поля заполнены и разобраны — кнопка «Сохранить» включена. */
  formReady: boolean;
  /** Сохранение; ошибку показывает вызывающий (`reportApiError`). */
  onSubmit: () => Promise<unknown>;
}

export function PeriodicSection({
  title, addLabel, canEdit, isLoading, columns, rows, toolbarExtra, footer,
  open, onOpenChange, form, formReady, onSubmit,
}: Props) {
  const { t } = useTranslation();
  // Двойной клик по «Сохранить» не шлёт второй запрос (ТЗ §05). Ключ
  // идемпотентности ручки справочников не принимают: повтор после обрыва
  // упрётся в уникальность даты и ответит 422, дубля не будет и так.
  const save = useIdempotentAction(onSubmit);
  const readOnlyNotice = !isLoading && !canEdit;

  const submit = async () => {
    try {
      await save.run();
      onOpenChange(false);
    } catch {
      // Ошибка уже показана в onSubmit; диалог остаётся открытым с данными.
    }
  };

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-base font-semibold">{title}</h3>
        <div className="flex flex-wrap items-center gap-2">
          {toolbarExtra}
          <Button size="sm" onClick={() => onOpenChange(true)} disabled={!canEdit}>
            {addLabel}
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
              {columns.map((label) => <TableHead key={label}>{label}</TableHead>)}
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow>
                <TableCell colSpan={columns.length}><Skeleton className="h-6 w-full" /></TableCell>
              </TableRow>
            ) : rows.length === 0 ? (
              <TableRow>
                <TableCell colSpan={columns.length} className="py-6 text-center text-muted-foreground">
                  {t('bpp.refdata.empty', 'Справочник пуст')}
                </TableCell>
              </TableRow>
            ) : rows}
          </TableBody>
        </Table>
      </div>
      {footer}

      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{addLabel}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">{form}</div>
          <DialogFooter>
            <Button variant="outline" onClick={() => onOpenChange(false)} disabled={save.pending}>
              {t('bpp.refdata.cancel', 'Отмена')}
            </Button>
            <Button onClick={submit} disabled={save.pending || !formReady}>
              {t('bpp.refdata.save', 'Сохранить')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}

export default PeriodicSection;
