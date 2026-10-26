/**
 * Вкладка «Поля» настроек доски (K-35, этап S3): новое поле-список с
 * вариантами, место среди полей стрелками, удаление — только после
 * подтверждения, потому что уносит значения у всех задач доски.
 */
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';

const toast = vi.hoisted(() => ({ error: vi.fn(), success: vi.fn(), info: vi.fn() }));
vi.mock('sonner', () => ({ toast }));

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() }));
vi.mock('@/api/client', () => ({ default: api }));

import { FieldsTab } from '../FieldsTab';

const FIELDS = [
  { id: 1, board_kind: 'department', board_id: 3, name: 'Причина ожидания', type: 'text',
    options: [], show_on_card: false, position: 'V' },
  { id: 2, board_kind: 'department', board_id: 3, name: 'Взята в работу', type: 'date',
    options: [], show_on_card: true, position: 'k' },
  { id: 3, board_kind: 'department', board_id: 3, name: 'Этап', type: 'list',
    options: [{ id: 'a1', name: 'Проект', color: 'blue' }], show_on_card: false, position: 'r' },
];

beforeEach(() => {
  vi.clearAllMocks();
  api.get.mockResolvedValue({ data: FIELDS });
  api.post.mockResolvedValue({ data: FIELDS[0] });
  api.patch.mockResolvedValue({ data: FIELDS[0] });
  api.delete.mockResolvedValue({ data: null });
});

const renderTab = () => renderWithProviders(<FieldsTab boardKey={{ kind: 'department', id: 3 }} />);

describe('FieldsTab', () => {
  it('создаёт поле-список с вариантами', async () => {
    renderTab();
    await userEvent.click(await screen.findByRole('button', { name: 'Новое поле' }));
    await userEvent.type(screen.getByRole('textbox', { name: 'Название поля' }), 'Срочность');
    await userEvent.click(screen.getByRole('combobox', { name: 'Тип поля' }));
    await userEvent.click(await screen.findByRole('option', { name: 'Список' }));
    await userEvent.click(screen.getByRole('button', { name: 'Вариант' }));
    await userEvent.type(screen.getByRole('textbox', { name: 'Вариант 1' }), 'Горит');
    await userEvent.click(screen.getByRole('switch', { name: 'Показывать на карточке' }));
    await userEvent.click(screen.getByRole('button', { name: 'Создать' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('tasks/v1/boards/departments/3/fields', {
      name: 'Срочность', type: 'list', show_on_card: true,
      options: [{ name: 'Горит', color: null }],
    }));
  });

  it('повтор варианта не даёт сохранить, причина — после попытки', async () => {
    renderTab();
    await userEvent.click(await screen.findByRole('button', { name: 'Изменить «Этап»' }));
    await userEvent.click(screen.getByRole('button', { name: 'Вариант' }));
    // Новый вариант сразу принимает ввод.
    expect(screen.getByRole('textbox', { name: 'Вариант 2' })).toHaveFocus();
    await userEvent.keyboard('проект');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Варианты списка не должны повторяться');
    expect(api.patch).not.toHaveBeenCalled();
  });

  it('стрелка «Выше» ставит поле между соседями', async () => {
    renderTab();
    const row = await screen.findByTestId('board-field-3');
    await userEvent.click(within(row).getByRole('button', { name: 'Выше' }));
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith('tasks/v1/boards/fields/3',
      { before_id: 1, after_id: 2 }));
  });

  it('удаление — только после подтверждения', async () => {
    renderTab();
    await userEvent.click(await screen.findByRole('button', { name: 'Удалить «Причина ожидания»' }));
    expect(api.delete).not.toHaveBeenCalled();
    const confirm = screen.getByRole('alert');
    expect(confirm).toHaveTextContent('Его значения у всех задач доски тоже удалятся');
    await userEvent.click(within(confirm).getByRole('button', { name: 'Удалить' }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith('tasks/v1/boards/fields/1'));
  });
});
