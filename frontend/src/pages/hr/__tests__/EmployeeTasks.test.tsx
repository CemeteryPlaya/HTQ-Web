/**
 * «Мои задачи» / «Задачи отдела» сотрудника (канбан K1.7, спека S1-04, S1-07).
 *
 * Вкладки отбирает сервер (`?scope=mine|department`): после расширения
 * видимости (K1.4) клиентский фильтр первых 50 задач терял свои задачи — их
 * вытесняли задачи отдела. «Взять в работу» — отдельная ручка `claim`, а не
 * `PATCH` (полная правка отвечала 403 не-участнику), и кнопка видна только
 * там, где сервер сказал `can.claim`.
 */
import React from 'react';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';
import type { Task } from '@/types/tasks';
import type { UserProfile } from '@/types/userProfile';

vi.mock('@/components/tasks/TasksLayout', () => ({
  TasksLayout: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));
vi.mock('@/components/tasks/KanbanBoard', () => ({ KanbanBoard: () => null }));

const toastError = vi.fn();
vi.mock('sonner', () => ({
  toast: { error: (msg: string) => toastError(msg), success: vi.fn() },
}));

const fetchTasks = vi.fn();
const claimTask = vi.fn();
vi.mock('@/api/tasks', () => ({
  fetchTasks: (params?: Record<string, string>) => fetchTasks(params),
  claimTask: (id: number) => claimTask(id),
  updateTask: vi.fn(),
}));

import EmployeeTasks from '../EmployeeTasks';

const PROFILE = { id: 7, department_id: 3, department: 'ИТ' } as unknown as UserProfile;

const task = (over: Partial<Task>): Task => ({
  id: 1, key: 'T-1', summary: 'Задача', description: '', task_type: 'task',
  priority: 'medium', status: 'todo', progress_percent: 0, reporter: 9,
  assignee: null, supervisor: null, department: 3, project: null, roadmap: null,
  site: null, site_block: null, contractor: null, contractor_worker: null,
  parent: null, labels: [], assignees: [], due_date: null, start_date: null,
  completed_at: null, created_at: '2026-10-21T00:00:00Z', updated_at: '2026-10-21T00:00:00Z',
  ...over,
});

beforeEach(() => {
  vi.clearAllMocks();
  fetchTasks.mockResolvedValue([]);
});

describe('EmployeeTasks', () => {
  it('запрашивает вкладку «Мои» с scope=mine, вкладку отдела — с scope=department', async () => {
    renderWithProviders(<EmployeeTasks profile={PROFILE} />);
    await waitFor(() => expect(fetchTasks).toHaveBeenCalledWith({ scope: 'mine' }));

    await userEvent.click(screen.getByRole('tab', { name: 'Задачи отдела' }));
    await waitFor(() => expect(fetchTasks).toHaveBeenCalledWith({ scope: 'department' }));
  });

  it('не фильтрует задачи отдела на клиенте: показывает и чужие, и взятые', async () => {
    fetchTasks.mockImplementation(async (params?: Record<string, string>) => (
      params?.scope === 'department'
        ? [task({ id: 1, key: 'T-1', summary: 'Свободная' }),
           task({ id: 2, key: 'T-2', summary: 'Взятая коллегой', status: 'in_progress',
                  assignee: 11, assignee_name: 'Коллега', department: 5 })]
        : []));
    renderWithProviders(<EmployeeTasks profile={PROFILE} />);
    await userEvent.click(await screen.findByRole('tab', { name: 'Задачи отдела' }));
    expect(await screen.findByText('Свободная')).toBeInTheDocument();
    expect(screen.getByText('Взятая коллегой')).toBeInTheDocument();
  });

  it('показывает «Взять в работу» только у строк с can.claim', async () => {
    fetchTasks.mockResolvedValue([
      task({ id: 1, key: 'T-1', summary: 'Можно взять', can: { claim: true } }),
      task({ id: 2, key: 'T-2', summary: 'Нельзя взять', can: { claim: false } }),
      task({ id: 3, key: 'T-3', summary: 'Без флага' }),
    ]);
    renderWithProviders(<EmployeeTasks profile={PROFILE} />);
    expect(await screen.findByText('Можно взять')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: /Взять в работу/ })).toHaveLength(1);
  });

  it('«Взять в работу» зовёт claim и обновляет оба списка задач', async () => {
    fetchTasks.mockResolvedValue([task({ id: 4, summary: 'Свободная', can: { claim: true } })]);
    claimTask.mockResolvedValue(task({ id: 4, assignee: 7, status: 'in_progress' }));
    const { queryClient } = renderWithProviders(<EmployeeTasks profile={PROFILE} />);
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries');

    await userEvent.click(await screen.findByRole('button', { name: /Взять в работу/ }));

    await waitFor(() => expect(claimTask).toHaveBeenCalledWith(4));
    await waitFor(() => {
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ['employee-tasks'] });
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ['hr-tasks'] });
    });
  });

  it('отказ claim показывает текст по коду ошибки', async () => {
    fetchTasks.mockResolvedValue([task({ id: 4, summary: 'Свободная', can: { claim: true } })]);
    claimTask.mockRejectedValue({
      response: { status: 409, data: { detail: 'server text', code: 'task_claim_unavailable' } },
    });
    renderWithProviders(<EmployeeTasks profile={PROFILE} />);
    await userEvent.click(await screen.findByRole('button', { name: /Взять в работу/ }));
    await waitFor(() => expect(toastError).toHaveBeenCalledWith(
      'Задачу уже взяли в работу или она не ждёт исполнителя'));
  });
});
