/**
 * Вид «Таблица» раздела «Задачи» для администратора задач (`HRTasks`,
 * `/tasks/list`, этап S6a): строка открывает окно карточки поверх страницы
 * (`?card=<id>`), как на досках; карандаш ведёт на полную страницу задачи.
 * Своего канбана у страницы больше нет — «Доска» ведёт на доски раздела.
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
  fetchTasks, createTask: vi.fn(), deleteTask: vi.fn(),
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
  it('сразу таблица; «Доска» ведёт на доски раздела', async () => {
    renderWithProviders(<HRTasks />, { route: '/tasks/list' });
    expect(await screen.findByText('Проверить акты')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Доска/ })).toHaveAttribute('href', '/tasks/board');
    expect(screen.getByRole('link', { name: /Таблица/ })).toHaveAttribute('aria-current', 'page');
  });

  it('«Показать задачи объекта» (?site_id=) сразу фильтрует таблицу по объекту', async () => {
    renderWithProviders(<HRTasks />, { route: '/tasks/list?site_id=4' });
    expect(await screen.findByText('Проверить акты')).toBeInTheDocument();
    expect(fetchTasks).toHaveBeenCalledWith({ site_id: '4' });
  });

  it('строка таблицы открывает окно, карандаш — страницу задачи', async () => {
    renderWithProviders(<HRTasks />, { route: '/tasks/list' });
    await userEvent.click(await screen.findByText('Проверить акты'));
    expect(screen.getByLabelText('адрес')).toHaveTextContent('/tasks/list?card=3');
    await userEvent.click(screen.getByTitle('Редактировать'));
    expect(screen.getByLabelText('адрес')).toHaveTextContent('/tasks/3');
  });
});
