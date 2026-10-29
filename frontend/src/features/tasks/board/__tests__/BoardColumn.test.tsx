/**
 * Колонка доски — то, что нашла живая проверка S1 (23.10):
 * - у колонки нет своей прокрутки: `@hello-pangea/dnd` не поддерживает
 *   вложенные прокрутки, и колонка со `overflow` внутри прокручиваемого холста
 *   ломала перенос между колонками;
 * - куда схема переходов не пускает, гаснет вся колонка, а не только зона
 *   карточек (у пустой колонки она — полоска в 16 px);
 * - меню цвета закрывается после выбора.
 */
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DragDropContext } from '@hello-pangea/dnd';
import { describe, expect, it, vi } from 'vitest';

import { BoardColumn, type BoardColumnProps } from '../BoardColumn';
import type { BoardCard, BoardColumn as Column } from '../types';

const card: BoardCard = {
  id: 5, key: 'T-5', summary: 'Проверить акты', status: 'backlog', priority: 'medium', labels: [],
  due_date: null, start_date: null, completed_at: null, progress_percent: 0, has_description: false,
  counts: { comments: 0, attachments: 0, checklist_done: 0, checklist_total: 0 },
  members: [], project: null, department: null, relation: null, rank: 'V', is_new: false,
  my_role: null, can_move: true,
};

const column: Column = {
  status: 'backlog', title: 'Постановка задачи', color: 'purple', hidden: false,
  count: 1, has_more: false, cards: [card],
};

function renderColumn(over: Partial<BoardColumnProps> = {}) {
  const props: BoardColumnProps = {
    column, collapsed: false, onToggleCollapsed: vi.fn(), canAdmin: true, canCreate: true,
    canDragCard: () => true, dropDisabled: false, labelsExpanded: false, onToggleLabels: vi.fn(),
    onOpenCard: vi.fn(), onQuickEdit: vi.fn(), onCompleteCard: vi.fn(), onAdd: vi.fn(),
    addPending: false, onSetColor: vi.fn(), onHide: vi.fn(), onLoadMore: vi.fn(), ...over,
  };
  render(<DragDropContext onDragEnd={() => undefined}><BoardColumn {...props} /></DragDropContext>);
  return props;
}

describe('BoardColumn', () => {
  it('не прокручивается сама — прокрутка только у холста', () => {
    renderColumn();
    const section = screen.getByTestId('board-column-backlog');
    const scrolling = [section, ...section.querySelectorAll('*')]
      .filter((el) => /(^|\s)overflow-(y-)?(auto|scroll)(\s|$)/.test(el.getAttribute('class') ?? ''));
    expect(scrolling).toEqual([]);
  });

  it('недоступная для броска колонка гаснет целиком', () => {
    renderColumn({ dropDisabled: true });
    expect(screen.getByTestId('board-column-backlog').className).toMatch(/opacity-40/);
  });

  it('выбор цвета применяется и закрывает меню', async () => {
    const { onSetColor } = renderColumn();
    await userEvent.click(screen.getByRole('button', { name: 'Действия с колонкой' }));
    await userEvent.click(await screen.findByText('Цвет колонки'));
    await userEvent.click(await screen.findByRole('button', { name: 'Бирюзовый' }));
    expect(onSetColor).toHaveBeenCalledWith('sky');
    expect(screen.queryByText('Цвет колонки')).not.toBeInTheDocument();
  });

  it('название колонки — своё у доски', () => {
    renderColumn();
    const header = within(screen.getByTestId('board-column-backlog')).getByRole('heading');
    expect(header).toHaveTextContent('Постановка задачи');
  });
});
