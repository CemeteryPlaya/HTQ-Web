/**
 * Правка текста на месте (Trello: название и описание карточки). Клик —
 * поле ввода; Enter (у однострочного) или «Сохранить» — сохранить, Esc или
 * «Отмена» — вернуть прежнее. Без права правки — просто текст.
 */
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';

export interface EditableTextProps {
  value: string;
  onSave: (value: string) => void;
  canEdit: boolean;
  /** Однострочное (название): Enter сохраняет, переносов нет. */
  singleLine?: boolean;
  placeholder?: string;
  maxLength?: number;
  className?: string;
  /** Подпись поля для экранного диктора. */
  label: string;
}

export function EditableText({
  value, onSave, canEdit, singleLine = false, placeholder, maxLength, className, label,
}: EditableTextProps) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(value);
  const field = useRef<HTMLTextAreaElement>(null);
  // Правка заканчивается ровно один раз: Enter, а за ним blur исчезающего
  // поля, или Esc, а за ним тот же blur, не должны сохранить второй раз.
  const active = useRef(false);
  const start = () => { active.current = true; setEditing(true); };

  useEffect(() => { if (!editing) setText(value); }, [value, editing]);
  useEffect(() => {
    if (editing) {
      field.current?.focus();
      field.current?.select();
    }
  }, [editing]);

  const save = () => {
    if (!active.current) return;
    active.current = false;
    const next = singleLine ? text.replace(/\s+/g, ' ').trim() : text.trim();
    setEditing(false);
    if ((singleLine && !next) || next === value.trim()) {
      setText(value);
      return;
    }
    onSave(next);
  };
  const cancel = () => { active.current = false; setText(value); setEditing(false); };

  if (!editing) {
    const empty = !value.trim();
    return (
      <div
        role={canEdit ? 'button' : undefined}
        tabIndex={canEdit ? 0 : undefined}
        aria-label={canEdit ? label : undefined}
        onClick={() => canEdit && start()}
        onKeyDown={(event) => { if (canEdit && event.key === 'Enter') start(); }}
        className={cn('whitespace-pre-wrap break-words rounded-md',
          canEdit && 'cursor-pointer hover:bg-muted/60', empty && 'text-muted-foreground', className)}
      >
        {empty ? placeholder : value}
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <Textarea
        ref={field}
        aria-label={label}
        value={text}
        rows={singleLine ? 2 : 6}
        maxLength={maxLength}
        placeholder={placeholder}
        className={cn('resize-y', singleLine && 'resize-none', className)}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Escape') { event.stopPropagation(); cancel(); }
          if (singleLine && event.key === 'Enter') { event.preventDefault(); save(); }
        }}
        onBlur={singleLine ? save : undefined}
      />
      {!singleLine && (
        <div className="flex gap-2">
          <Button size="sm" onClick={save}>{t('tasks.card.save', 'Сохранить')}</Button>
          <Button size="sm" variant="ghost" onClick={cancel}>{t('tasks.board.cancel', 'Отмена')}</Button>
        </div>
      )}
    </div>
  );
}
