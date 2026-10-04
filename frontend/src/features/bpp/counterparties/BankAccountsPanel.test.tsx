/**
 * Банковские счета контрагента: добавление идёт с `Idempotency-Key`,
 * неверный IBAN ловится до запроса тем же правилом, что на сервере, отказ
 * сервера по полю (E-CTR-04) показывается у поля, архив — `is_active: false`
 * (удаления нет).
 */
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';

import type { BankAccount } from './api';
import { BankAccountsPanel } from './BankAccountsPanel';

const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
const patch = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get, post, patch } }));

const toastError = vi.hoisted(() => vi.fn());
vi.mock('sonner', () => ({ toast: { error: toastError, success: vi.fn(), info: vi.fn() } }));

const CP = 'cp-1';
const GOOD_IBAN = 'KZ86125KZT5004100100';
const BAD_IBAN = 'KZ87125KZT5004100100'; // контрольные цифры не сходятся

const ACCOUNT: BankAccount = {
  id: 'acc-1', counterparty_id: CP, iban: GOOD_IBAN, bank_name: 'Халык Банк', bic: 'HSBKKZKX',
  currency: 'KZT', is_primary: true, is_active: true,
  created_at: '2026-09-01T00:00:00Z', updated_at: '2026-09-01T00:00:00Z',
};

let user: ReturnType<typeof userEvent.setup>;

beforeEach(() => {
  user = userEvent.setup();
  get.mockReset();
  post.mockReset();
  patch.mockReset();
  toastError.mockReset();
});

function renderPanel(accounts: BankAccount[] = [], onChanged = vi.fn()) {
  renderWithProviders(
    <BankAccountsPanel counterpartyId={CP} accounts={accounts} canEdit onChanged={onChanged} />,
  );
  return onChanged;
}

async function fillAccount(iban: string) {
  await user.click(screen.getByRole('button', { name: 'Добавить счёт' }));
  await user.type(screen.getByLabelText('IBAN'), iban);
  await user.type(screen.getByLabelText('БИК'), 'HSBKKZKX');
  await user.type(screen.getByLabelText('Банк'), 'Халык Банк');
}

describe('BankAccountsPanel', () => {
  it('добавляет счёт с ключом идемпотентности и просит перечитать карточку', async () => {
    post.mockResolvedValue({ data: ACCOUNT });
    const onChanged = renderPanel();

    await fillAccount(GOOD_IBAN);
    await user.click(screen.getByRole('button', { name: 'Добавить' }));

    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
    const [url, body, config] = post.mock.calls[0];
    expect(url).toContain(`counterparties/${CP}/accounts`);
    expect(body).toMatchObject({
      iban: GOOD_IBAN, bic: 'HSBKKZKX', bank_name: 'Халык Банк', currency: 'KZT', is_primary: false,
    });
    expect(config.headers['Idempotency-Key']).toBeTruthy();
    // Форма закрылась — снова кнопка «Добавить счёт».
    expect(screen.getByRole('button', { name: 'Добавить счёт' })).toBeInTheDocument();
  });

  it('неверный IBAN — отказ у поля, запроса нет', async () => {
    const onChanged = renderPanel();

    await fillAccount(BAD_IBAN);
    await user.click(screen.getByRole('button', { name: 'Добавить' }));

    expect(await screen.findByText(/IBAN «KZ87125KZT5004100100» неверен/)).toBeInTheDocument();
    expect(screen.getByLabelText('IBAN')).toHaveAttribute('aria-invalid', 'true');
    expect(post).not.toHaveBeenCalled();
    expect(onChanged).not.toHaveBeenCalled();
  });

  it('отказ сервера по полю (E-CTR-04) — текст у поля, без всплывашки', async () => {
    post.mockRejectedValue({
      response: {
        status: 422,
        data: {
          detail: 'Счёт отклонён', code: 'E-CTR-04',
          fields: [{ field: 'iban', message: 'Такой счёт у контрагента уже есть' }],
        },
      },
    });
    renderPanel();

    await fillAccount(GOOD_IBAN);
    await user.click(screen.getByRole('button', { name: 'Добавить' }));

    expect(await screen.findByText('Такой счёт у контрагента уже есть')).toBeInTheDocument();
    expect(toastError).not.toHaveBeenCalled();
  });

  it('«В архив» — PATCH is_active: false, счёт не удаляется', async () => {
    patch.mockResolvedValue({ data: { ...ACCOUNT, is_active: false } });
    const onChanged = renderPanel([ACCOUNT]);

    const row = screen.getByRole('row', { name: new RegExp(GOOD_IBAN) });
    await user.click(within(row).getByRole('button', { name: 'В архив' }));

    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
    const [url, body, config] = patch.mock.calls[0];
    expect(url).toContain('counterparties/accounts/acc-1');
    expect(body).toEqual({ is_active: false });
    expect(config.headers['Idempotency-Key']).toBeTruthy();
  });

  it('архивный счёт — без действий, с отметкой «Архив»', () => {
    renderPanel([{ ...ACCOUNT, is_active: false, is_primary: false }]);

    const row = screen.getByRole('row', { name: new RegExp(GOOD_IBAN) });
    expect(within(row).getByText('Архив')).toBeInTheDocument();
    expect(within(row).queryByRole('button')).toBeNull();
  });
});
