/**
 * Доска задач ↔ «Проект» БЗО (D-02: «Проект» главный).
 *
 * Доска заводится только выбором «Проекта» — своего названия, статуса, сроков
 * и владельца на создании у неё нет; у связанной доски эти поля только для
 * чтения и в правку не уходят (сервер ответил бы 409). Доска без связи
 * правится по-старому.
 */
import React from 'react';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';
import type { Project, ProjectLinkCandidate } from '@/types/tasks';

vi.mock('@/components/tasks/TasksLayout', () => ({
  TasksLayout: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));
vi.mock('@/components/tasks/SiteWorkTree', () => ({ SiteWorkTree: () => null }));

vi.mock('@/hooks/usePermissions', () => ({
  usePermissions: () => ({ atLeast: () => true, level: () => 'admin', can: () => true }),
}));
vi.mock('@/hooks/useActiveProfile', () => ({
  useActiveProfile: () => ({ activeProfile: { id: 9 } }),
}));

const toastError = vi.fn();
vi.mock('sonner', () => ({
  toast: { error: (msg: string) => toastError(msg), success: vi.fn() },
}));

const fetchProjects = vi.fn();
const fetchProjectLinkCandidates = vi.fn();
const createProject = vi.fn();
const updateProject = vi.fn();
vi.mock('@/api/tasks', () => ({
  fetchProjects: () => fetchProjects(),
  fetchProjectLinkCandidates: (q: string) => fetchProjectLinkCandidates(q),
  createProject: (body: unknown) => createProject(body),
  updateProject: (id: number, body: unknown) => updateProject(id, body),
  deleteProject: vi.fn(),
  fetchProjectTasks: vi.fn().mockResolvedValue([]),
  fetchRoadmaps: vi.fn().mockResolvedValue([]),
  fetchSites: vi.fn().mockResolvedValue([]),
  setProjectSites: vi.fn(),
}));
vi.mock('@/api/hr', () => ({ fetchDepartments: vi.fn().mockResolvedValue([]) }));
vi.mock('@/api/users', () => ({ searchUserOptions: vi.fn().mockResolvedValue([]) }));

import HRProjects from '../HRProjects';

const CANDIDATE: ProjectLinkCandidate = {
  id: '6f1c2d3e-0000-4000-8000-000000000001', code: 'П-015', name: 'Объект 15',
  status: 'active', date_start: '2026-01-01', date_end: '2026-06-30', manager_user_id: 11,
};

const board = (over: Partial<Project> = {}): Project => ({
  id: 1, name: 'Объект 15', description: '', status: 'active', color: '#3b82f6',
  start_date: null, end_date: null, owner_id: 9, owner_name: 'Админ', department_id: null,
  sites: [], site_ids: [], use_production_calendar: false, task_count: 0, done_count: 0,
  progress: 0, created_at: '2026-09-29T00:00:00Z', updated_at: '2026-09-29T00:00:00Z',
  project_ref: CANDIDATE.id, project_code: 'П-015', linked: true, ...over,
});

beforeEach(() => {
  vi.clearAllMocks();
  fetchProjects.mockResolvedValue([]);
  fetchProjectLinkCandidates.mockResolvedValue([CANDIDATE]);
  createProject.mockResolvedValue(board());
  updateProject.mockResolvedValue(board());
});

describe('HRProjects — связь с «Проектом»', () => {
  it('создаёт доску выбором проекта, без своего названия', async () => {
    const user = userEvent.setup();
    renderWithProviders(<HRProjects />);

    await user.click(await screen.findByRole('button', { name: /Добавить проект/ }));
    expect(screen.queryByLabelText('Название')).not.toBeInTheDocument();
    await user.click(await screen.findByRole('button', { name: /П-015.*Объект 15/ }));
    expect(screen.getByText('2026-06-30')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Сохранить/ }));

    await waitFor(() => expect(createProject).toHaveBeenCalledTimes(1));
    expect(createProject).toHaveBeenCalledWith({
      project_ref: CANDIDATE.id, description: '', color: '#3b82f6',
      department_id: null, use_production_calendar: false,
    });
  });

  it('не отправляет доску без проекта', async () => {
    const user = userEvent.setup();
    renderWithProviders(<HRProjects />);

    await user.click(await screen.findByRole('button', { name: /Добавить проект/ }));
    await user.click(screen.getByRole('button', { name: /Сохранить/ }));
    expect(toastError).toHaveBeenCalledWith('Выберите проект');
    expect(createProject).not.toHaveBeenCalled();
  });

  it('у связанной доски поля проекта только для чтения и в правку не уходят', async () => {
    fetchProjects.mockResolvedValue([board()]);
    const user = userEvent.setup();
    renderWithProviders(<HRProjects />);

    await user.click(await screen.findByRole('button', { name: /Объект 15/ }));
    expect(screen.getByRole('link', { name: /П-015/ })).toHaveAttribute(
      'href', `/bpp/projects/${CANDIDATE.id}`);
    await user.click(screen.getByRole('button', { name: /Изменить/ }));
    expect(screen.getByLabelText('Название')).toBeDisabled();
    await user.click(screen.getByRole('button', { name: /Сохранить/ }));

    await waitFor(() => expect(updateProject).toHaveBeenCalledTimes(1));
    expect(updateProject).toHaveBeenCalledWith(1, {
      description: '', color: '#3b82f6', department_id: null, use_production_calendar: false,
    });
  });

  it('доска без связи правится целиком, как раньше', async () => {
    fetchProjects.mockResolvedValue([board({ linked: false, project_ref: '', project_code: null })]);
    const user = userEvent.setup();
    renderWithProviders(<HRProjects />);

    await user.click(await screen.findByRole('button', { name: /Объект 15/ }));
    await user.click(screen.getByRole('button', { name: /Изменить/ }));
    const name = screen.getByLabelText('Название');
    expect(name).toBeEnabled();
    await user.clear(name);
    await user.type(name, 'Объект 16');
    await user.click(screen.getByRole('button', { name: /Сохранить/ }));

    await waitFor(() => expect(updateProject).toHaveBeenCalledTimes(1));
    expect(updateProject.mock.calls[0][1]).toMatchObject({ name: 'Объект 16', status: 'active' });
  });
});
