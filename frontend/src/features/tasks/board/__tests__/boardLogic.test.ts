/**
 * Чистая логика доски (этап S1): фильтр в адресе, параметры запроса,
 * оптимистичный перенос, соседи места вставки, схема переходов, адрес доски.
 */
import { describe, expect, it } from 'vitest';

import { canTransition } from '@/lib/tasks/transitions';

import { filterParams } from '../api';
import { dueTone, neighboursAt } from '../boardUtils';
import { boardKeyFromPath, boardUrl } from '../boardRoutes';
import { moveInBoard } from '../hooks/useBoard';
import { activeFilterCount, readFilters, writeFilters } from '../hooks/useBoardFilters';
import { EMPTY_FILTERS, type Board, type BoardCard } from '../types';

const card = (id: number, status: BoardCard['status']): BoardCard => ({
  id, key: `T-${id}`, summary: `Задача ${id}`, status, priority: 'medium', labels: [],
  due_date: null, start_date: null, completed_at: null, progress_percent: 0,
  has_description: false,
  counts: { comments: 0, attachments: 0, checklist_done: 0, checklist_total: 0 },
  members: [], project: null, department: null, relation: null, rank: null,
  is_new: false, my_role: null, can_move: true,
});

const board = (): Board => ({
  board: { kind: 'personal', id: null, title: null, color: null, settings: { columns: {} as never } },
  columns: [
    { status: 'todo', title: null, color: null, hidden: false, count: 3, has_more: false,
      cards: [card(1, 'todo'), card(2, 'todo'), card(3, 'todo')] },
    { status: 'in_progress', title: null, color: null, hidden: false, count: 2, has_more: false,
      cards: [card(4, 'in_progress'), card(5, 'in_progress')] },
    { status: 'done', title: null, color: null, hidden: false, count: 0, has_more: false, cards: [] },
  ],
  can: { admin: true, reorder: true, create: true },
});

const ids = (value: Board, status: string) =>
  value.columns.find((column) => column.status === status)?.cards.map((item) => item.id);

describe('фильтр доски в адресе', () => {
  it('читается и пишется без потерь', () => {
    const filters = {
      ...EMPTY_FILTERS, q: 'смета', label: ['3', 'none'], member: ['me'], due: ['overdue'],
      completion: ['incomplete'], activity: ['1w'], new: true, hideEmpty: true,
    };
    const params = writeFilters(new URLSearchParams('card=7'), filters);
    expect(params.get('card')).toBe('7');
    expect(params.get('label')).toBe('3,none');
    expect(params.get('compact')).toBe('1');
    expect(readFilters(params)).toEqual(filters);
  });

  it('пустой фильтр убирает свои параметры', () => {
    const params = writeFilters(new URLSearchParams('q=x&label=1&new=1&compact=1'), EMPTY_FILTERS);
    expect(params.toString()).toBe('');
  });

  it('«скрывать пустые колонки» — вид: не считается условием и не уходит на сервер', () => {
    const filters = { ...EMPTY_FILTERS, hideEmpty: true, member: ['me', '12'] };
    expect(activeFilterCount(filters)).toBe(2);
    expect(filterParams(filters)).toEqual({ member: 'me,12' });
  });
});

describe('оптимистичный перенос', () => {
  it('ставит карточку после before_id в другой колонке и пересчитывает счётчики', () => {
    const next = moveInBoard(board(), 2, { status: 'in_progress', before_id: 4, after_id: 5 });
    expect(ids(next, 'todo')).toEqual([1, 3]);
    expect(ids(next, 'in_progress')).toEqual([4, 2, 5]);
    expect(next.columns.find((column) => column.status === 'in_progress')?.count).toBe(3);
    expect(next.columns.find((column) => column.status === 'in_progress')?.cards[1].status)
      .toBe('in_progress');
  });

  it('без соседей — в конец колонки, в пустую колонку — первой', () => {
    expect(ids(moveInBoard(board(), 1, { status: 'in_progress' }), 'in_progress')).toEqual([4, 5, 1]);
    expect(ids(moveInBoard(board(), 1, { status: 'done' }), 'done')).toEqual([1]);
  });

  it('только порядок в своей колонке', () => {
    expect(ids(moveInBoard(board(), 3, { status: 'todo', after_id: 1 }), 'todo')).toEqual([3, 1, 2]);
  });

  it('карточки нет на доске — доска не меняется', () => {
    const before = board();
    expect(moveInBoard(before, 99, { status: 'done' })).toBe(before);
  });
});

describe('соседи места вставки', () => {
  const cards = [card(1, 'todo'), card(2, 'todo'), card(3, 'todo')];

  it('индекс считается без перетаскиваемой карточки', () => {
    expect(neighboursAt(cards, 1, 1)).toEqual({ before_id: 2, after_id: 3 });
    expect(neighboursAt(cards, 3, 0)).toEqual({ before_id: null, after_id: 1 });
    expect(neighboursAt(cards, 9, 3)).toEqual({ before_id: 3, after_id: null });
  });
});

describe('тон срока', () => {
  const today = new Date(2026, 9, 22);
  it('просрочен, скоро, выполнено, без срока', () => {
    expect(dueTone({ due_date: '2026-10-21', status: 'todo' }, today)).toBe('overdue');
    expect(dueTone({ due_date: '2026-10-24', status: 'todo' }, today)).toBe('soon');
    expect(dueTone({ due_date: '2026-10-25', status: 'todo' }, today)).toBe('normal');
    expect(dueTone({ due_date: '2026-10-01', status: 'done' }, today)).toBe('done');
    expect(dueTone({ due_date: null, status: 'todo' }, today)).toBeNull();
  });
});

describe('схема переходов', () => {
  it('своя колонка разрешена всегда, чужая — по схеме', () => {
    expect(canTransition('backlog', 'backlog')).toBe(true);
    expect(canTransition('in_progress', 'done')).toBe(true);
    expect(canTransition('backlog', 'done')).toBe(false);
    expect(canTransition('cancelled', 'todo')).toBe(true);
  });
});

describe('адрес доски', () => {
  it('личная, отдела и проекта; кривой id — не доска', () => {
    expect(boardKeyFromPath('/tasks/board', undefined)).toEqual({ kind: 'personal' });
    expect(boardKeyFromPath('/tasks/board/department/7', '7')).toEqual({ kind: 'department', id: 7 });
    expect(boardKeyFromPath('/tasks/board/project/3', '3')).toEqual({ kind: 'project', id: 3 });
    expect(boardKeyFromPath('/tasks/board/project/x', 'x')).toBeNull();
  });

  it('адрес и разбор — взаимно обратные', () => {
    for (const key of [{ kind: 'personal' as const }, { kind: 'department' as const, id: 4 },
      { kind: 'project' as const, id: 9 }]) {
      const url = boardUrl(key);
      expect(boardKeyFromPath(url, url.split('/').pop())).toEqual(key);
    }
  });
});
