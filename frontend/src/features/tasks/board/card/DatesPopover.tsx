/**
 * Даты карточки (Trello «Даты»): начало и срок. Порядок дат проверяется до
 * отправки (`datesOutOfOrder`) — узнавать о нём от сервера дороже.
 */
import { type ReactNode, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import { DateInput } from '@/components/ui/date-input';
import { Label } from '@/components/ui/label';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { datesOutOfOrder } from '@/lib/validation';

export interface DatesPopoverProps {
  startDate: string | null;
  dueDate: string | null;
  onSave: (dates: { start_date: string | null; due_date: string | null }) => void;
  disabled?: boolean;
  trigger: ReactNode;
}

export function DatesPopover({ startDate, dueDate, onSave, disabled = false, trigger }: DatesPopoverProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [start, setStart] = useState(startDate ?? '');
  const [due, setDue] = useState(dueDate ?? '');
  const [startInvalid, setStartInvalid] = useState(false);
  const [dueInvalid, setDueInvalid] = useState(false);

  useEffect(() => {
    if (open) {
      setStart(startDate ?? '');
      setDue(dueDate ?? '');
    }
  }, [open, startDate, dueDate]);

  const outOfOrder = datesOutOfOrder(start, due);
  const save = (next: { start_date: string | null; due_date: string | null }) => {
    onSave(next);
    setOpen(false);
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild disabled={disabled}>{trigger}</PopoverTrigger>
      <PopoverContent align="start" className="w-72 space-y-3 p-3">
        <p className="text-center text-sm font-semibold">{t('tasks.card.dates.title', 'Даты')}</p>
        <div className="space-y-1.5">
          <Label>{t('tasks.card.dates.start', 'Начало')}</Label>
          <DateInput value={start} onChange={setStart} onValidityChange={setStartInvalid} />
        </div>
        <div className="space-y-1.5">
          <Label>{t('tasks.card.dates.due', 'Срок')}</Label>
          <DateInput value={due} onChange={setDue} onValidityChange={setDueInvalid} />
        </div>
        {outOfOrder && (
          <p role="alert" className="text-xs text-destructive">
            {t('tasks.card.dates.order', 'Срок не может быть раньше начала.')}
          </p>
        )}
        <div className="flex gap-2">
          <Button size="sm" className="flex-1" disabled={outOfOrder || startInvalid || dueInvalid}
            onClick={() => save({ start_date: start || null, due_date: due || null })}>
            {t('tasks.card.save', 'Сохранить')}
          </Button>
          <Button size="sm" variant="outline" className="flex-1"
            onClick={() => save({ start_date: null, due_date: null })}>
            {t('tasks.card.dates.clear', 'Убрать даты')}
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}
