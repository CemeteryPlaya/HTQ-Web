/**
 * «+ Добавить карточку» внизу колонки (Trello): поле на месте, Enter —
 * создать и остаться в поле для следующей, Esc или × — закрыть.
 */
import { useEffect, useRef, useState } from 'react';
import { Plus, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';

export function QuickAddCard({ onAdd, pending }: {
  onAdd: (summary: string) => Promise<unknown>;
  pending: boolean;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState('');
  const field = useRef<HTMLTextAreaElement>(null);

  useEffect(() => { if (open) field.current?.focus(); }, [open]);

  const submit = async () => {
    const summary = text.trim();
    if (!summary || pending) return;
    try {
      await onAdd(summary);
      setText('');
    } catch {
      // Причину показал onError мутации; текст остаётся — можно повторить.
    }
    field.current?.focus();
  };

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="flex w-full items-center gap-1.5 rounded-lg px-2 py-1.5 text-sm text-muted-foreground transition hover:bg-black/5 hover:text-foreground dark:hover:bg-white/10"
      >
        <Plus className="h-4 w-4" />
        {t('tasks.board.addCard', 'Добавить карточку')}
      </button>
    );
  }

  return (
    <div className="space-y-2">
      <Textarea
        ref={field}
        value={text}
        rows={2}
        maxLength={500}
        placeholder={t('tasks.board.addCardPlaceholder', 'Введите название задачи')}
        className="resize-none bg-board-card text-sm"
        onChange={(event) => setText(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void submit(); }
          if (event.key === 'Escape') { setOpen(false); setText(''); }
        }}
      />
      <div className="flex items-center gap-2">
        <Button size="sm" onClick={() => void submit()} disabled={!text.trim() || pending}>
          {t('tasks.board.addCard', 'Добавить карточку')}
        </Button>
        <Button size="icon" variant="ghost" className="h-8 w-8"
          aria-label={t('tasks.board.cancel', 'Отмена')}
          onClick={() => { setOpen(false); setText(''); }}>
          <X className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
