/**
 * Реестр L-06 (ТЗ §10.5): вкладка — параметр `tab` запроса и адреса страницы
 * (ссылки дашборда и сводки открывают нужную вкладку); ФД на вкладке
 * «На решение ФД» не оплачивает отмеченные без причины и видит итог по
 * каждому счёту.
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { createTestQueryClient } from '@/test/renderWithProviders';

import type { InvoiceRow } from './api';
import { InvoicesPage } from './InvoicesPage';

const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get, post } }));
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() } }));
vi.mock('@/hooks/usePermissions', () => ({
  usePermissions: () => ({ can: () => true, atLeast: () => true }),
}));

const ROW: InvoiceRow = {
  id: 'inv1', number: 'СЧ-2026-000001', status: 'under_review', created_at: '2026-09-28T05:00:00Z',
  author_name: 'Иванов А.', basis: 'no_contract', agreement_number: null, project_code: 'П-015',
  article_name: 'Металлопрокат', counterparty_name: 'ТОО «Альфа»',
  counterparty_reg_number: '100000000001', counterparty_blocked: false, ext_number: '77',
  ext_date: '2026-09-27', amount: '1000.00', currency_code: 'KZT', amount_kzt: '1000.00',
  due_date: '2026-10-10', planned_pay_date: null, overdue: false, docs_required: {},
  days_waiting_docs: null, recon_status: 'no_data', paid_bank_amount: '0.00',
  possible_split: true, current_holders: null,
};

function LocationProbe() {
  return <output data-testid="search">{useLocation().search}</output>;
}

const renderAt = (entry = '/bpp/invoices') => render(
  <QueryClientProvider client={createTestQueryClient()}>
    <MemoryRouter initialEntries={[entry]}><InvoicesPage /><LocationProbe /></MemoryRouter>
  </QueryClientProvider>,
);

const requested = (fragment: string) =>
  get.mock.calls.some(([url]) => String(url).includes(fragment));

describe('InvoicesPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    get.mockImplementation((url: string) => (url.includes('invoices')
      ? Promise.resolve({ data: {
        items: [ROW], total: 1, page: 1, page_size: 50,
        totals: { amount_kzt: '1000.00', paid_bank_amount: '0.00' },
      } })
      : Promise.resolve({ data: [] })));
  });

  it('вкладка «На решение ФД» — «Не оплачивать отмеченные» с причиной', { timeout: 20000 }, async () => {
    post.mockResolvedValue({ data: { ok: [], failed: [{ id: 'inv1', reason: 'Решение ждёт не вас.' }] } });
    render(
      <QueryClientProvider client={createTestQueryClient()}>
        <MemoryRouter><InvoicesPage /></MemoryRouter>
      </QueryClientProvider>,
    );

    await userEvent.click(await screen.findByRole('tab', { name: 'На решение ФД' }));
    await waitFor(() => expect(get.mock.calls.some(([url]) => String(url).includes('?tab=fd'))).toBe(true));

    await userEvent.click(await screen.findByRole('checkbox', { name: 'Отметить СЧ-2026-000001' }));
    await userEvent.click(screen.getByRole('button', { name: 'Не оплачивать отмеченные' }));
    const dialog = await screen.findByRole('dialog');
    const submit = within(dialog).getByRole('button', { name: 'Не оплачивать' });
    expect(submit).toBeDisabled();
    await userEvent.type(within(dialog).getByLabelText('Комментарий'), 'Нет бюджета на квартал');
    await userEvent.click(submit);

    await waitFor(() => expect(post).toHaveBeenCalled());
    const [url, body] = post.mock.calls[0];
    expect(url).toContain('invoices/batch-decision');
    expect(body).toEqual({
      invoice_ids: ['inv1'], decision: 'not_payable', comment: 'Нет бюджета на квартал',
    });
    expect(await screen.findByText('Решение ждёт не вас.', { exact: false })).toBeInTheDocument();
  });

  it('открывает вкладку из адреса — ссылка сводки «Ждут закрывающих»', async () => {
    renderAt('/bpp/invoices?tab=awaiting_docs');

    expect(await screen.findByRole('tab', { name: 'Ждут закрывающих' }))
      .toHaveAttribute('aria-selected', 'true');
    await waitFor(() => expect(requested('?tab=awaiting_docs')).toBe(true));
    expect(requested('?tab=all')).toBe(false);
  });

  it('смена вкладки пишет её в адрес и начинает с первой страницы, поиск остаётся', async () => {
    // 500 строк — третья страница существует, реестр её не прижимает.
    get.mockImplementation((url: string) => Promise.resolve({ data: url.includes('invoices') ? {
      items: [ROW], total: 500, page: 3, page_size: 50,
      totals: { amount_kzt: '1000.00', paid_bank_amount: '0.00' },
    } : [] }));
    renderAt('/bpp/invoices?page=3&q=145');

    await userEvent.click(await screen.findByRole('tab', { name: 'К оплате' }));
    await waitFor(() => expect(screen.getByTestId('search').textContent).toContain('tab=to_pay'));
    const search = new URLSearchParams(screen.getByTestId('search').textContent ?? '');
    expect(search.get('page')).toBeNull();
    expect(search.get('q')).toBe('145');
    await waitFor(() => expect(requested('?tab=to_pay')).toBe(true));

    await userEvent.click(screen.getByRole('tab', { name: 'Все' }));
    await waitFor(() => expect(screen.getByTestId('search').textContent).not.toContain('tab='));
  });

  it('неизвестная вкладка в адресе — «Все», параметр убран', async () => {
    renderAt('/bpp/invoices?tab=bogus');

    expect(await screen.findByRole('tab', { name: 'Все' })).toHaveAttribute('aria-selected', 'true');
    await waitFor(() => expect(screen.getByTestId('search').textContent).toBe(''));
    expect(requested('?tab=bogus')).toBe(false);
  });
});
