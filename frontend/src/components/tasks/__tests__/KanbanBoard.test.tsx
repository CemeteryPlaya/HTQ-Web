/**
 * Старый канбан страницы «Задачи» открывает карточку окном поверх страницы
 * (`onOpen`): кликом по карточке, обычным кликом по ключу или Enter. Чипы
 * быстрой правки окно не открывают, а ключ с Ctrl ведёт на страницу задачи.
 */
import { fireEvent, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';
import type { Task } from '@/types/tasks';

vi.mock('@/api/hr', () => ({ fetchEmployeeUsers: vi.fn().mockResolvedValue([]) }));
vi.mock('@/api/tasks', () => ({
  fetchLabels: vi.fn().mockResolvedValue([]), updateTask: vi.fn(), updateTaskAssignees: vi.fn(),
  updateTaskSupervisor: vi.fn(), updateTaskProgress: vi.fn(),
}));

import { KanbanBoard } from '../KanbanBoard';

const TASK = {
  id: 3, key: 'TASK-3', summary: 'Проверить акты', status: 'backlog', priority: 'medium',
  task_type: 'task', progress_percent: 0, labels: [], assignees: [], supervisor: null, project: null,
} as unknown as Task;

function renderBoard() {
  const onOpen = vi.fn();
  renderWithProviders(<KanbanBoard tasks={[TASK]} onStatusChange={vi.fn()} onOpen={onOpen} />);
  return onOpen;
}

describe('KanbanBoard', () => {
  it('клик по карточке открывает окно', async () => {
    const onOpen = renderBoard();
    await userEvent.click(screen.getByText('Проверить акты'));
    expect(onOpen).toHaveBeenCalledWith(TASK);
  });

  it('ключ открывает окно, а с Ctrl — страницу задачи', () => {
    const onOpen = renderBoard();
    const key = screen.getByRole('link', { name: 'TASK-3' });
    expect(key).toHaveAttribute('href', '/tasks/3');
    // fireEvent возвращает false, если переход по ссылке отменён.
    expect(fireEvent.click(key)).toBe(false);
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(fireEvent.click(key, { ctrlKey: true })).toBe(true);
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it('чип быстрой правки окно не открывает', async () => {
    const onOpen = renderBoard();
    await userEvent.click(screen.getByRole('button', { name: 'medium' }));
    expect(onOpen).not.toHaveBeenCalled();
  });

  it('Enter на карточке открывает окно', () => {
    const onOpen = renderBoard();
    const handle = screen.getByTestId('kanban-card-3').parentElement as HTMLElement;
    handle.focus();
    fireEvent.keyDown(handle, { key: 'Enter' });
    expect(onOpen).toHaveBeenCalledWith(TASK);
  });
});
