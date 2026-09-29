/**
 * Вкладка «Счета организации»: правка счёта уходит `PATCH` только
 * изменённых полей с `version` (так счёт переводят на другой шаблон), дубль
 * IBAN (E-BNK-01) показывает у поля полный текст отказа сервера; без права
 * правки кнопок записи нет.
 */
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';

import { AccountsTab } from './AccountsTab';
import type { OrgAccount, StatementTemplate } from './api';

const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
const patch = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get, post, patch } }));

const toastError = vi.hoisted(() => vi.fn());
vi.mock('sonner', () => ({ toast: { error: toastError, success: vi.fn(), info: vi.fn() } }));

const template = (id: string, name: string): StatementTemplate => ({
  id, name, format: 'csv', encoding: 'cp1251', delimiter: ';', date_format: 'ДД.ММ.ГГГГ',
  amount_mode: 'signed', is_active: true, active_accounts: 1, version: 1,
  columns: { date: 'Дата', doc_number: 'Номер', amount: 'Сумма', purpose: 'Назначение' },
});

const ACCOUNT: OrgAccount = {
  id: 'acc-1', iban: 'KZ86125KZT5004100100', bank_name: 'Халык Банк', bic: 'HSBKKZKX',
  currency: 'KZT', template: { id: 'tpl-1', name: 'Халык CSV', format: 'csv' },
  is_active: true, version: 4,
};

let user: ReturnType<typeof userEvent.setup>;

beforeEach(() => {
  user = userEvent.setup();
  get.mockReset();
  post.mockReset();
  patch.mockReset();
  toastError.mockReset();
  get.mockImplementation((url: string) => Promise.resolve({
    data: url.endsWith('templates')
      ? [template('tpl-1', 'Халык CSV'), template('tpl-2', 'Kaspi Excel')]
      : [ACCOUNT],
  }));
});

describe('AccountsTab', () => {
  it('«Изменить» — PATCH только изменённого шаблона с версией счёта', async () => {
    patch.mockResolvedValue({ data: { ...ACCOUNT, version: 5 } });
    renderWithProviders(<AccountsTab canEdit />);

    await user.click(await screen.findByRole('button', { name: 'Изменить' }));
    const form = screen.getByRole('form', { name: 'Счёт KZ86125KZT5004100100' });
    expect(within(form).getByLabelText('IBAN')).toHaveValue('KZ86125KZT5004100100');

    await user.click(within(form).getByRole('combobox', { name: 'Шаблон выписки' }));
    await user.click(await screen.findByRole('option', { name: 'Kaspi Excel' }));
    await user.click(within(form).getByRole('button', { name: 'Сохранить' }));

    await waitFor(() => expect(patch).toHaveBeenCalled());
    const [url, body, config] = patch.mock.calls[0];
    expect(url).toBe('bpp/v1/bank/accounts/acc-1');
    expect(body).toEqual({ template_id: 'tpl-2', version: 4 });
    expect(config.headers['Idempotency-Key']).toBeTruthy();
    await waitFor(() => expect(screen.queryByRole('form')).toBeNull());
  });

  it('дубль IBAN (E-BNK-01) — полный текст отказа у поля IBAN', async () => {
    const detail = 'Счёт организации KZ86125KZT5004100100 (в архиве) уже заведён. Верните его из архива.';
    post.mockRejectedValue({
      response: {
        status: 422,
        data: {
          detail, code: 'E-BNK-01',
          fields: [{ field: 'iban', message: 'IBAN уже заведён', existing_id: 'acc-0' }],
        },
      },
    });
    renderWithProviders(<AccountsTab canEdit />);

    await user.click(await screen.findByRole('button', { name: 'Добавить счёт' }));
    const form = screen.getByRole('form', { name: 'Новый счёт организации' });
    await user.type(within(form).getByLabelText('IBAN'), 'KZ86125KZT5004100100');
    await user.type(within(form).getByLabelText('БИК'), 'HSBKKZKX');
    await user.click(within(form).getByRole('combobox', { name: 'Шаблон выписки' }));
    await user.click(await screen.findByRole('option', { name: 'Халык CSV' }));
    await user.click(within(form).getByRole('button', { name: 'Добавить' }));

    expect(await screen.findByText(detail)).toBeInTheDocument();
    expect(toastError).not.toHaveBeenCalled();
  });
  it('без права правки — ни «Добавить счёт», ни «Изменить», ни «В архив»', async () => {
    renderWithProviders(<AccountsTab canEdit={false} />);
    expect(await screen.findByText('KZ86125KZT5004100100')).toBeInTheDocument();

    expect(screen.queryByRole('button', { name: 'Добавить счёт' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Изменить' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'В архив' })).toBeNull();
  });
});
