/**
 * Форма F-04 (ТЗ §09):
 * - превышение над планом больше остатка статьи — предупреждение и нет
 *   «Отправить» (§9.3 п.5, BR-034);
 * - непроверенный контрагент — окно подтверждения, отправка уходит с
 *   `counterparty_confirmed` (D-20);
 * - действующий договор у ФД — только чтение, «Расторгнуть» и «Исполнен».
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { createTestQueryClient } from '@/test/renderWithProviders';

import type { AgreementCard } from './api';
import { AgreementFormPage } from './AgreementFormPage';

const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
const patch = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get, post, patch, delete: vi.fn() } }));
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() } }));
vi.mock('../core/HistoryTab', () => ({ HistoryTab: () => <div>История</div> }));
vi.mock('../core/ApprovalTab', () => ({ ApprovalTab: () => <div>Согласование</div> }));
vi.mock('@/components/files/FilesPanel', () => ({ FilesPanel: () => <div>Файлы</div> }));

const ID = '3fa85f64-5717-4562-b3fc-2c963f66afa6';

const card = (over: Partial<AgreementCard> = {}): AgreementCard => ({
  id: ID, number: 'ДГ-2026-000001', status: 'draft', version: 2, author_id: 904,
  author_name: 'Иванов А.', created_at: '2026-09-28T05:00:00Z',
  project: { id: 'p1', code: 'П-015', name: 'Объект' },
  article: { id: 'art', code: 'T-METAL', name: 'Металлопрокат', archived: false },
  counterparty: {
    id: 'c1', name: 'ТОО «Альфа»', short_name: '', reg_number: '100000000001',
    country_code: 'KZ', is_vat_payer: true, status: 'active', is_verified: true,
  },
  counterparty_confirmed: false, name: 'Договор на ТМЦ по проекту П-015', ext_number: '145',
  ext_date: '2026-09-28', agreement_type: 'goods', is_open: false, amount: '1000.00',
  currency_code: 'KZT', with_vat: true, vat_rate: '16.00', vat_source: 'refdata',
  vat_amount: '137.93', amount_without_vat: '862.07', vat_warning: null, valid_to: null,
  status_comment: '', rework_comment: '', parent: null, supplements: [],
  effective_amount: '1000.00', remaining: null,
  budget: { available: '200.00', over_plan: '0.00', plan_total: '1000.00' },
  items: [{
    id: 'i1', request_item_id: 'r1', sys_number: 'ЗЗ-2026-000001-01', name: 'Швеллер',
    request_id: 'q1', request_number: 'ЗЗ-2026-000001', uom: 'т', plan_qty: '10.000',
    plan_amount: '1000.00', qty: '10.000', amount: '1000.00', qty_available: '10.000',
  }],
  current_holders: null, allowed_actions: ['save', 'submit', 'delete', 'print'],
  ...over,
});

function serve(agreement: AgreementCard) {
  get.mockImplementation((url: string) => (url.endsWith(`agreements/${ID}`)
    ? Promise.resolve({ data: agreement })
    : Promise.resolve({ data: { invoices: [], effective_amount: null, remaining: null } })));
}

function renderForm() {
  return render(
    <QueryClientProvider client={createTestQueryClient()}>
      <MemoryRouter initialEntries={[`/bpp/agreements/${ID}`]}>
        <Routes>
          <Route path="/bpp/agreements/:id" element={<AgreementFormPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('AgreementFormPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('превышение над планом больше остатка статьи — нет «Отправить»', { timeout: 15000 }, async () => {
    serve(card());
    renderForm();

    const amount = await screen.findByLabelText('Сумма договора', {}, { timeout: 4000 });
    await userEvent.clear(amount);
    await userEvent.type(amount, '1 300,00');

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Сумма договора превышает план позиций на 300,00 KZT; доступный остаток статьи — 200,00 KZT.',
    );
    expect(screen.queryByRole('button', { name: 'Отправить на согласование' })).not.toBeInTheDocument();
  });

  it('непроверенный контрагент — подтверждение, отправка с counterparty_confirmed', { timeout: 15000 }, async () => {
    serve(card({
      counterparty: {
        id: 'c1', name: 'ТОО «Альфа»', short_name: '', reg_number: '100000000001',
        country_code: 'KZ', is_vat_payer: true, status: 'active', is_verified: false,
      },
    }));
    post.mockResolvedValue({ data: card({ status: 'on_review', allowed_actions: ['print'] }) });
    renderForm();

    await userEvent.click(await screen.findByRole(
      'button', { name: 'Отправить на согласование' }, { timeout: 4000 },
    ));
    const dialog = await screen.findByRole('alertdialog');
    await userEvent.click(within(dialog).getByRole('checkbox'));
    await userEvent.click(within(dialog).getByRole('button', { name: 'Подтвердить и продолжить' }));

    await waitFor(() => expect(post).toHaveBeenCalled());
    const [url, body] = post.mock.calls[0];
    expect(url).toContain(`agreements/${ID}/submit`);
    expect(body).toEqual({ version: 2, counterparty_confirmed: true });
  });

  it('«Открытый договор» скрывает сумму договора и суммы позиций', { timeout: 15000 }, async () => {
    serve(card());
    renderForm();

    expect(await screen.findByLabelText('Сумма договора', {}, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.getByLabelText('Сумма по договору ЗЗ-2026-000001-01')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('checkbox', { name: 'Открытый договор' }));

    expect(screen.queryByLabelText('Сумма договора')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Сумма по договору ЗЗ-2026-000001-01')).not.toBeInTheDocument();
  });

  it('действующий договор у ФД — только чтение и действия ФД', { timeout: 15000 }, async () => {
    serve(card({ status: 'active', allowed_actions: ['fulfil', 'terminate', 'print'] }));
    renderForm();

    expect(await screen.findByText('Только просмотр', {}, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Расторгнуть' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Отметить «Исполнен»' })).toBeInTheDocument();
    expect(screen.queryByLabelText('Сумма договора')).not.toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Исполнение' })).toBeInTheDocument();
  });
});
