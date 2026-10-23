/**
 * Колонка доски (Trello): 272 px, свой цвет (K-34), шапка — название,
 * счётчик, «свернуть» и меню; внизу — «+ Добавить карточку». Свёрнутая
 * колонка — узкая полоса с повёрнутым названием; свёрнутость — вид у
 * конкретного человека (K-34), его хранит холст.
 */
import { Draggable, Droppable } from '@hello-pangea/dnd';
import { ChevronsLeftRight, EyeOff, MoreHorizontal, Palette, Plus } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel,
  DropdownMenuSeparator, DropdownMenuSub, DropdownMenuSubContent, DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { cn } from '@/lib/utils';

import { BoardCard } from './BoardCard';
import { columnStyle, swatchStyle } from './boardColors';
import { useColumnTitle } from './boardUtils';
import { QuickAddCard } from './QuickAddCard';
import { BOARD_COLORS, type BoardCard as Card, type BoardColor, type BoardColumn as Column } from './types';

export interface BoardColumnProps {
  column: Column;
  collapsed: boolean;
  onToggleCollapsed: () => void;
  canAdmin: boolean;
  canCreate: boolean;
  canDragCard: (card: Card) => boolean;
  dropDisabled: boolean;
  labelsExpanded: boolean;
  onToggleLabels: () => void;
  onOpenCard: (card: Card) => void;
  onQuickEdit: (card: Card, anchor: HTMLElement) => void;
  onCompleteCard: (card: Card) => void;
  onAdd: (summary: string) => Promise<unknown>;
  addPending: boolean;
  onSetColor: (color: BoardColor | null) => void;
  onHide: () => void;
  onLoadMore: () => void;
}

export function BoardColumn(props: BoardColumnProps) {
  const { t } = useTranslation();
  const columnTitle = useColumnTitle();
  const { column, collapsed } = props;
  const title = columnTitle(column);

  if (collapsed) {
    return (
      <button
        type="button"
        onClick={props.onToggleCollapsed}
        className="flex w-10 shrink-0 flex-col items-center gap-2 rounded-xl py-3 text-sm font-semibold"
        style={columnStyle(column.color)}
        aria-label={t('tasks.board.column.expand', 'Развернуть колонку «{{title}}»', { title })}
      >
        <ChevronsLeftRight className="h-4 w-4 text-muted-foreground" />
        <span className="text-xs text-muted-foreground">{column.count}</span>
        <span className="[writing-mode:vertical-rl]">{title}</span>
      </button>
    );
  }

  return (
    <section
      aria-label={title}
      data-testid={`board-column-${column.status}`}
      className="flex max-h-full w-[min(272px,85vw)] shrink-0 snap-start flex-col rounded-xl"
      style={columnStyle(column.color)}
    >
      <header className="flex items-start gap-1 px-3 pb-1 pt-2.5">
        <h3 className="min-w-0 flex-1 break-words text-sm font-semibold leading-6">{title}</h3>
        <span className="pt-0.5 text-xs text-muted-foreground">{column.count}</span>
        <Button size="icon" variant="ghost" className="h-6 w-6"
          aria-label={t('tasks.board.column.collapse', 'Свернуть колонку')}
          onClick={props.onToggleCollapsed}>
          <ChevronsLeftRight className="h-3.5 w-3.5" />
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button size="icon" variant="ghost" className="h-6 w-6"
              aria-label={t('tasks.board.column.menu', 'Действия с колонкой')}>
              <MoreHorizontal className="h-4 w-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-56">
            <DropdownMenuLabel>{t('tasks.board.column.actions', 'Действия с колонкой')}</DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={props.onToggleCollapsed}>
              <ChevronsLeftRight className="mr-2 h-4 w-4" />
              {t('tasks.board.column.collapse', 'Свернуть колонку')}
            </DropdownMenuItem>
            {props.canAdmin && (
              <>
                <DropdownMenuSub>
                  <DropdownMenuSubTrigger>
                    <Palette className="mr-2 h-4 w-4" />
                    {t('tasks.board.column.color', 'Цвет колонки')}
                  </DropdownMenuSubTrigger>
                  <DropdownMenuSubContent className="w-52 p-2">
                    <div className="grid grid-cols-5 gap-1.5">
                      {BOARD_COLORS.map((color) => (
                        <button
                          key={color}
                          type="button"
                          aria-label={t(`tasks.board.colors.${color}`, color)}
                          className={cn('h-7 rounded-md ring-offset-2',
                            column.color === color && 'ring-2 ring-foreground')}
                          style={swatchStyle(color)}
                          onClick={() => props.onSetColor(color)}
                        />
                      ))}
                    </div>
                    <Button variant="ghost" size="sm" className="mt-2 w-full"
                      onClick={() => props.onSetColor(null)}>
                      {t('tasks.board.column.noColor', 'Без цвета')}
                    </Button>
                  </DropdownMenuSubContent>
                </DropdownMenuSub>
                <DropdownMenuItem onSelect={props.onHide}>
                  <EyeOff className="mr-2 h-4 w-4" />
                  {t('tasks.board.column.hide', 'Скрыть колонку')}
                </DropdownMenuItem>
              </>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      </header>

      <Droppable droppableId={column.status} isDropDisabled={props.dropDisabled}>
        {(provided, snapshot) => (
          <div
            ref={provided.innerRef}
            {...provided.droppableProps}
            className={cn('min-h-[8px] flex-1 space-y-2 overflow-y-auto px-2 pb-1',
              snapshot.isDraggingOver && 'rounded-lg bg-black/5 dark:bg-white/5',
              props.dropDisabled && 'opacity-60')}
          >
            {column.cards.map((card, index) => (
              <Draggable key={card.id} draggableId={String(card.id)} index={index}
                isDragDisabled={!props.canDragCard(card)}>
                {(drag, dragSnapshot) => (
                  <div ref={drag.innerRef} {...drag.draggableProps} {...drag.dragHandleProps}>
                    <BoardCard
                      card={card}
                      dragging={dragSnapshot.isDragging}
                      labelsExpanded={props.labelsExpanded}
                      onToggleLabels={props.onToggleLabels}
                      onOpen={props.onOpenCard}
                      onQuickEdit={props.onQuickEdit}
                      onComplete={props.onCompleteCard}
                    />
                  </div>
                )}
              </Draggable>
            ))}
            {provided.placeholder}
            {column.has_more && (
              <Button variant="ghost" size="sm" className="w-full" onClick={props.onLoadMore}>
                {t('tasks.board.column.more', 'Показать ещё')}
              </Button>
            )}
          </div>
        )}
      </Droppable>

      {props.canCreate && (
        <div className="px-2 pb-2 pt-1">
          <QuickAddCard onAdd={props.onAdd} pending={props.addPending} />
        </div>
      )}
      {!props.canCreate && column.cards.length === 0 && (
        <p className="px-3 pb-3 text-xs text-muted-foreground">
          {t('tasks.board.column.empty', 'Карточек нет')}
        </p>
      )}
      <span className="sr-only"><Plus /></span>
    </section>
  );
}
