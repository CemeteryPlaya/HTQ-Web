/**
 * Форма F-02 (ТЗ §07):
 * - сумма больше доступного остатка — предупреждение текстом ТЗ §7.6 п.4,
 *   «Отправить на согласование» нет, «Сохранить черновик» есть;
 * - «На доработке» — комментарий возврата жёлтой плашкой (§7.6 п.6);
 * - «Отправить» уходит с `version` карточки и `Idempotency-Key`;
 * - заявка на согласовании — только чтение, «Печать» есть.
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { createTestQueryClient } from '@/test/renderWithProviders';

import type { PurchaseRequestCard } from './api';
import { RequestFormPage } from './RequestFormPage';

const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
const patch = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get, post, patch, delete: vi.fn() } }));
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() } }));
vi.mock('../core/HistoryTab', () => ({ HistoryTab: () => <div>История</div> }));
vi.mock('../core/ApprovalTab', () => ({ ApprovalTab: () => <div>Согласование</div> }));
vi.mock('@/components/files/FilesPanel', () => ({ FilesPanel: () => <div>Файлы</div> }));

const ID = '3fa85f64-5717-4562-b3fc-2c963f66afa6';

const card = (over: Partial<PurchaseRequestCard> = {}): PurchaseRequestCard => ({
  id: ID, number: 'ЗЗ-2026-000045', status: 'draft', version: 3, author_id: 904,
  author_name: 'Иванов А.', created_at: '2026-09-27T10:00:00Z', initiator_role: 'sn',
  project: { id: 'p1', code: 'П-015', name: 'Объект 15' },
  article: { id: 'a1', code: 'T-METAL', name: 'Металлопрокат', archived: false },
  purchase_type: 'goods', need_date: '2099-10-15', justification: 'Нужно для монтажа каркаса',
  currency_code: 'KZT', total_amount: '3650000.00', status_comment: '', rework_comment: '',
  budget: null,
  items: [{
    id: 'i1', line_no: 1, sys_number: 'ЗЗ-2026-000045-01', name: 'Швеллер 12П', specs: '',
    uom_id: 'uom-t', uom: 'т', qty: '10.000', price: '365000.00', amount: '3650000.00',
    need_date: '2099-10-15', status: 'open',
  }],
  current_holders: null, files: [],
  allowed_actions: ['save', 'submit', 'cancel', 'delete', 'copy', 'print'],
  ...over,
});

function serve(request: PurchaseRequestCard, available = '2400000.00') {
  get.mockImplementation((url: string) => {
    if (url.endsWith(`requests/${ID}`)) return Promise.resolve({ data: request });
    if (url.endsWith('bpp/v1/me')) {
      return Promise.resolve({ data: { article_groups: ['supply'], initiator_roles: ['sn'] } });
    }
    if (url.endsWith('budgets/lines')) {
      return Promise.resolve({
        data: [{
          article_id: 'a1', article_code: 'T-METAL', article_name: 'Металлопрокат',
          limit: '5000000.00', committed: '2600000.00', available,
        }],
      });
    }
    if (url.includes('projects')) {
      return Promise.resolve({ data: [{ id: 'p1', code: 'П-015', name: 'Объект 15', status: 'active' }] });
    }
    if (url.includes('uoms')) {
      return Promise.resolve({ data: [{ id: 'uom-t', code: 't', short_name: 'т', name: 'Тонна' }] });
    }
    return Promise.resolve({ data: [] });
  });
}

function renderForm() {
  return render(
    <QueryClientProvider client={createTestQueryClient()}>
      <MemoryRouter initialEntries={[`/bpp/requests/${ID}`]}>
        <Routes>
          <Route path="/bpp/requests/:id" element={<RequestFormPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('RequestFormPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('сумма больше остатка: предупреждение, отправки нет, черновик сохранить можно', { timeout: 15000 }, async () => {
    serve(card());
    renderForm();

    // Цепочка загрузок (карточка → «кто я» → строки бюджета) под нагрузкой
    // всего набора тестов дольше секунды ожидания по умолчанию.
    expect(await screen.findByRole('alert', {}, { timeout: 4000 })).toHaveTextContent(
      'Сумма заявки превышает доступный остаток статьи на 1 250 000,00 KZT',
    );
    expect(screen.getByTestId('after-request')).toHaveTextContent('-1 250 000,00 KZT');
    expect(screen.queryByRole('button', { name: 'Отправить на согласование' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Сохранить черновик' })).toBeInTheDocument();
  });

  it('сумма в пределах остатка — «Отправить» уходит с version и ключом', { timeout: 15000 }, async () => {
    serve(card(), '5000000.00');
    post.mockResolvedValue({ data: card({ status: 'in_approval', allowed_actions: ['print'] }) });
    renderForm();

    await userEvent.click(await screen.findByRole(
      'button', { name: 'Отправить на согласование' }, { timeout: 4000 },
    ));

    await waitFor(() => expect(post).toHaveBeenCalled());
    const [url, body, config] = post.mock.calls[0];
    expect(url).toContain(`requests/${ID}/submit`);
    expect(body).toEqual({ version: 3 });
    expect(config.headers['Idempotency-Key']).toBeTruthy();
    expect(patch).not.toHaveBeenCalled();   // без правок — без сохранения
  });

  it('«На доработке» — комментарий возврата жёлтой плашкой', async () => {
    serve(card({ status: 'rework', rework_comment: 'Уточните марку стали и ГОСТ' }), '5000000.00');
    renderForm();

    const banner = await screen.findByText('Заявка возвращена на доработку');
    expect(within(banner.closest('[role="status"]') as HTMLElement)
      .getByText('Уточните марку стали и ГОСТ')).toBeInTheDocument();
  });

  it('на согласовании — только чтение с блоком бюджета сервера и печатью', async () => {
    serve(card({
      status: 'in_approval', allowed_actions: ['copy', 'print'],
      budget: {
        limit: '5000000.00', committed: '6250000.00', available: '-1250000.00',
        after_request: '-1250000.00', reserved: true,
      },
    }));
    renderForm();

    expect(await screen.findByText('Только просмотр')).toBeInTheDocument();
    expect(screen.getByText('Остаток после заявки (уже в резерве)')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Печать (PDF)' })).toBeInTheDocument();
    expect(screen.queryByRole('textbox', { name: 'Наименование' })).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
