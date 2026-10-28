/**
 * Свои поля доски в окне карточки (решение K-35, этап S3): значение правит
 * тот, кто ведёт задачу; текст — по Enter, флажок и список — сразу; кнопка
 * «Чек-лист» копирует пункты шаблона домашней доски; лента называет поле.
 */
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';
import type { Task, TaskHomeBoard } from '@/types/tasks';

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

const field = (over: Record<string, unknown>) => ({
  board_kind: 'department', board_id: 3, options: [], show_on_card: false, position: 'V',
  value: null, ...over,
});

const HOME: TaskHomeBoard[] = [{
  kind: 'department', id: 3, title: 'Отдел ИТ',
  fields: [
    field({ id: 1, name: 'Причина ожидания', type: 'text' }),
    field({ id: 2, name: 'Объём', type: 'number' }),
    field({ id: 3, name: 'Срочно', type: 'checkbox', value: false }),
    field({ id: 4, name: 'Этап', type: 'list', options: [
      { id: 'a1', name: 'Проект', color: 'blue' }, { id: 'b2', name: 'Стройка', color: null }] }),
  ] as TaskHomeBoard['fields'],
  checklist_templates: [{ id: 't1', title: 'Приёмка', items: ['Проверить', 'Сдать'] }],
}];

function task(over: Partial<Task> = {}): Task {
  return {
    id: 5, key: 'T-5', summary: 'Подготовить смету', description: '', task_type: 'task',
    priority: 'medium', status: 'in_progress', progress_percent: 0, labels: [],
    assignees: [{ user_id: 7, role: 'primary', name: 'Иван Петров', avatar_url: null }],
    watchers: [], due_date: null, start_date: null, completed_at: null,
    created_at: '2026-10-20T09:00:00Z', updated_at: '2026-10-20T09:00:00Z',
    can: { full_edit: true, soft_edit: true, comment: true, request_access: [], decide_access: false },
    checklists: [], pending_access_requests: 0, home_boards: HOME,
    ...over,
  } as Task;
}

const FEED = {
  items: [
    { kind: 'activity', id: 4, created_at: '2026-10-21T09:00:00Z',
      actor: { id: 7, name: 'Иван Петров', avatar_url: null }, field: 'field:1',
      old: null, new: 'Ждём смету', old_label: null, new_label: null,
      board_field: { id: 1, name: 'Причина ожидания', type: 'text' } },
    { kind: 'activity', id: 5, created_at: '2026-10-21T08:00:00Z',
      actor: { id: 7, name: 'Иван Петров', avatar_url: null }, field: 'field:3',
      old: null, new: 'true', old_label: null, new_label: null,
      board_field: { id: 3, name: 'Срочно', type: 'checkbox' } },
    { kind: 'activity', id: 6, created_at: '2026-10-21T07:00:00Z',
      actor: { id: 7, name: 'Иван Петров', avatar_url: null }, field: 'field:9',
      old: 'Старое', new: null, old_label: null, new_label: null,
      board_field: { id: 9, name: null, type: null } },
    { kind: 'activity', id: 7, created_at: '2026-10-21T06:00:00Z',
      actor: { id: 7, name: 'Иван Петров', avatar_url: null }, field: 'due_date',
      old: null, new: '2031-10-30', old_label: null, new_label: null, board_field: null },
    // Правило — без автора, кнопка — от нажавшего (этап S4).
    { kind: 'activity', id: 8, created_at: '2026-10-21T05:00:00Z', actor: null,
      field: 'status', old: 'in_progress', new: 'done', old_label: null, new_label: null,
      board_field: null, automation: { id: 3, name: 'Все пункты — в «Готово»' } },
    { kind: 'activity', id: 9, created_at: '2026-10-21T04:00:00Z',
      actor: { id: 7, name: 'Иван Петров', avatar_url: null }, field: 'status',
      old: 'todo', new: 'in_progress', old_label: null, new_label: null, board_field: null,
      automation: { id: 4, name: 'Взять в работу' } },
  ],
  next_before: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  api.get.mockImplementation((url: string) => {
    if (url.endsWith('/feed')) return Promise.resolve({ data: FEED });
    if (url.endsWith('/access-requests')) return Promise.resolve({ data: [] });
    return Promise.resolve({ data: {} });
  });
  api.put.mockResolvedValue({ data: { home_boards: HOME } });
  tasksApi.fetchLabels.mockResolvedValue([]);
});

function renderModal() {
  return renderWithProviders(
    <CardModal taskId={5} columns={[]} onClose={vi.fn()} onMove={vi.fn()} />,
  );
}

describe('поля доски в окне карточки', () => {
  it('текст сохраняется по Enter, пустое число не уходит', async () => {
    tasksApi.fetchTask.mockResolvedValue(task());
    renderModal();
    const block = await screen.findByTestId('card-fields-department-3');
    await userEvent.type(within(block).getByRole('textbox', { name: 'Причина ожидания' }),
      '  Ждём смету {Enter}');
    await waitFor(() => expect(api.put).toHaveBeenCalledWith('tasks/v1/tasks/5/fields/1',
      { value: 'Ждём смету' }));
    const number = within(block).getByRole('textbox', { name: 'Объём' });
    await userEvent.type(number, '12х{Enter}');
    expect(await within(block).findByText('Введите число, например 1250,5')).toBeInTheDocument();
    expect(api.put).toHaveBeenCalledTimes(1);
    await userEvent.clear(number);
    await userEvent.type(number, '1 250,5{Enter}');
    await waitFor(() => expect(api.put).toHaveBeenCalledWith('tasks/v1/tasks/5/fields/2',
      { value: '1 250,5' }));
  });

  it('флажок и список сохраняются сразу', async () => {
    tasksApi.fetchTask.mockResolvedValue(task());
    renderModal();
    const block = await screen.findByTestId('card-fields-department-3');
    await userEvent.click(within(block).getByRole('checkbox'));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith('tasks/v1/tasks/5/fields/3',
      { value: true }));
    await userEvent.click(within(block).getByRole('button', { name: 'Этап' }));
    await userEvent.click(await screen.findByRole('menuitem', { name: 'Стройка' }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith('tasks/v1/tasks/5/fields/4',
      { value: 'b2' }));
  });

  it('без права вести задачу поля только для чтения', async () => {
    tasksApi.fetchTask.mockResolvedValue(task({
      can: { full_edit: false, soft_edit: false, comment: true, request_access: [], decide_access: false },
    }));
    renderModal();
    const block = await screen.findByTestId('card-fields-department-3');
    expect(within(block).getByRole('textbox', { name: 'Причина ожидания' })).toBeDisabled();
    expect(within(block).getByRole('checkbox')).toBeDisabled();
    expect(within(block).getByRole('button', { name: 'Этап' })).toBeDisabled();
  });

  it('без полей у домашних досок блока нет', async () => {
    tasksApi.fetchTask.mockResolvedValue(task({ home_boards: [{ ...HOME[0], fields: [] }] }));
    renderModal();
    await screen.findByRole('button', { name: 'Название задачи' });
    expect(screen.queryByTestId('card-fields-department-3')).not.toBeInTheDocument();
  });

  it('чек-лист копирует пункты шаблона домашней доски', async () => {
    tasksApi.fetchTask.mockResolvedValue(task());
    api.post.mockResolvedValue({ data: { id: 8, title: 'Приёмка', position: 'V', done: 0, total: 2,
      items: [] } });
    renderModal();
    await userEvent.click(await screen.findByRole('button', { name: 'Чек-лист' }));
    await userEvent.click(await screen.findByRole('combobox', { name: 'Скопировать пункты из…' }));
    await userEvent.click(await screen.findByRole('option', { name: 'Приёмка · 2' }));
    expect(screen.getByRole('textbox', { name: 'Название' })).toHaveValue('Приёмка');
    await userEvent.click(screen.getByRole('button', { name: 'Добавить' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('tasks/v1/tasks/5/checklists', {
      title: 'Приёмка',
      template: { board_kind: 'department', board_id: 3, template_id: 't1' },
    }));
  });

  it('лента называет поле, флажок и удалённое поле, срок — словами', async () => {
    tasksApi.fetchTask.mockResolvedValue(task());
    renderModal();
    expect(await screen.findByText(/поле «Причина ожидания»: — → Ждём смету/)).toBeInTheDocument();
    expect(screen.getByText(/флажок «Срочно» отмечен/)).toBeInTheDocument();
    expect(screen.getByText(/поле «удалённое поле» очищено \(было: Старое\)/)).toBeInTheDocument();
    // Срок — словами, как на доске, а не ISO-строкой.
    expect(screen.getByText(/срок — 30 окт\. 2031/)).toBeInTheDocument();
  });

  it('правка автоматизации подписана правилом, кнопка — ещё и нажавшим', async () => {
    tasksApi.fetchTask.mockResolvedValue(task());
    renderModal();
    expect(await screen.findByText('Автоматизация «Все пункты — в «Готово»»')).toBeInTheDocument();
    expect(screen.getByText('(через автоматизацию «Взять в работу»)', { exact: false }))
      .toBeInTheDocument();
  });
});
