/**
 * Форма F-05 (ТЗ §10):
 * - счёт без договора выше 1000 МРП — нет «Отправить ФД», «Оформить договор
 *   по этим позициям» удаляет черновик и создаёт договор из его позиций
 *   (BR-040);
 * - «Оплатить» ФД спрашивает плановую дату (по умолчанию — срок оплаты);
 * - «Оплачено» БУХ — дата, сумма (по умолчанию — неоплаченный остаток) и
 *   номер п/п.
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { createTestQueryClient } from '@/test/renderWithProviders';

import type { InvoiceCard } from './api';
import { localToday } from './invoiceForm';
import { InvoiceFormPage } from './InvoiceFormPage';

const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
const patch = vi.hoisted(() => vi.fn());
const del = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get, post, patch, delete: del } }));
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() } }));
vi.mock('@/hooks/usePermissions', () => ({
  usePermissions: () => ({ can: () => true, atLeast: () => true }),
}));
vi.mock('../core/HistoryTab', () => ({ HistoryTab: () => <div>История</div> }));
vi.mock('../core/ApprovalTab', () => ({ ApprovalTab: () => <div>Согласование</div> }));

const ID = '3fa85f64-5717-4562-b3fc-2c963f66afa6';

const card = (over: Partial<InvoiceCard> = {}): InvoiceCard => ({
  id: ID, number: 'СЧ-2026-000001', status: 'draft', version: 3, author_id: 904,
  author_name: 'Иванов А.', created_at: '2026-09-28T05:00:00Z', basis: 'no_contract',
  initiator_role: 'sn', agreement: null,
  project: { id: 'p1', code: 'П-015', name: 'Объект' },
  article: { id: 'art', code: 'T-METAL', name: 'Металлопрокат' },
  counterparty: {
    id: 'c1', name: 'ТОО «Альфа»', short_name: '', reg_number: '100000000001',
    country_code: 'KZ', is_vat_payer: true, status: 'active', is_verified: true,
  },
  counterparty_confirmed: false, ext_number: '77', ext_date: '2026-09-27',
  amount: '5000000.00', currency_code: 'KZT', rate: null, rate_source: 'kzt',
  amount_kzt: '5000000.00', threshold: '3932000.00', over_threshold: true, with_vat: true,
  vat_rate: '16.00', vat_source: 'refdata', vat_amount: '689655.17', vat_warning: null,
  purchase_type: 'goods', is_advance: false, due_date: '2099-01-15', planned_pay_date: null,
  fd_decided_at: null, status_comment: '', rework_comment: '', author_comment: '',
  docs_required: {}, docs_requested_at: null, docs_comment: '', days_waiting_docs: null,
  recon_status: 'no_data', paid_bank_amount: '0.00', paid_amount: '0.00',
  unpaid_amount: '5000000.00', payments: [], possible_split: false,
  lines: [{
    id: 'l1', request_item_id: 'r1', sys_number: 'ЗЗ-2026-000001-01', name: 'Швеллер',
    request_id: 'q1', request_number: 'ЗЗ-2026-000001', qty: '10.000', amount: '5000000.00',
    plan_amount: '5000000.00', qty_available: '10.000', amount_available: '5000000.00',
  }],
  current_holders: null, allowed_actions: ['save', 'submit', 'delete', 'cancel'],
  ...over,
});

function serve(invoice: InvoiceCard) {
  get.mockImplementation((url: string) => {
    if (url.endsWith(`invoices/${ID}`)) return Promise.resolve({ data: invoice });
    if (url.includes('invoices/threshold')) {
      return Promise.resolve({ data: { date: '2026-09-27', threshold: '3932000.00' } });
    }
    return Promise.resolve({ data: [] });
  });
}

function renderForm() {
  return render(
    <QueryClientProvider client={createTestQueryClient()}>
      <MemoryRouter initialEntries={[`/bpp/invoices/${ID}`]}>
        <Routes>
          <Route path="/bpp/invoices/:id" element={<InvoiceFormPage />} />
          <Route path="/bpp/agreements/:id" element={<div>Экран договора</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('InvoiceFormPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('выше 1000 МРП без договора — нет «Отправить ФД», есть «Оформить договор»', { timeout: 15000 }, async () => {
    serve(card());
    del.mockResolvedValue({ data: null });
    post.mockResolvedValue({ data: { id: 'agr-new' } });
    renderForm();

    const alert = await screen.findByRole('alert', {}, { timeout: 4000 });
    expect(alert).toHaveTextContent('выше 1000 МРП (3 932 000,00 KZT на дату счёта)');
    expect(screen.queryByRole('button', { name: 'Отправить ФД' })).not.toBeInTheDocument();

    await userEvent.click(within(alert).getByRole('button', { name: 'Оформить договор по этим позициям' }));
    const dialog = await screen.findByRole('dialog');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Оформить договор' }));

    expect(await screen.findByText('Экран договора')).toBeInTheDocument();
    expect(del.mock.calls[0][0]).toContain(`invoices/${ID}`);
    const [url, body] = post.mock.calls[0];
    expect(url).toContain('agreements');
    expect(body).toEqual({ item_ids: ['r1'], role: 'sn' });
  });

  it('«Оплатить» ФД — плановая дата по умолчанию из срока оплаты', { timeout: 15000 }, async () => {
    serve(card({
      status: 'under_review', amount: '1000.00', amount_kzt: '1000.00', over_threshold: false,
      allowed_actions: ['cancel', 'pay', 'not_payable', 'return'],
    }));
    post.mockResolvedValue({ data: card({ status: 'to_pay', allowed_actions: [] }) });
    renderForm();

    await userEvent.click(await screen.findByRole('button', { name: 'Оплатить' }, { timeout: 4000 }));
    const dialog = await screen.findByRole('dialog');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Оплатить' }));

    await waitFor(() => expect(post).toHaveBeenCalled());
    const [url, body] = post.mock.calls[0];
    expect(url).toContain(`invoices/${ID}/decision`);
    expect(body).toEqual({ decision: 'pay', comment: '', planned_pay_date: '2099-01-15' });
  });

  it('«Оплачено» БУХ — неоплаченный остаток и номер п/п', { timeout: 15000 }, async () => {
    serve(card({
      status: 'partially_paid', amount: '1000.00', amount_kzt: '1000.00', over_threshold: false,
      paid_amount: '400.00', unpaid_amount: '600.00', allowed_actions: ['mark_paid'],
    }));
    post.mockResolvedValue({ data: card({ status: 'paid', allowed_actions: [] }) });
    renderForm();

    await userEvent.click(await screen.findByRole('button', { name: 'Оплачено' }, { timeout: 4000 }));
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByLabelText('Сумма, KZT')).toHaveValue('600,00');
    await userEvent.type(within(dialog).getByLabelText('№ п/п'), '77');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Оплачено' }));

    await waitFor(() => expect(post).toHaveBeenCalled());
    const [url, body] = post.mock.calls[0];
    expect(url).toContain(`invoices/${ID}/payments`);
    expect(body).toEqual({ pay_date: localToday(), amount: '600.00', pp_number: '77', rate: null });
  });
});
