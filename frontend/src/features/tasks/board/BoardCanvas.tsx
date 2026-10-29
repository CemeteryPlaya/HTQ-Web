/**
 * Холст доски: колонки бок о бок с прокруткой вбок, перетаскивание
 * (`@hello-pangea/dnd`). Бросок вычисляет соседей по месту вставки в
 * целевой колонке — их и отправляет перенос (мастер-план §6.1). Колонку,
 * куда сервер не пустит по схеме переходов, во время перетаскивания видно
 * как недоступную.
 */
import { useCallback, useMemo, useState } from 'react';
import { DragDropContext, type DragStart, type DropResult } from '@hello-pangea/dnd';

import { canTransition } from '@/lib/tasks/transitions';
import type { TaskStatus } from '@/types/tasks';

import { BoardColumn } from './BoardColumn';
import { neighboursAt } from './boardUtils';
import type { Board, BoardCard, BoardColor } from './types';

const LABELS_KEY = 'tasks:board:labels-expanded';

function readFlag(key: string): boolean {
  try { return window.localStorage.getItem(key) === '1'; } catch { return false; }
}
function writeFlag(key: string, value: boolean): void {
  try { window.localStorage.setItem(key, value ? '1' : '0'); } catch { /* приватный режим */ }
}

function readCollapsed(key: string): TaskStatus[] {
  try {
    const raw = JSON.parse(window.localStorage.getItem(key) ?? '[]');
    return Array.isArray(raw) ? (raw as TaskStatus[]) : [];
  } catch { return []; }
}

export interface BoardCanvasProps {
  board: Board;
  storageKey: string;
  onMove: (card: BoardCard, status: TaskStatus, before: number | null, after: number | null) => void;
  onOpenCard: (card: BoardCard) => void;
  onQuickEdit: (card: BoardCard, anchor: HTMLElement) => void;
  onAdd: (status: TaskStatus, summary: string) => Promise<unknown>;
  addPending: boolean;
  /** Где показывать «Добавить карточку»: новая задача начинается не с любого
   * статуса (сервер, `task_status_initial`). */
  canCreateIn: (status: TaskStatus) => boolean;
  onSetColumn: (status: TaskStatus, patch: { color?: BoardColor | null; hidden?: boolean }) => void;
  onLoadMore: (status: TaskStatus, offset: number) => void;
}

export function BoardCanvas(props: BoardCanvasProps) {
  const { board } = props;
  const [labelsExpanded, setLabelsExpanded] = useState(() => readFlag(LABELS_KEY));
  const collapseKey = `tasks:board:collapsed:${props.storageKey}`;
  const [collapsed, setCollapsed] = useState<TaskStatus[]>(() => readCollapsed(collapseKey));
  const [dragFrom, setDragFrom] = useState<TaskStatus | null>(null);

  const cardById = useMemo(() => {
    const map = new Map<number, BoardCard>();
    for (const column of board.columns) for (const card of column.cards) map.set(card.id, card);
    return map;
  }, [board.columns]);

  const toggleLabels = useCallback(() => {
    setLabelsExpanded((value) => { writeFlag(LABELS_KEY, !value); return !value; });
  }, []);

  const toggleCollapsed = (status: TaskStatus) => {
    setCollapsed((current) => {
      const next = current.includes(status)
        ? current.filter((item) => item !== status) : [...current, status];
      try { window.localStorage.setItem(collapseKey, JSON.stringify(next)); } catch { /* ignore */ }
      return next;
    });
  };

  const canDragCard = useCallback(
    (card: BoardCard) => card.can_move || board.can.reorder,
    [board.can.reorder],
  );

  const onDragStart = (start: DragStart) => {
    setDragFrom(start.source.droppableId as TaskStatus);
  };

  const onDragEnd = (result: DropResult) => {
    setDragFrom(null);
    const { destination, source, draggableId } = result;
    if (!destination) return;
    const card = cardById.get(Number(draggableId));
    if (!card) return;
    const target = destination.droppableId as TaskStatus;
    if (target === source.droppableId && destination.index === source.index) return;
    const column = board.columns.find((item) => item.status === target);
    if (!column) return;
    const { before_id, after_id } = neighboursAt(column.cards, card.id, destination.index);
    props.onMove(card, target, before_id, after_id);
  };

  const dropDisabled = (status: TaskStatus) => {
    if (!dragFrom || dragFrom === status) return false;
    return !canTransition(dragFrom, status);
  };

  const visible = board.columns.filter((column) => !column.hidden);

  return (
    <DragDropContext onDragStart={onDragStart} onDragEnd={onDragEnd}>
      {/* Холст — ЕДИНСТВЕННЫЙ прокручиваемый контейнер (вбок и вниз):
          `@hello-pangea/dnd` не поддерживает вложенные прокрутки, и колонка
          со своей прокруткой внутри прокручиваемого холста ломала перенос
          между колонками («unsupported nested scroll container»). */}
      <div className="flex h-full items-start gap-3 overflow-auto px-4 pb-4 pt-3">
        {visible.map((column) => (
          <BoardColumn
            key={column.status}
            column={column}
            collapsed={collapsed.includes(column.status)}
            onToggleCollapsed={() => toggleCollapsed(column.status)}
            canAdmin={board.can.admin}
            canCreate={props.canCreateIn(column.status)}
            canDragCard={canDragCard}
            dropDisabled={dropDisabled(column.status)}
            labelsExpanded={labelsExpanded}
            onToggleLabels={toggleLabels}
            onOpenCard={props.onOpenCard}
            onQuickEdit={props.onQuickEdit}
            onCompleteCard={(card) => props.onMove(card, 'done', null, null)}
            onAdd={(summary) => props.onAdd(column.status, summary)}
            addPending={props.addPending}
            onSetColor={(color) => props.onSetColumn(column.status, { color })}
            onHide={() => props.onSetColumn(column.status, { hidden: true })}
            onLoadMore={() => props.onLoadMore(column.status, column.cards.length)}
          />
        ))}
      </div>
    </DragDropContext>
  );
}
