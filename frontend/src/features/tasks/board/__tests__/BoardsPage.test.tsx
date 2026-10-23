/**
 * Страница доски (этап S1, мастер-план §7.3): колонки с названиями и цветами
 * доски, скрытые не показываются (K-34); «Добавить карточку» — только в
 * колонках, с которых задача может начаться у этого человека
 * (`task_status_initial`); доска отдела — по id из адреса, быстрое
 * добавление ставит задачу в отдел доски; «Колонки» — администратору доски
 * (K-39); невидимая доска — объяснение, а не пустой холст.
 */
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';
import type { TaskStatus } from '@/types/tasks';

vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() } }));
vi.mock('@/components/Header', () => ({ Header: () => null }));
vi.mock('@/api/tasks', () => ({ fetchLabels: vi.fn().mockResolvedValue([]) }));

const permissions = vi.hoisted(() => vi.fn());
vi.mock('@/hooks/usePermissions', () => ({ usePermissions: () => permissions() }));

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn() }));
vi.mock('@/api/client', () => ({ default: api }));

import BoardsPage from '../BoardsPage';
import type { Board } from '../types';

const ORDER: TaskStatus[] = ['backlog', 'todo', 'in_progress', 'in_review', 'blocked', 'done', 'cancelled'];
const TITLES: Partial<Record<TaskStatus, string>> = {
  backlog: 'Постановка задачи', todo: 'Ожидающие исполнения', in_progress: 'Исполнение',
  blocked: 'В ожидании', done: 'Готово',
};
const HIDDEN: TaskStatus[] = ['in_review', 'cancelled'];

function boardResponse(over: Partial<Board['can']> = {}, kind: Board['board']['kind'] = 'personal'): Board {
  const settings = Object.fromEntries(ORDER.map((status) => [status, {
    title: TITLES[status] ?? null, color: status === 'done' ? 'green' : null, hidden: HIDDEN.includes(status),
  }])) as Board['board']['settings']['columns'];
  return {
    board: { kind, id: kind === 'personal' ? null : 7, title: kind === 'personal' ? null : 'ИТ',
      color: null, settings: { columns: settings } },
    columns: ORDER.map((status) => ({
      status, ...settings[status], count: status === 'todo' ? 1 : 0, has_more: false,
      cards: status === 'todo' ? [{
        id: 11, key: 'T-11', summary: 'Подготовить отчёт', status: 'todo', priority: 'medium',
        labels: [], due_date: null, start_date: null, completed_at: null, progress_percent: 0,
        has_description: false,
        counts: { comments: 0, attachments: 0, checklist_done: 0, checklist_total: 0 },
        members: [], project: null, department: null, relation: null, rank: null,
        is_new: true, my_role: 'assignee', can_move: true,
      }] : [],
    })),
    can: { admin: false, reorder: false, create: true, ...over },
  };
}

function serve(board: Board | Error) {
  api.get.mockImplementation((url: string) => {
    if (url === 'tasks/v1/boards') {
      return Promise.resolve({ data: { personal: true, departments: [], projects: [] } });
    }
    return board instanceof Error ? Promise.reject(board) : Promise.resolve({ data: board });
  });
}

function renderAt(route: string) {
  return renderWithProviders(
    <Routes>
      <Route path="/tasks/board" element={<BoardsPage />} />
      <Route path="/tasks/board/department/:id" element={<BoardsPage />} />
      <Route path="/tasks/board/project/:id" element={<BoardsPage />} />
    </Routes>,
    { route },
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  permissions.mockReturnValue({ atLeast: () => false });
  try { window.localStorage.clear(); } catch { /* jsdom без хранилища */ }
});

describe('BoardsPage', () => {
  it('показывает колонки с названиями доски и прячет скрытые', async () => {
    serve(boardResponse());
    renderAt('/tasks/board');
    expect(await screen.findByText('Ожидающие исполнения')).toBeInTheDocument();
    expect(screen.getByText('Подготовить отчёт')).toBeInTheDocument();
    expect(screen.getByText('Мои задачи')).toBeInTheDocument();
    for (const status of HIDDEN) {
      expect(screen.queryByTestId(`board-column-${status}`)).not.toBeInTheDocument();
    }
    expect(screen.getByTestId('board-column-done')).toBeInTheDocument();
  });

  it('рядовой сотрудник добавляет карточки только в начальные колонки', async () => {
    serve(boardResponse());
    renderAt('/tasks/board');
    await screen.findByText('Ожидающие исполнения');
    expect(within(screen.getByTestId('board-column-backlog')).getByText('Добавить карточку')).toBeInTheDocument();
    expect(within(screen.getByTestId('board-column-todo')).getByText('Добавить карточку')).toBeInTheDocument();
    expect(within(screen.getByTestId('board-column-in_progress')).queryByText('Добавить карточку'))
      .not.toBeInTheDocument();
  });

  it('администратор задач добавляет карточки в любой видимой колонке', async () => {
    permissions.mockReturnValue({ atLeast: (module: string, level: string) => module === 'tasks' && level === 'admin' });
    serve(boardResponse());
    renderAt('/tasks/board');
    await screen.findByText('Ожидающие исполнения');
    expect(screen.getAllByText('Добавить карточку')).toHaveLength(5);
  });

  it('доска отдела берётся по id из адреса, новая карточка встаёт в отдел доски', async () => {
    serve(boardResponse({}, 'department'));
    api.post.mockResolvedValue({ data: { id: 12 } });
    renderAt('/tasks/board/department/7');
    await screen.findByText('Ожидающие исполнения');
    expect(api.get).toHaveBeenCalledWith('tasks/v1/boards/departments/7', expect.anything());

    const todo = screen.getByTestId('board-column-todo');
    await userEvent.click(within(todo).getByText('Добавить карточку'));
    await userEvent.type(within(todo).getByPlaceholderText('Введите название задачи'), 'Новая задача{Enter}');

    await waitFor(() => expect(api.post).toHaveBeenCalledWith('tasks/v1/tasks/', {
      summary: 'Новая задача', status: 'todo', department_id: 7,
      board: { kind: 'department', id: 7 },
    }));
  });

  it('«Колонки» — только у администратора доски', async () => {
    serve(boardResponse());
    const view = renderAt('/tasks/board');
    await screen.findByText('Ожидающие исполнения');
    expect(screen.queryByRole('button', { name: /Колонки/ })).not.toBeInTheDocument();
    view.unmount();

    serve(boardResponse({ admin: true }));
    renderAt('/tasks/board');
    await screen.findByText('Ожидающие исполнения');
    expect(screen.getByRole('button', { name: /Колонки/ })).toBeInTheDocument();
  });

  it('невидимая доска объясняется, а не показывается пустой', async () => {
    serve(Object.assign(new Error('404'), { response: { status: 404, data: { detail: 'Board not found' } } }));
    renderAt('/tasks/board/project/3');
    expect(await screen.findByText('Доски нет или она вам не видна')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'К моей доске' })).toHaveAttribute('href', '/tasks/board');
  });
});
