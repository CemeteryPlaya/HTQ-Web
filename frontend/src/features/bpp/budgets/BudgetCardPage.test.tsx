/**
 * Форма F-01 (ТЗ §06):
 * - утверждённый бюджет без права правки — только чтение, «Задействовано» и
 *   «Доступно» видны, кнопок правки нет;
 * - «Оплачено факт» (CALC-007) — столбец, итог и сводка группы; без данных
 *   выписки (подмодуль выключен) столбца нет;
 * - в корректировке лимит ниже задействованного подсвечен текстом ТЗ §6.5
 *   п.3, а «Утвердить корректировку» не показывается;
 * - «Утвердить» уходит с `version` карточки и `Idempotency-Key`.
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { createTestQueryClient } from '@/test/renderWithProviders';

import type { BudgetCard, BudgetLine } from './api';
import { BudgetCardPage } from './BudgetCardPage';

const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
const patch = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get, post, patch, delete: vi.fn() } }));
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() } }));
vi.mock('../core/HistoryTab', () => ({ HistoryTab: () => <div>История</div> }));

const ID = '3fa85f64-5717-4562-b3fc-2c963f66afa6';

const line = (over: Partial<BudgetLine> = {}): BudgetLine => ({
  id: 'l1', article_id: 'art-1', article_code: 'T-METAL', article_name: 'Металлопрокат',
  article_archived: false, group_code: 'supply', group_name: 'Снабжение',
  limit_amount: '5000000.00', comment: '', committed: '3400000.00', paid_fact: '1200000.00',
  available: '1600000.00',
  ...over,
});

const totals = {
  limit_amount: '5000000.00', committed: '3400000.00', paid_fact: '1200000.00',
  available: '1600000.00', by_group: [],
};

const card = (over: Partial<BudgetCard> = {}): BudgetCard => ({
  id: ID, number: 'БДЖ-П-015', status: 'approved', version: 7, currency_code: 'KZT',
  project: { id: 'p1', code: 'П-015', name: 'Объект', customer_name: 'ТОО «Заказчик»' },
  date_from: null, date_to: null, status_comment: '',
  active_version: {
    id: 'v1', version_no: 1, state: 'active', comment: '', approved_at: '2026-09-20T05:00:00Z',
    approved_by: 1, approved_by_name: 'ФД',
  },
  correction: null, lines: [line()], totals,
  created_at: '2026-09-20T05:00:00Z', created_by: 1, created_by_name: 'ФД',
  allowed_actions: ['export'],
  ...over,
});

function renderCard() {
  return render(
    <QueryClientProvider client={createTestQueryClient()}>
      <MemoryRouter initialEntries={[`/bpp/budgets/${ID}`]}>
        <Routes>
          <Route path="/bpp/budgets/:id" element={<BudgetCardPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function serve(budget: BudgetCard) {
  get.mockImplementation((url: string) => {
    if (url.endsWith(`budgets/${ID}`)) return Promise.resolve({ data: budget });
    return Promise.resolve({ data: [] });
  });
}

describe('BudgetCardPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('утверждённый бюджет без права правки — только чтение с остатками', async () => {
    serve(card());
    renderCard();

    expect(await screen.findByText('БДЖ-П-015')).toBeInTheDocument();
    expect(screen.getByText('Только просмотр')).toBeInTheDocument();
    const row = screen.getByTestId('budget-line');
    expect(within(row).getByText('3 400 000,00 KZT')).toBeInTheDocument();
    expect(within(row).getByText('1 600 000,00 KZT')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Сохранить/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('textbox', { name: 'Лимит' })).not.toBeInTheDocument();
  });

  it('«Оплачено факт» — столбец, итог и группы; выписка выключена — столбца нет', async () => {
    const group = {
      group_code: 'supply', group_name: 'Снабжение', limit_amount: '5000000.00',
      committed: '3400000.00', paid_fact: '1200000.00', available: '1600000.00',
    };
    serve(card({ totals: { ...totals, by_group: [group] } }));
    const { unmount } = renderCard();

    expect(await screen.findByRole('columnheader', { name: 'Оплачено факт' })).toBeInTheDocument();
    expect(within(screen.getByTestId('budget-line')).getByText('1 200 000,00 KZT')).toBeInTheDocument();
    // Итог таблицы и сводка группы.
    expect(screen.getAllByText('1 200 000,00 KZT')).toHaveLength(2);
    expect(screen.getByText('Оплачено факт: 1 200 000,00 KZT')).toBeInTheDocument();
    unmount();

    serve(card({
      lines: [line({ paid_fact: null })],
      totals: { ...totals, paid_fact: null, by_group: [{ ...group, paid_fact: null }] },
    }));
    renderCard();
    expect(await screen.findByText('БДЖ-П-015')).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Задействовано' })).toBeInTheDocument();
    expect(screen.queryByRole('columnheader', { name: 'Оплачено факт' })).not.toBeInTheDocument();
    expect(screen.queryByText(/Оплачено факт:/)).not.toBeInTheDocument();
  });

  it('корректировка: лимит ниже задействованного подсвечен, утвердить нельзя', async () => {
    serve(card({
      allowed_actions: ['save_correction', 'approve_correction', 'cancel_correction', 'export'],
      correction: {
        version_no: 2, comment: 'Рост цен на металл', totals,
        lines: [line({ limit_amount: '3000000.00' })],
      },
    }));
    renderCard();

    expect(
      await screen.findByText('Лимит не может быть меньше задействованной суммы 3 400 000,00'),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Отменить корректировку' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Утвердить корректировку' })).not.toBeInTheDocument();

    const limit = screen.getByRole('textbox', { name: 'Лимит' });
    await userEvent.clear(limit);
    await userEvent.type(limit, '3 500 000,00');
    expect(await screen.findByRole('button', { name: 'Утвердить корректировку' })).toBeInTheDocument();
  });

  it('«Утвердить» черновик уходит с version и Idempotency-Key', async () => {
    serve(card({
      status: 'draft', active_version: null, allowed_actions: ['save', 'approve', 'delete'],
      lines: [line({ committed: null, paid_fact: null, available: null })],
    }));
    post.mockResolvedValue({ data: card() });
    renderCard();

    await userEvent.click(await screen.findByRole('button', { name: 'Утвердить' }));
    const dialog = await screen.findByRole('dialog');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Утвердить' }));

    await waitFor(() => expect(post).toHaveBeenCalled());
    const [url, body, config] = post.mock.calls[0];
    expect(url).toContain(`budgets/${ID}/approve`);
    expect(body).toEqual({ version: 7 });
    expect(config.headers['Idempotency-Key']).toBeTruthy();
  });
});
