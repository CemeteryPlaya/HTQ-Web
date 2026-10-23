/**
 * Быстрая правка (Trello «карандаш»): доска затемняется, карточка остаётся на
 * своём месте с полем названия, справа — действия: «Открыть», метки,
 * участники и даты (при полной правке), «Переместить» (только разрешённые
 * схемой переходов колонки), «Копировать ссылку».
 */
import { forwardRef, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { ArrowRightLeft, Clock, ExternalLink, Link2, Tag, Users } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { canTransition } from '@/lib/tasks/transitions';
import { cn } from '@/lib/utils';
import type { TaskStatus } from '@/types/tasks';

import { swatchStyle } from './boardColors';
import { cardLink, useColumnTitle } from './boardUtils';
import { DatesPopover } from './card/DatesPopover';
import { LabelsPopover } from './card/LabelsPopover';
import { type Crew, MembersPopover } from './card/MembersPopover';
import type { BoardCard, BoardColumn } from './types';

const CARD_WIDTH = 256;
const SIDE_WIDTH = 200;

export interface CardQuickEditProps {
  card: BoardCard;
  anchor: DOMRect;
  columns: BoardColumn[];
  onClose: () => void;
  onOpen: (card: BoardCard) => void;
  onMove: (card: BoardCard, status: TaskStatus) => void;
  onRename: (card: BoardCard, summary: string) => void;
  onLabels: (card: BoardCard, ids: number[]) => void;
  onDates: (card: BoardCard, dates: { start_date: string | null; due_date: string | null }) => void;
  onCrew: (card: BoardCard, crew: Crew) => void;
}

export function CardQuickEdit({
  card, anchor, columns, onClose, onOpen, onMove, onRename, onLabels, onDates, onCrew,
}: CardQuickEditProps) {
  const { t } = useTranslation();
  const columnTitle = useColumnTitle();
  const [text, setText] = useState(card.summary);
  const [moving, setMoving] = useState(false);
  const field = useRef<HTMLTextAreaElement>(null);
  const [position, setPosition] = useState({ top: anchor.top, left: anchor.left });

  useLayoutEffect(() => {
    // Карточка остаётся на своём месте, но окно не уходит за край экрана.
    const width = Math.min(CARD_WIDTH + SIDE_WIDTH + 8, window.innerWidth - 16);
    setPosition({
      top: Math.max(8, Math.min(anchor.top, window.innerHeight - 320)),
      left: Math.max(8, Math.min(anchor.left, window.innerWidth - width - 8)),
    });
  }, [anchor]);

  useEffect(() => {
    field.current?.focus();
    field.current?.select();
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const save = () => {
    const summary = text.trim();
    if (summary && summary !== card.summary) onRename(card, summary);
    onClose();
  };

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(cardLink(card));
      toast.success(t('tasks.board.quick.linkCopied', 'Ссылка скопирована'));
    } catch {
      // Буфер обмена закрыт (нет HTTPS или прав) — ссылку показываем текстом.
      toast.info(cardLink(card));
    }
    onClose();
  };

  const targets = columns.filter((column) => column.status !== card.status
    && !column.hidden && canTransition(card.status, column.status));

  return (
    <div className="fixed inset-0 z-50" role="dialog" aria-modal="true"
      aria-label={t('tasks.board.card.quickEdit', 'Быстрая правка')}>
      <button type="button" className="absolute inset-0 h-full w-full cursor-default bg-black/60"
        aria-label={t('tasks.board.quick.close', 'Закрыть')} onClick={onClose} />
      <div className="absolute flex flex-col gap-2 sm:flex-row sm:items-start"
        style={{ top: position.top, left: position.left }}>
        <div className="space-y-2" style={{ width: Math.min(CARD_WIDTH, window.innerWidth - 16) }}>
          <Textarea
            ref={field}
            value={text}
            rows={4}
            maxLength={500}
            className="resize-none rounded-lg bg-board-card text-sm shadow-lg"
            onChange={(event) => setText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); save(); }
            }}
          />
          <Button size="sm" onClick={save} disabled={!text.trim()}>
            {t('tasks.board.quick.save', 'Сохранить')}
          </Button>
        </div>

        <div className="flex w-[200px] flex-col items-start gap-1">
          <QuickButton icon={ExternalLink} onClick={() => { onClose(); onOpen(card); }}>
            {t('tasks.board.quick.open', 'Открыть карточку')}
          </QuickButton>
          {card.can_edit && (
            <>
              <LabelsPopover selected={card.labels.map((label) => label.id)}
                onChange={(ids) => onLabels(card, ids)}
                trigger={<QuickButton icon={Tag}>{t('tasks.card.add.labels', 'Метки')}</QuickButton>} />
              <MembersPopover assignees={card.members} onChange={(crew) => onCrew(card, crew)}
                trigger={<QuickButton icon={Users}>{t('tasks.card.add.members', 'Участники')}</QuickButton>} />
              <DatesPopover startDate={card.start_date} dueDate={card.due_date}
                onSave={(dates) => onDates(card, dates)}
                trigger={<QuickButton icon={Clock}>{t('tasks.card.add.dates', 'Даты')}</QuickButton>} />
            </>
          )}
          {card.can_move && (
            <QuickButton icon={ArrowRightLeft} onClick={() => setMoving((value) => !value)}
              pressed={moving}>
              {t('tasks.board.quick.move', 'Переместить')}
            </QuickButton>
          )}
          {moving && (
            <div className="w-full space-y-1 rounded-md bg-popover p-1.5 text-popover-foreground shadow-lg">
              {targets.map((column) => (
                <button key={column.status} type="button"
                  className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm hover:bg-muted"
                  onClick={() => { onMove(card, column.status); onClose(); }}>
                  <span className="h-3 w-3 shrink-0 rounded-sm border"
                    style={column.color ? swatchStyle(column.color) : undefined} />
                  <span className="truncate">{columnTitle(column)}</span>
                </button>
              ))}
              {targets.length === 0 && (
                <p className="px-2 py-1.5 text-xs text-muted-foreground">
                  {t('tasks.board.quick.noTargets',
                    'Из этой колонки задачу перенести некуда: другие колонки скрыты или недоступны по схеме переходов.')}
                </p>
              )}
            </div>
          )}
          <QuickButton icon={Link2} onClick={() => void copyLink()}>
            {t('tasks.board.quick.copyLink', 'Копировать ссылку')}
          </QuickButton>
        </div>
      </div>
    </div>
  );
}

/** Кнопка боковой колонки; `forwardRef` — её открывают и всплывающие окна
 * (`PopoverTrigger asChild` вешает ref и обработчики на неё саму). */
const QuickButton = forwardRef<HTMLButtonElement, {
  icon: React.ComponentType<{ className?: string }>;
  pressed?: boolean;
  children: React.ReactNode;
} & React.ButtonHTMLAttributes<HTMLButtonElement>>(
  function QuickButton({ icon: Icon, pressed = false, children, className, ...rest }, ref) {
    return (
      <button ref={ref} type="button" aria-pressed={pressed} {...rest}
        className={cn('flex items-center gap-2 rounded-md bg-black/70 px-3 py-1.5 text-sm font-medium text-white',
          'transition hover:translate-x-0.5 hover:bg-black/85', pressed && 'bg-black/90', className)}>
        <Icon className="h-4 w-4" />
        {children}
      </button>
    );
  },
);
