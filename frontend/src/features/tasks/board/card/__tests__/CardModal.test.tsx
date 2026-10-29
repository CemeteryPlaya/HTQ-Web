/**
 * Окно карточки (этап S2, решение K-19): название правится на месте, пункт
 * чек-листа отмечается, лента показывает комментарии и события, тот, кто не
 * в роли, просит доступ, недоступная карточка закрывает окно с объяснением.
 */
import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';
import type { Task } from '@/types/tasks';

import type { BoardColumn } from '../../types';

const toast = vi.hoisted(() => ({ error: vi.fn(), success: vi.fn(), info: vi.fn() }));
vi.mock('sonner', () => ({ toast }));

const tasksApi = vi.hoisted(() => ({
  fetchTask: vi.fn(), updateTask: vi.fn(), updateTaskAssignees: vi.fn(),
  updateTaskSupervisor: vi.fn(), watchTask: vi.fn(), unwatchTask: vi.fn(),
  addTaskComment: vi.fn(), fetchLabels: vi.fn(), createLabel: vi.fn(),
}));
vi.mock('@/api/tasks', () => tasksApi);

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() }));
vi.mock('@/api/client', () => ({ default: api }));

vi.mock('@/hooks/useActiveProfile', () => ({ useActiveProfile: () => ({ activeProfile: { id: '7' } }) }));
vi.mock('@/hooks/usePermissions', () => ({ usePermissions: () => ({ atLeast: () => false }) }));

import { CardModal } from '../CardModal';

function task(over: Partial<Task> = {}): Task {
  return {
    id: 5, key: 'T-5', summary: 'Подготовить смету', description: '', task_type: 'task',
    priority: 'medium', status: 'in_progress', progress_percent: 0, reporter: 7,
    assignee: 7, supervisor: null, department: null, project: null, roadmap: null, site: null,
    site_block: null, contractor: null, contractor_worker: null, parent: null, labels: [],
    assignees: [{ user_id: 7, role: 'primary', name: 'Иван Петров', avatar_url: null }],
    watchers: [], due_date: null, start_date: null, completed_at: null,
    created_at: '2026-10-20T09:00:00Z', updated_at: '2026-10-20T09:00:00Z',
    can: { full_edit: true, soft_edit: true, comment: true, request_access: [], decide_access: false },
    checklists: [{
      id: 1, title: 'Приёмка', position: 'V', done: 0, total: 1,
      items: [{ id: 10, text: 'Проверить акт', is_done: false, done_by: null, done_at: null, position: 'V' }],
    }],
    pending_access_requests: 0,
    ...over,
  } as Task;
}

const FEED = {
  items: [
    { kind: 'comment', id: 3, created_at: '2026-10-21T10:00:00Z', updated_at: '2026-10-21T10:00:00Z',
      actor: { id: 8, name: 'Анна Ким', avatar_url: null }, body: 'Смету проверила' },
    { kind: 'activity', id: 4, created_at: '2026-10-21T09:00:00Z', actor: null, field: 'claim',
      old: null, new: '7', old_label: null, new_label: 'Иван Петров' },
    { kind: 'activity', id: 5, created_at: '2026-10-21T08:00:00Z', actor: { id: 9, name: 'Ирина Ли', avatar_url: null },
      field: 'access_approved', old: null, new: 'own:12', old_label: null, new_label: 'Самат Снабженец' },
  ],
  next_before: null,
};

function serve() {
  api.get.mockImplementation((url: string) => {
    if (url.endsWith('/feed')) return Promise.resolve({ data: FEED });
    if (url.endsWith('/access-requests')) return Promise.resolve({ data: [] });
    return Promise.resolve({ data: {} });
  });
  api.post.mockResolvedValue({ data: {} });
}

type Column = Pick<BoardColumn, 'status' | 'title' | 'color' | 'hidden'>;

function renderModal(columns: Column[] = []) {
  const onClose = vi.fn();
  const onMove = vi.fn();
  const { queryClient } = renderWithProviders(
    <CardModal taskId={5} columns={columns} onClose={onClose} onMove={onMove} />,
  );
  return { onClose, onMove, queryClient };
}

/** «Приёмка» после отметки единственного пункта — ответ сервера. */
const CHECKED = {
  id: 1, title: 'Приёмка', position: 'V', done: 1, total: 1,
  items: [{ id: 10, text: 'Проверить акт', is_done: true, done_by: { id: 7, name: 'Иван Петров' },
    done_at: '2026-10-21T10:00:00Z', position: 'V' }],
};

beforeEach(() => {
  vi.clearAllMocks();
  serve();
  tasksApi.fetchLabels.mockResolvedValue([]);
});

describe('CardModal', () => {
  it('название правится на месте и уходит на сервер', async () => {
    tasksApi.fetchTask.mockResolvedValue(task());
    tasksApi.updateTask.mockResolvedValue(task({ summary: 'Смета по объекту' }));
    renderModal();
    await userEvent.click(await screen.findByRole('button', { name: 'Название задачи' }));
    const field = screen.getByRole('textbox', { name: 'Название задачи' });
    await userEvent.clear(field);
    await userEvent.type(field, 'Смета по объекту{Enter}');
    await waitFor(() => expect(tasksApi.updateTask).toHaveBeenCalledWith(5, { summary: 'Смета по объекту' }));
  });

  it('правка в окне перечитывает и старый реестр задач', async () => {
    // Окно открывается и со старой страницы «Задачи» — её список должен
    // показать правку после закрытия окна.
    tasksApi.fetchTask.mockResolvedValue(task());
    tasksApi.updateTask.mockResolvedValue(task({ summary: 'Смета по объекту' }));
    const { queryClient } = renderModal();
    queryClient.setQueryData(['hr-tasks', {}], []);
    queryClient.setQueryData(['employee-tasks', 'my-tasks'], []);
    await userEvent.click(await screen.findByRole('button', { name: 'Название задачи' }));
    await userEvent.type(screen.getByRole('textbox', { name: 'Название задачи' }), '!{Enter}');
    await waitFor(() => expect(queryClient.getQueryState(['hr-tasks', {}])?.isInvalidated).toBe(true));
    expect(queryClient.getQueryState(['employee-tasks', 'my-tasks'])?.isInvalidated).toBe(true);
  });

  it('ведёт на полную страницу задачи', async () => {
    tasksApi.fetchTask.mockResolvedValue(task());
    renderModal();
    expect(await screen.findByRole('link', { name: 'Открыть страницей' })).toHaveAttribute('href', '/tasks/5');
  });

  it('Esc в поле названия отменяет правку, а окно остаётся', async () => {
    tasksApi.fetchTask.mockResolvedValue(task());
    const { onClose } = renderModal();
    await userEvent.click(await screen.findByRole('button', { name: 'Название задачи' }));
    await userEvent.type(screen.getByRole('textbox', { name: 'Название задачи' }), ' лишнее');
    await userEvent.keyboard('{Escape}');
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Название задачи' })).toHaveTextContent('Подготовить смету');
    expect(tasksApi.updateTask).not.toHaveBeenCalled();
  });

  it('Esc в поиске участников закрывает только окно участников', async () => {
    tasksApi.fetchTask.mockResolvedValue(task());
    const { onClose } = renderModal();
    await userEvent.click(await screen.findByRole('button', { name: 'Участники' }));
    const search = await screen.findByPlaceholderText('Найти сотрудника');
    act(() => search.focus());
    await userEvent.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByPlaceholderText('Найти сотрудника')).not.toBeInTheDocument());
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Название задачи' })).toBeInTheDocument();
  });

  it('даты показаны словами, а не ISO-строкой', async () => {
    tasksApi.fetchTask.mockResolvedValue(task({ start_date: '2031-10-23', due_date: '2031-10-30' }));
    renderModal();
    expect(await screen.findByText('23 окт. 2031 — 30 окт. 2031')).toBeInTheDocument();
  });

  it('пункт чек-листа отмечается сразу и уходит на сервер', async () => {
    tasksApi.fetchTask.mockResolvedValue(task());
    api.patch.mockImplementation(() => {
      // Сервер запомнил отметку: перечитанная карточка несёт её.
      tasksApi.fetchTask.mockResolvedValue(task({ checklists: [CHECKED] } as Partial<Task>));
      return Promise.resolve({ data: CHECKED });
    });
    renderModal();
    const section = await screen.findByRole('region', { name: 'Приёмка' });
    expect(within(section).getByText('0%')).toBeInTheDocument();
    await userEvent.click(within(section).getByRole('checkbox', { name: 'Проверить акт' }));
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith('tasks/v1/checklist-items/10', { is_done: true }));
    expect(await within(section).findByText('100%')).toBeInTheDocument();
  });

  it('отметка пункта перечитывает карточку: правило доски перенесло её (S4)', async () => {
    tasksApi.fetchTask.mockResolvedValue(task());
    api.patch.mockImplementation(() => {
      // На сервере сработало правило «Все пункты отмечены — в «Готово»».
      tasksApi.fetchTask.mockResolvedValue(task({ status: 'done', checklists: [CHECKED] } as Partial<Task>));
      return Promise.resolve({ data: CHECKED });
    });
    renderModal([
      { status: 'in_progress', title: 'Исполнение', color: null, hidden: false },
      { status: 'done', title: 'Готово', color: null, hidden: false },
    ]);
    expect(await screen.findByRole('button', { name: 'Исполнение' })).toBeInTheDocument();
    const section = screen.getByRole('region', { name: 'Приёмка' });
    await userEvent.click(within(section).getByRole('checkbox', { name: 'Проверить акт' }));
    expect(await screen.findByRole('button', { name: 'Готово' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Исполнение' })).not.toBeInTheDocument();
  });

  it('комментарий перечитывает карточку: правило доски могло её перенести (S4)', async () => {
    tasksApi.fetchTask.mockResolvedValue(task());
    tasksApi.addTaskComment.mockResolvedValue({ id: 30, body: 'На доработку: смета' });
    renderModal();
    await screen.findByRole('button', { name: 'Название задачи' });
    const before = tasksApi.fetchTask.mock.calls.length;
    const feed = screen.getByRole('region', { name: 'Комментарии и события' });
    await userEvent.type(within(feed).getByPlaceholderText('Напишите комментарий…'), 'На доработку: смета');
    await userEvent.click(within(feed).getByRole('button', { name: 'Сохранить' }));
    await waitFor(() => expect(tasksApi.addTaskComment).toHaveBeenCalledWith(5, 'На доработку: смета'));
    await waitFor(() => expect(tasksApi.fetchTask.mock.calls.length).toBeGreaterThan(before));
  });

  it('лента показывает комментарии и события, событие без автора — автоматизация', async () => {
    tasksApi.fetchTask.mockResolvedValue(task());
    renderModal();
    expect(await screen.findByText('Смету проверила')).toBeInTheDocument();
    expect(screen.getByText('Анна Ким')).toBeInTheDocument();
    expect(screen.getByText('Автоматизация')).toBeInTheDocument();
    // Решение по запросу доступа называет запросившего, а не только вид запроса.
    expect(screen.getByText(/запрос доступа на владение от Самат Снабженец одобрен/)).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith('tasks/v1/tasks/5/feed', { params: { details: '0' } });
    await userEvent.click(screen.getByRole('button', { name: 'Показать подробности' }));
    await waitFor(() => expect(api.get).toHaveBeenCalledWith('tasks/v1/tasks/5/feed',
      { params: { details: '1' } }));
  });

  it('кто не в роли, просит доступ на владение', async () => {
    tasksApi.fetchTask.mockResolvedValue(task({
      assignees: [], assignee: null,
      can: { full_edit: false, soft_edit: false, comment: true, request_access: ['execute', 'own'],
        decide_access: false },
    }));
    api.post.mockResolvedValue({ data: { id: 9, status: 'pending' } });
    renderModal();
    await userEvent.click(await screen.findByRole('button', { name: 'Запросить доступ' }));
    const dialog = await screen.findByRole('dialog', { name: 'Запросить доступ к задаче' });
    await userEvent.click(within(dialog).getByText('Доступ на владение'));
    await userEvent.click(within(dialog).getByRole('button', { name: 'Отправить запрос' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('tasks/v1/tasks/5/access-requests',
      { kind: 'own', comment: '' }));
    // Без права правки название — просто текст.
    expect(screen.queryByRole('button', { name: 'Название задачи' })).not.toBeInTheDocument();
  });

  it('недоступная карточка закрывает окно с объяснением', async () => {
    tasksApi.fetchTask.mockRejectedValue(Object.assign(new Error('404'),
      { response: { status: 404, data: { detail: 'Task not found' } } }));
    const { onClose } = renderModal();
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(toast.error).toHaveBeenCalled();
  });

  it('открытие отмечает задачу просмотренной', async () => {
    tasksApi.fetchTask.mockResolvedValue(task());
    renderModal();
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('tasks/v1/tasks/5/seen'));
  });
});
