/**
 * Диалог «Отправить в отдел» (канбан K1.7, спека §K1.5 «Фронт», мастер-план K-08).
 *
 * Список целей — справочник отделов без текущего отдела задачи и без
 * неактивных: перенос в тот же отдел сервер отвергает (`task_transfer_same`),
 * в закрытый — тоже (`task_department_inactive`), и показывать такие пункты
 * значит предлагать заведомый отказ. Отказ сервера показывается в самом
 * диалоге: текст по `code` из словаря, а если словарь кода не знает —
 * `detail` сервера.
 */
import React from 'react';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';

vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

const fetchDepartments = vi.hoisted(() => vi.fn());
vi.mock('@/api/hr', () => ({ fetchDepartments: () => fetchDepartments() }));
const transferTask = vi.fn();
vi.mock('@/api/tasks', () => ({
  transferTask: (id: number, body: unknown) => transferTask(id, body),
}));

import { TransferDialog } from '../TransferDialog';

const DEPARTMENTS = [
  { id: 1, name: 'ИТ', description: '', created_at: '', is_active: true },
  { id: 2, name: 'Эксплуатация', description: '', created_at: '', is_active: true },
  { id: 3, name: 'Закрытый отдел', description: '', created_at: '', is_active: false },
];

const renderDialog = (department: number | null = 1) => {
  const onOpenChange = vi.fn();
  const view = renderWithProviders(
    <TransferDialog task={{ id: 5, key: 'T-5', department }} open onOpenChange={onOpenChange} />,
  );
  return { ...view, onOpenChange };
};

beforeEach(() => {
  vi.clearAllMocks();
  fetchDepartments.mockResolvedValue(DEPARTMENTS);
});

describe('TransferDialog', () => {
  it('не предлагает текущий и неактивные отделы', async () => {
    renderDialog();
    expect(await screen.findByText('Эксплуатация')).toBeInTheDocument();
    expect(screen.queryByText('ИТ')).not.toBeInTheDocument();
    expect(screen.queryByText('Закрытый отдел')).not.toBeInTheDocument();
  });

  it('предупреждает, что исполнители будут сняты', async () => {
    renderDialog();
    expect(await screen.findByText(/Исполнители будут сняты/)).toBeInTheDocument();
  });

  it('отправляет выбранный отдел и закрывается', async () => {
    transferTask.mockResolvedValue({ id: 5 });
    const { onOpenChange } = renderDialog();
    const submit = screen.getByRole('button', { name: 'Отправить' });
    expect(submit).toBeDisabled();

    await userEvent.click(await screen.findByText('Эксплуатация'));
    await userEvent.click(submit);

    await waitFor(() => expect(transferTask).toHaveBeenCalledWith(5, { department_id: 2 }));
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
  });

  it('показывает текст отказа по коду ошибки', async () => {
    transferTask.mockRejectedValue({
      response: { status: 403, data: { detail: 'server text', code: 'task_transfer_forbidden' } },
    });
    renderDialog();
    await userEvent.click(await screen.findByText('Эксплуатация'));
    await userEvent.click(screen.getByRole('button', { name: 'Отправить' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Переносить задачу может глава её отдела');
  });

  it('незнакомый код — текст сервера', async () => {
    transferTask.mockRejectedValue({
      response: { status: 422, data: { detail: 'Сервер объяснил причину', code: 'unknown_code' } },
    });
    renderDialog();
    await userEvent.click(await screen.findByText('Эксплуатация'));
    await userEvent.click(screen.getByRole('button', { name: 'Отправить' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Сервер объяснил причину');
  });

  it('у задачи без отдела предлагает выбрать отдел-отправитель', async () => {
    renderDialog(null);
    // Цель — любой действующий отдел: текущего у задачи нет.
    expect((await screen.findAllByText('ИТ')).length).toBeGreaterThan(0);
    expect(screen.getByText('Отдел-отправитель')).toBeInTheDocument();
  });
});
