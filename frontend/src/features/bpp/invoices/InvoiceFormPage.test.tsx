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
vi.mock('@/hooks/useActiveProfile', () => ({
  useActiveProfile: () => ({ activeProfile: { id: '1' } }),
}));
vi.mock('../core/HistoryTab', () => ({ HistoryTab: () => <div>История</div> }));
vi.mock('../core/ApprovalTab', () => ({ ApprovalTab: () => <div>Согласование</div> }));
vi.mock('@/components/files/FilesPanel', () => ({ FilesPanel: () => <div>Файлы</div> }));

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


const COMPARISON = {
  source: {
    kind: 'source', source_type: 'SRC', id: ID, number: 'ДОК-1', status: 'x', status_label: 'x',
    url: '/x', counterparty: null, currency_code: 'KZT', amount: '1.00', amount_kzt: '1.00',
    with_vat: false, vat_rate: null, vat_amount: null, delivery_date: null, payment_terms: null,
    author: { id: 1, name: 'А' },
  },
  offers: [], positions: [], limit: 3, submitted_count: 0, window_open: true,
  can_propose: true, propose_blocked_reason: null, my_offer_id: null,
};

/** Сравнение альтернатив отвечает поверх того, что уже отдаёт `serve`. */
function withComparison(type: 'invoice' | 'agreement') {
  const base = get.getMockImplementation()!;
  get.mockImplementation((url: string) => (url.includes('/comparison')
    ? Promise.resolve({ data: { ...COMPARISON, source: { ...COMPARISON.source, source_type: type } } })
    : base(url)));
}
const comparisonAsked = () => get.mock.calls.some(([url]) => String(url).includes('/comparison'));

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

  it('смена основания снимает договор со счёта', { timeout: 15000 }, async () => {
    serve(card({
      basis: 'contract', amount: '1000.00', amount_kzt: '1000.00', over_threshold: false,
      threshold: null,
      agreement: {
        id: 'agr1', number: 'ДГ-2026-000001', ext_number: '145', ext_date: '2026-09-20',
        is_open: false, status: 'active', effective_amount: '5000.00', remaining: '4000.00',
      },
      lines: [{
        id: 'l1', request_item_id: 'r1', sys_number: 'ЗЗ-2026-000001-01', name: 'Швеллер',
        request_id: 'q1', request_number: 'ЗЗ-2026-000001', qty: '10.000', amount: '1000.00',
        plan_amount: '1000.00', qty_available: '10.000', amount_available: '1000.00',
      }],
    }));
    patch.mockResolvedValue({ data: card({ basis: 'no_contract', agreement: null, amount: '1000.00' }) });
    renderForm();

    await userEvent.click(await screen.findByRole('button', { name: 'Сделать «Без договора»' }, { timeout: 4000 }));
    const dialog = await screen.findByRole('dialog');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Без договора' }));

    await waitFor(() => expect(patch).toHaveBeenCalled());
    const [url, body] = patch.mock.calls[0];
    expect(url).toContain(`invoices/${ID}`);
    expect(body).toMatchObject({ basis: 'no_contract', version: 3 });
    expect(body).not.toHaveProperty('counterparty_id');
  });

  it('отметка оплаты больше неоплаченного остатка — кнопка закрыта', { timeout: 15000 }, async () => {
    serve(card({
      status: 'partially_paid', amount: '1000.00', amount_kzt: '1000.00', over_threshold: false,
      paid_amount: '400.00', unpaid_amount: '600.00', allowed_actions: ['mark_paid'],
    }));
    renderForm();

    await userEvent.click(await screen.findByRole('button', { name: 'Оплачено' }, { timeout: 4000 }));
    const dialog = await screen.findByRole('dialog');
    const amount = within(dialog).getByLabelText('Сумма, KZT');
    await userEvent.clear(amount);
    await userEvent.type(amount, '600,01');

    expect(within(dialog).getByRole('alert')).toHaveTextContent('Сумма больше неоплаченного остатка');
    expect(within(dialog).getByRole('button', { name: 'Оплачено' })).toBeDisabled();
    expect(post).not.toHaveBeenCalled();
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

  it('счёт без договора — под позициями блок «Альтернативы»; по договору — блока нет', { timeout: 15000 }, async () => {
    serve(card());
    withComparison('invoice');
    renderForm();
    expect(await screen.findByRole('button', { name: 'Предложить альтернативу' }, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.getByTestId('alternatives-block')).toBeInTheDocument();
  });

  it('ФД выбирает альтернативу — комментарий, SelectAlternativeOffer, переход к новому документу', { timeout: 20000 }, async () => {
    serve(card({
      status: 'under_review', allowed_actions: ['pay', 'not_payable', 'return', 'select_alternative'],
    }));
    const offer = {
      ...COMPARISON.source, kind: 'offer', id: 'of1', number: 'АП-2026-000007', status: 'submitted',
      status_label: 'Подано', version: 1, source_amount_kzt: '5000000.00',
      saving: { amount: '500000.00', pct: '10.00', more_expensive: false },
      payment_terms: 'postpay', payment_terms_note: '', justification: '', files: [],
      author: { id: 906, name: 'Петров И.', role: 'sn' }, own_document: false,
      submitted_at: '2026-09-29T05:00:00Z',
    };
    const base = get.getMockImplementation()!;
    get.mockImplementation((url: string) => (url.includes('/comparison')
      ? Promise.resolve({ data: {
        ...COMPARISON, source: { ...COMPARISON.source, source_type: 'invoice' },
        offers: [offer], submitted_count: 1,
      } })
      : base(url)));
    post.mockResolvedValue({ data: {
      invoice: card({ status: 'replaced', allowed_actions: [] }),
      result: { type: 'agreement', id: 'ag-new', number: 'ДГ-2026-000009' },
      remainder: null, kpi_id: 'k1',
    } });
    renderForm();

    await userEvent.click(await screen.findByRole('button', { name: 'Выбрать' }, { timeout: 4000 }));
    const dialog = await screen.findByRole('dialog');
    await userEvent.type(within(dialog).getByRole('textbox'), 'Дешевле при тех же сроках');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Выбрать' }));

    expect(await screen.findByText('Экран договора', {}, { timeout: 4000 })).toBeInTheDocument();
    expect(post).toHaveBeenCalledWith(
      expect.stringContaining(`invoices/${ID}/select-alternative`),
      { offer_id: 'of1', comment: 'Дешевле при тех же сроках', version: 3 },
      expect.objectContaining({ headers: expect.objectContaining({ 'Idempotency-Key': expect.any(String) }) }),
    );
  });

  it('без права выбора кнопки «Выбрать» в блоке нет', { timeout: 15000 }, async () => {
    serve(card({ status: 'under_review', allowed_actions: ['pay', 'not_payable', 'return'] }));
    withComparison('invoice');
    renderForm();
    await screen.findByTestId('alternatives-block', {}, { timeout: 4000 });
    expect(screen.queryByRole('button', { name: 'Выбрать' })).toBeNull();
  });

  it('счёт по договору — сравнение альтернатив не запрашивается', { timeout: 15000 }, async () => {
    serve(card({
      basis: 'contract',
      agreement: {
        id: 'ag', number: 'ДГ-1', ext_number: '1', ext_date: null, is_open: false,
        status: 'active', effective_amount: '1.00', remaining: '1.00',
      },
    }));
    withComparison('invoice');
    renderForm();
    await screen.findByText('СЧ-2026-000001', {}, { timeout: 4000 });
    expect(comparisonAsked()).toBe(false);
    expect(screen.queryByTestId('alternatives-block')).toBeNull();
  });
});
