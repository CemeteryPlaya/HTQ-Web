/**
 * Подотчёт (B4.1):
 * - черновик — сумма и цель правятся, «Отправить на согласование» шлёт версию;
 * - бухгалтер отмечает выдачу;
 * - авансовый отчёт уходит multipart с файлом; файл не того формата не
 *   принимается до запроса; отчёт в строке отправляется своей кнопкой.
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { createTestQueryClient } from '@/test/renderWithProviders';

import type { AccountableCard } from './api';
import { AccountableFormPage } from './AccountableFormPage';

const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
const patch = vi.hoisted(() => vi.fn());
const toastError = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get, post, patch, delete: vi.fn() } }));
vi.mock('sonner', () => ({ toast: { error: toastError, success: vi.fn(), info: vi.fn() } }));
vi.mock('../core/HistoryTab', () => ({ HistoryTab: () => <div>История</div> }));
vi.mock('../core/ApprovalTab', () => ({ ApprovalTab: () => <div>Согласование</div> }));

const ID = '3fa85f64-5717-4562-b3fc-2c963f66afa6';

const card = (over: Partial<AccountableCard> = {}): AccountableCard => ({
  id: ID, number: 'ПО-2026-000001', status: 'draft', version: 2,
  project: { id: 'p1', code: 'П-015', name: 'Объект' }, project_id: 'p1', article_id: 'art',
  article_name: 'Металлопрокат', amount: '1000.00', currency: 'KZT', goal: 'Командировка',
  accountable_user_id: 904, accountable_user_name: 'Иванов А.', paid_at: null, paid_by_name: null,
  reported_amount: '0.00', remaining_amount: '1000.00', reports: [], current_holders: null,
  allowed_actions: ['save', 'submit', 'delete'], created_at: '2026-09-28T05:00:00Z',
  ...over,
});

function serve(value: AccountableCard) {
  get.mockImplementation(() => Promise.resolve({ data: value }));
}

function renderForm() {
  return render(
    <QueryClientProvider client={createTestQueryClient()}>
      <MemoryRouter initialEntries={[`/bpp/accountable/${ID}`]}>
        <Routes>
          <Route path="/bpp/accountable/:id" element={<AccountableFormPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('AccountableFormPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('черновик: правка суммы уходит перед отправкой', { timeout: 15000 }, async () => {
    serve(card());
    patch.mockResolvedValue({ data: card({ version: 3, amount: '1200.00' }) });
    post.mockResolvedValue({ data: card({ version: 4, status: 'on_review', allowed_actions: [] }) });
    renderForm();

    const amount = await screen.findByLabelText('Сумма', {}, { timeout: 4000 });
    await userEvent.clear(amount);
    await userEvent.type(amount, '1 200,00');
    await userEvent.click(screen.getByRole('button', { name: 'Отправить на согласование' }));

    await waitFor(() => expect(post).toHaveBeenCalled());
    expect(patch.mock.calls[0][1]).toEqual({ amount: '1200.00', goal: 'Командировка', version: 2 });
    const [url, body] = post.mock.calls[0];
    expect(url).toContain(`accountable/${ID}/submit`);
    expect(body).toEqual({ version: 3 });
  });

  it('бухгалтер отмечает выдачу', { timeout: 15000 }, async () => {
    serve(card({ status: 'awaiting_accounting', allowed_actions: ['mark_paid'] }));
    post.mockResolvedValue({ data: card({ status: 'awaiting_report', allowed_actions: [] }) });
    renderForm();

    await userEvent.click(await screen.findByRole('button', { name: 'Отметить выдачу' }, { timeout: 4000 }));
    const dialog = await screen.findByRole('dialog');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Отметить выдачу' }));

    await waitFor(() => expect(post).toHaveBeenCalled());
    expect(post.mock.calls[0][0]).toContain(`accountable/${ID}/mark-paid`);
    expect(post.mock.calls[0][1]).toEqual({ version: 2 });
  });

  it('авансовый отчёт — multipart с файлом; чужой формат отвергается до запроса', { timeout: 20000 }, async () => {
    serve(card({ status: 'awaiting_report', allowed_actions: ['add_report'] }));
    post.mockResolvedValue({ data: { id: 'r1', expense_name: 'Бензин', amount: '400.00',
      approval_state: 'draft', created_at: '2026-09-28T06:00:00Z', files: [], can_submit: true } });
    renderForm();

    await userEvent.click(await screen.findByRole('button', { name: 'Добавить отчёт' }, { timeout: 4000 }));
    const dialog = await screen.findByRole('dialog');
    await userEvent.type(within(dialog).getByLabelText('Наименование затрат'), 'Бензин');
    await userEvent.type(within(dialog).getByLabelText('Сумма, KZT'), '400');
    const input = within(dialog).getByLabelText(/Подтверждающий документ/) as HTMLInputElement;

    await userEvent.upload(input, new File(['x'], 'check.docx', { type: 'application/msword' }),
      { applyAccept: false });
    expect(toastError).toHaveBeenCalled();
    const submit = within(dialog).getByRole('button', { name: 'Добавить отчёт' });
    expect(submit).toBeDisabled();

    await userEvent.upload(input, new File(['%PDF'], 'check.pdf', { type: 'application/pdf' }));
    await userEvent.click(submit);

    await waitFor(() => expect(post).toHaveBeenCalled());
    const [url, body] = post.mock.calls[0];
    expect(url).toContain(`accountable/${ID}/reports`);
    expect(body).toBeInstanceOf(FormData);
    expect((body as FormData).get('expense_name')).toBe('Бензин');
    expect((body as FormData).get('amount')).toBe('400.00');
    expect(((body as FormData).get('file') as File).name).toBe('check.pdf');
  });

  it('отчёт в строке отправляется своей кнопкой', { timeout: 15000 }, async () => {
    serve(card({
      status: 'awaiting_report', allowed_actions: ['add_report'],
      reports: [{ id: 'r1', expense_name: 'Бензин', amount: '400.00', approval_state: 'draft',
        created_at: '2026-09-28T06:00:00Z', files: [{ id: '5', filename: 'check.pdf' }], can_submit: true }],
    }));
    post.mockResolvedValue({ data: {} });
    renderForm();

    const row = await screen.findByTestId('advance-report', {}, { timeout: 4000 });
    expect(within(row).getByText('Черновик')).toBeInTheDocument();
    await userEvent.click(within(row).getByRole('button', { name: 'Отправить на согласование' }));
    const dialog = await screen.findByRole('dialog');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Отправить на согласование' }));

    await waitFor(() => expect(post).toHaveBeenCalled());
    expect(post.mock.calls[0][0]).toContain('accountable/reports/r1/submit');
  });
});
