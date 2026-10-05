/**
 * Вкладка «Счета организации»: правка счёта уходит `PATCH` только
 * изменённых полей с `version` (так счёт переводят на другой шаблон), дубль
 * IBAN (E-BNK-01) показывает у поля полный текст отказа сервера; без права
 * правки кнопок записи нет; валюта — выбор из действующих валют справочника
 * (архивная валюта счёта в правке видна выбранной), пустой справочник —
 * подсказка со ссылкой.
 */
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';

import { AccountsTab } from './AccountsTab';
import type { Currency } from '../refdata/api';

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

const currency = (code: string, name: string): Currency => ({
  id: `cur-${code}`, code, name, symbol: '', is_active: true, can_edit: false,
});

const currencies = vi.hoisted(() => ({ value: [] as Currency[] }));

let user: ReturnType<typeof userEvent.setup>;

beforeEach(() => {
  user = userEvent.setup();
  get.mockReset();
  post.mockReset();
  patch.mockReset();
  toastError.mockReset();
  currencies.value = [currency('KZT', 'Тенге'), currency('USD', 'Доллар США')];
  get.mockImplementation((url: string) => {
    if (url.endsWith('currencies')) return Promise.resolve({ data: currencies.value });
    return Promise.resolve({
      data: url.endsWith('templates')
        ? [template('tpl-1', 'Халык CSV'), template('tpl-2', 'Kaspi Excel')]
        : [ACCOUNT],
    });
  });
});

const currencyCalls = () => get.mock.calls.filter(([url]) => String(url).endsWith('currencies'));

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
  it('валюта — выбор из действующих валют справочника, новый счёт — в тенге', async () => {
    post.mockResolvedValue({ data: { ...ACCOUNT, id: 'acc-2' } });
    renderWithProviders(<AccountsTab canEdit />);

    await user.click(await screen.findByRole('button', { name: 'Добавить счёт' }));
    const form = screen.getByRole('form', { name: 'Новый счёт организации' });
    const select = within(form).getByRole('combobox', { name: 'Валюта' });
    await waitFor(() => expect(select).toHaveTextContent('KZT — Тенге'));
    expect(currencyCalls()[0][1].params).toEqual({ active: '1' });

    await user.click(select);
    expect(await screen.findByRole('option', { name: 'USD — Доллар США' })).toBeInTheDocument();
    await user.click(screen.getByRole('option', { name: 'USD — Доллар США' }));
    await user.type(within(form).getByLabelText('IBAN'), 'KZ86125KZT5004100100');
    await user.type(within(form).getByLabelText('БИК'), 'HSBKKZKX');
    await user.click(within(form).getByRole('combobox', { name: 'Шаблон выписки' }));
    await user.click(await screen.findByRole('option', { name: 'Халык CSV' }));
    await user.click(within(form).getByRole('button', { name: 'Добавить' }));

    await waitFor(() => expect(post).toHaveBeenCalled());
    expect(post.mock.calls[0][1]).toMatchObject({ currency: 'USD', template_id: 'tpl-1' });
  });

  it('архивная валюта счёта в правке видна выбранной и без правки не уходит', async () => {
    patch.mockResolvedValue({ data: { ...ACCOUNT, version: 5 } });
    get.mockImplementation((url: string) => {
      if (url.endsWith('currencies')) return Promise.resolve({ data: currencies.value });
      return Promise.resolve({
        data: url.endsWith('templates')
          ? [template('tpl-1', 'Халык CSV')]
          : [{ ...ACCOUNT, currency: 'RUB' }],
      });
    });
    renderWithProviders(<AccountsTab canEdit />);

    await user.click(await screen.findByRole('button', { name: 'Изменить' }));
    const form = screen.getByRole('form', { name: 'Счёт KZ86125KZT5004100100' });
    expect(within(form).getByRole('combobox', { name: 'Валюта' })).toHaveTextContent('RUB (архив)');

    await user.clear(within(form).getByLabelText('Банк'));
    await user.type(within(form).getByLabelText('Банк'), 'Halyk');
    await user.click(within(form).getByRole('button', { name: 'Сохранить' }));

    await waitFor(() => expect(patch).toHaveBeenCalled());
    expect(patch.mock.calls[0][1]).toEqual({ bank_name: 'Halyk', version: 4 });
  });

  it('действующих валют нет — подсказка со ссылкой на справочник, без валюты не отправить', async () => {
    currencies.value = [];
    renderWithProviders(<AccountsTab canEdit />);

    await user.click(await screen.findByRole('button', { name: 'Добавить счёт' }));
    const form = screen.getByRole('form', { name: 'Новый счёт организации' });
    expect(await within(form).findByText(/Действующих валют в справочнике нет/)).toBeInTheDocument();
    expect(within(form).getByRole('link', { name: 'Справочники' }))
      .toHaveAttribute('href', '/bpp/refdata?tab=currencies');
    expect(within(form).getByRole('combobox', { name: 'Валюта' })).toBeDisabled();

    await user.type(within(form).getByLabelText('IBAN'), 'KZ86125KZT5004100100');
    await user.type(within(form).getByLabelText('БИК'), 'HSBKKZKX');
    await user.click(within(form).getByRole('combobox', { name: 'Шаблон выписки' }));
    await user.click(await screen.findByRole('option', { name: 'Халык CSV' }));
    await user.click(within(form).getByRole('button', { name: 'Добавить' }));

    expect(await within(form).findByText('Выберите валюту счёта')).toBeInTheDocument();
    expect(post).not.toHaveBeenCalled();
  });

  it('без права правки — ни «Добавить счёт», ни «Изменить», ни «В архив»', async () => {
    renderWithProviders(<AccountsTab canEdit={false} />);
    expect(await screen.findByText('KZ86125KZT5004100100')).toBeInTheDocument();

    expect(screen.queryByRole('button', { name: 'Добавить счёт' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Изменить' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'В архив' })).toBeNull();
    expect(currencyCalls()).toHaveLength(0);  // формы нет — справочник не нужен
  });
});
