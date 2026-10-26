/**
 * Реестр «Задачи» администратора задач (`HRTasks`): карточка канбана и строка
 * таблицы открывают окно карточки поверх страницы (`?card=<id>`), как на
 * досках; карандаш в таблице ведёт на полную страницу задачи.
 */
import React from 'react';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';
import type { Task } from '@/types/tasks';

vi.mock('@/components/tasks/TasksLayout', () => ({
  TasksLayout: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));
vi.mock('@/components/tasks/CreateTaskModal', () => ({ CreateTaskModal: () => null }));
vi.mock('@/components/tasks/KanbanBoard', () => ({
  KanbanBoard: ({ tasks, onOpen }: { tasks: Task[]; onOpen?: (task: Task) => void }) => (
    <div>
      {tasks.map((task) => (
        <button key={task.id} type="button" onClick={() => onOpen?.(task)}>{`карточка ${task.key}`}</button>
      ))}
    </div>
  ),
}));
// Окно карточки — своё, с тестами; здесь важен только адрес, который его открывает.
vi.mock('@/features/tasks/board/card/StandaloneCardModal', async () => {
  const { useLocation } = await import('react-router-dom');
  return {
    StandaloneCardModal: () => {
      const location = useLocation();
      return <output aria-label="адрес">{location.pathname + location.search}</output>;
    },
  };
});

const fetchTasks = vi.hoisted(() => vi.fn());
vi.mock('@/api/tasks', () => ({
  fetchTasks, createTask: vi.fn(), deleteTask: vi.fn(), updateTask: vi.fn(),
  fetchLabels: vi.fn().mockResolvedValue([]), fetchProjects: vi.fn().mockResolvedValue([]),
  fetchSites: vi.fn().mockResolvedValue([]), fetchTaskTypes: vi.fn().mockResolvedValue([]),
  fetchContractors: vi.fn().mockResolvedValue([]),
}));
vi.mock('@/api/hr', () => ({
  fetchDepartments: vi.fn().mockResolvedValue([]), fetchEmployeeUsers: vi.fn().mockResolvedValue([]),
}));

import HRTasks from '../HRTasks';

const TASK = {
  id: 3, key: 'TASK-3', summary: 'Проверить акты', status: 'backlog', priority: 'medium',
  task_type: 'task', labels: [], assignees: [], due_date: null,
} as unknown as Task;

beforeEach(() => {
  vi.clearAllMocks();
  fetchTasks.mockResolvedValue([TASK]);
});

describe('HRTasks', () => {
  it('карточка канбана открывает окно поверх страницы', async () => {
    renderWithProviders(<HRTasks />, { route: '/tasks' });
    await userEvent.click(await screen.findByRole('button', { name: 'карточка TASK-3' }));
    expect(screen.getByLabelText('адрес')).toHaveTextContent('/tasks?card=3');
  });

  it('строка таблицы открывает окно, карандаш — страницу задачи', async () => {
    renderWithProviders(<HRTasks />, { route: '/tasks' });
    await userEvent.click(await screen.findByRole('button', { name: 'Таблица' }));
    await userEvent.click(await screen.findByText('Проверить акты'));
    expect(screen.getByLabelText('адрес')).toHaveTextContent('/tasks?card=3');
    await userEvent.click(screen.getByTitle('Редактировать'));
    expect(screen.getByLabelText('адрес')).toHaveTextContent('/tasks/3');
  });
});
