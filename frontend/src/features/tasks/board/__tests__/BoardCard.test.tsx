/**
 * Карточка на доске (этап S1): название, метки, участники, кружок
 * «выполнено» — только если задачу можно вести и схема пускает в «Готово»,
 * карандаш быстрой правки не открывает карточку.
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { BoardCard } from '../BoardCard';
import type { BoardCard as Card } from '../types';

const base: Card = {
  id: 7, key: 'T-7', summary: 'Согласовать смету', status: 'in_progress', priority: 'medium',
  labels: [{ id: 1, name: 'Протокол', color: '#61bd4f' }],
  due_date: null, start_date: null, completed_at: null, progress_percent: 0, has_description: true,
  counts: { comments: 2, attachments: 0, checklist_done: 0, checklist_total: 0 },
  members: [1, 2, 3, 4, 5, 6].map((id) => ({
    user_id: id, role: id === 1 ? 'primary' : 'collaborator', name: `Сотрудник ${id}`, avatar_url: null,
  })),
  project: null, department: null, relation: null, rank: 'V', is_new: false, my_role: null,
  can_move: true,
};

function renderCard(card: Partial<Card> = {}) {
  const handlers = { onOpen: vi.fn(), onQuickEdit: vi.fn(), onComplete: vi.fn(), onToggleLabels: vi.fn() };
  render(<BoardCard card={{ ...base, ...card }} labelsExpanded={false} {...handlers} />);
  return handlers;
}

describe('BoardCard', () => {
  it('показывает название, четыре аватара и счётчик остальных', () => {
    renderCard();
    expect(screen.getByText('Согласовать смету')).toBeInTheDocument();
    expect(screen.getByText('+2')).toBeInTheDocument();
  });

  it('кружок «выполнено» — у задачи, которую можно вести и закрыть по схеме', async () => {
    const { onComplete, onOpen } = renderCard();
    await userEvent.click(screen.getByRole('button', { name: 'Отметить выполненной' }));
    expect(onComplete).toHaveBeenCalledWith(expect.objectContaining({ id: 7 }));
    expect(onOpen).not.toHaveBeenCalled();
  });

  it('без права вести задачу или без перехода в «Готово» кружка нет', () => {
    renderCard({ can_move: false });
    expect(screen.queryByRole('button', { name: 'Отметить выполненной' })).not.toBeInTheDocument();
  });

  it('из «Бэклога» сразу в «Готово» не закрыть', () => {
    renderCard({ status: 'backlog' });
    expect(screen.queryByRole('button', { name: 'Отметить выполненной' })).not.toBeInTheDocument();
  });

  it('карандаш открывает быструю правку, а не карточку', async () => {
    const { onQuickEdit, onOpen } = renderCard();
    await userEvent.click(screen.getByRole('button', { name: 'Быстрая правка' }));
    expect(onQuickEdit).toHaveBeenCalledTimes(1);
    expect(onOpen).not.toHaveBeenCalled();
  });

  it('клик по карточке открывает её', async () => {
    const { onOpen } = renderCard();
    await userEvent.click(screen.getByText('Согласовать смету'));
    expect(onOpen).toHaveBeenCalledWith(expect.objectContaining({ id: 7 }));
  });
});
