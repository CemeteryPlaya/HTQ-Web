/**
 * Вкладка «Шаблоны выписок»: без права правки кнопок записи нет (только
 * «Открыть»); после сохранения редактор берёт значения из ответа сервера —
 * приведённая сервером кодировка не оставляет шаблон «изменённым».
 */
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';

import type { StatementTemplate } from './api';
import { TemplatesTab } from './TemplatesTab';

const get = vi.hoisted(() => vi.fn());
const patch = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get, post: vi.fn(), patch } }));

vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() } }));

const SAVED: StatementTemplate = {
  id: 'tpl-1', name: 'Халык CSV', format: 'csv', encoding: 'cp1251', delimiter: ';',
  date_format: 'ДД.ММ.ГГГГ', amount_mode: 'signed', is_active: true, active_accounts: 1, version: 3,
  columns: { date: 'Дата', doc_number: 'Номер', amount: 'Сумма', purpose: 'Назначение' },
};

let user: ReturnType<typeof userEvent.setup>;

beforeEach(() => {
  user = userEvent.setup();
  get.mockReset();
  patch.mockReset();
  get.mockResolvedValue({ data: [SAVED] });
});

describe('TemplatesTab', () => {
  it('без права правки — ни «Создать», ни «В архив», шаблон открывается только для чтения', async () => {
    renderWithProviders(<TemplatesTab canEdit={false} />);
    await screen.findByText('Халык CSV');

    expect(screen.queryByRole('button', { name: 'Создать шаблон' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'В архив' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Изменить' })).toBeNull();

    await user.click(screen.getByRole('button', { name: 'Открыть' }));
    expect(screen.getByLabelText('Название')).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Сохранить' })).toBeNull();
  });

  it('после сохранения форма — по ответу сервера: несохранённых изменений нет, образец проверяется', async () => {
    patch.mockResolvedValue({ data: { ...SAVED, encoding: 'utf-8', version: 4 } });
    renderWithProviders(<TemplatesTab canEdit />);

    await user.click(await screen.findByRole('button', { name: 'Изменить' }));
    const encoding = screen.getByLabelText('Кодировка');
    await user.clear(encoding);
    await user.type(encoding, 'UTF8');
    expect(screen.getByText(/Есть несохранённые изменения/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Сохранить' }));
    await waitFor(() => expect(patch).toHaveBeenCalled());

    await waitFor(() => expect(screen.getByLabelText('Кодировка')).toHaveValue('utf-8'));
    expect(screen.queryByText(/Есть несохранённые изменения/)).toBeNull();
    expect(screen.getByLabelText('Образец выписки')).toBeInTheDocument();

    // Следующее сохранение идёт уже с новой версией.
    patch.mockResolvedValue({ data: { ...SAVED, encoding: 'utf-8', name: 'Халык CSV 2', version: 5 } });
    await user.type(screen.getByLabelText('Название'), ' 2');
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));
    await waitFor(() => expect(patch).toHaveBeenCalledTimes(2));
    expect(patch.mock.calls[1][1]).toMatchObject({ version: 4 });
  });
});
