/**
 * Перенос задачи со страницы `/tasks/:id` (канбан K1.7, спека S1-13, S1-14).
 *
 * Кнопка «Отправить в отдел» — по флагу сервера `can.transfer`. Смена отдела
 * за пределы своих поддеревьев — не правка, а перенос: сервер отвечает 422
 * `task_department_use_transfer`, и тост предлагает открыть диалог переноса
 * (иначе у главы было бы два пути: один снимает исполнителей, другой — нет).
 */
import React from 'react';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';
import type { Task } from '@/types/tasks';

vi.mock('@/components/tasks/TasksLayout', () => ({
  TasksLayout: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));
vi.mock('@/components/tasks/CreateTaskModal', () => ({ CreateTaskModal: () => null }));
vi.mock('@/components/tasks/TaskAssignments', () => ({ TaskAssignments: () => null }));
vi.mock('@/components/tasks/TaskDailyReporting', () => ({ TaskDailyReporting: () => null }));

const toastError = vi.fn();
vi.mock('sonner', () => ({
  toast: { error: (msg: string, opts?: unknown) => toastError(msg, opts), success: vi.fn() },
}));

const fetchTask = vi.fn();
const updateTask = vi.fn();
vi.mock('@/api/tasks', () => ({
  fetchTask: (id: number) => fetchTask(id),
  updateTask: (id: number, body: unknown) => updateTask(id, body),
  fetchTaskTransitions: vi.fn().mockResolvedValue([]),
  fetchProjects: vi.fn().mockResolvedValue([]),
  fetchLabels: vi.fn().mockResolvedValue([]),
  addTaskComment: vi.fn(),
  addTaskAttachment: vi.fn(),
  createTaskLink: vi.fn(),
  deleteTaskLink: vi.fn(),
  transferTask: vi.fn(),
}));
vi.mock('@/api/hr', () => ({
  fetchDepartments: vi.fn().mockResolvedValue([
    { id: 1, name: 'ИТ', description: '', created_at: '', is_active: true },
    { id: 2, name: 'Эксплуатация', description: '', created_at: '', is_active: true },
  ]),
  fetchEmployeeUsers: vi.fn().mockResolvedValue([]),
}));
vi.mock('@/api/client', () => ({ default: { get: vi.fn().mockResolvedValue({ data: {} }) } }));

import HRTaskDetail from '../HRTaskDetail';

const task = (over: Partial<Task> = {}): Task => ({
  id: 5, key: 'T-5', summary: 'Задача', description: '', task_type: 'task',
  priority: 'medium', status: 'todo', progress_percent: 0, reporter: 9,
  assignee: null, supervisor: null, department: 1, department_name: 'ИТ', project: null,
  roadmap: null, site: null, site_block: null, contractor: null, contractor_worker: null,
  parent: null, labels: [], assignees: [], due_date: null, start_date: null,
  completed_at: null, created_at: '2026-10-21T00:00:00Z', updated_at: '2026-10-21T00:00:00Z',
  ...over,
});

const renderPage = () => renderWithProviders(
  <Routes><Route path="/tasks/:id" element={<HRTaskDetail />} /></Routes>,
  { route: '/tasks/5' },
);

beforeEach(() => {
  vi.clearAllMocks();
});

describe('HRTaskDetail — перенос', () => {
  it('показывает «Отправить в отдел» при can.transfer', async () => {
    fetchTask.mockResolvedValue(task({ can: { transfer: true } }));
    renderPage();
    expect(await screen.findByRole('button', { name: /Отправить в отдел/ })).toBeInTheDocument();
  });

  it('без can.transfer кнопки нет', async () => {
    fetchTask.mockResolvedValue(task({ can: { transfer: false } }));
    renderPage();
    expect(await screen.findByText('T-5')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Отправить в отдел/ })).not.toBeInTheDocument();
  });

  it('отказ «используйте перенос» предлагает открыть диалог переноса', async () => {
    fetchTask.mockResolvedValue(task({ can: { transfer: true } }));
    updateTask.mockRejectedValue({
      response: { status: 422, data: { detail: 'server text', code: 'task_department_use_transfer' } },
    });
    renderPage();
    await screen.findByRole('button', { name: /Отправить в отдел/ });

    const trigger = screen.getAllByRole('combobox')
      .find((el) => within(el).queryByText('ИТ'));
    await userEvent.click(trigger as HTMLElement);
    await userEvent.click(await screen.findByRole('option', { name: 'Эксплуатация' }));

    await waitFor(() => expect(updateTask).toHaveBeenCalledWith(5, { department: 2 }));
    await waitFor(() => expect(toastError).toHaveBeenCalled());
    const [text, options] = toastError.mock.calls[0] as [string, { action: { label: string; onClick: () => void } }];
    expect(text).toMatch(/Отправить в отдел/);
    expect(options.action.label).toBe('Отправить в отдел');

    options.action.onClick();
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
  });
});
