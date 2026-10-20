/**
 * Реестр тендеров (T2.3; план §4.3): номер ссылкой на карточку, заявка
 * ссылкой на свою карточку, статус, срок приёма, счётчики; поиск — `q`.
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { createTestQueryClient } from '@/test/renderWithProviders';

import { TendersPage } from './TendersPage';
import { REQUEST_ID, TENDER_ID } from './testData';

const get = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get, post: vi.fn(), patch: vi.fn(), delete: vi.fn() } }));

const ROWS = [{
  id: TENDER_ID, number: 'ТН-2026-000003', status: 'intake', status_display: 'Приём предложений',
  request_id: REQUEST_ID, request_number: 'ЗТ-2026-000007', deadline_at: '2099-11-20T13:00:00+00:00',
  author_id: 904, created_at: '2026-10-07T09:00:00+00:00',
  counters: { sent: 4, opened: 2, submitted: 1 },
}];

function serve(rows: unknown = ROWS) {
  get.mockImplementation(() => Promise.resolve({
    data: Array.isArray(rows) ? { results: rows, total: rows.length, page: 1, page_size: 50 } : rows,
  }));
}

function renderPage() {
  return render(
    <QueryClientProvider client={createTestQueryClient()}>
      <MemoryRouter initialEntries={['/tender/tenders']}>
        <TendersPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('TendersPage', () => {
  beforeEach(() => vi.clearAllMocks());

  it('строка: номер, заявка, статус, срок, счётчики', async () => {
    serve();
    renderPage();

    const link = await screen.findByRole('link', { name: 'ТН-2026-000003' });
    expect(link).toHaveAttribute('href', `/tender/tenders/${TENDER_ID}`);
    const row = link.closest('tr') as HTMLElement;
    expect(within(row).getByRole('link', { name: 'ЗТ-2026-000007' }))
      .toHaveAttribute('href', `/tender/requests/${REQUEST_ID}`);
    expect(within(row).getByText('Приём предложений')).toBeInTheDocument();
    expect(within(row).getByText('4 / 2 / 1')).toBeInTheDocument();
    expect(within(row).getByText(/20\.11\.2099/)).toBeInTheDocument();
  });

  it('страница {results} и поиск q', async () => {
    serve({ results: ROWS, total: 1 });
    renderPage();
    await screen.findByRole('link', { name: 'ТН-2026-000003' });

    await userEvent.type(screen.getByRole('searchbox'), 'ТН-2026');
    await waitFor(() => expect(get).toHaveBeenCalledWith(
      expect.stringContaining('tender/v1/tenders'),
      { params: expect.objectContaining({ q: 'ТН-2026' }) },
    ));
  });

  it('пустой реестр — подсказка, откуда берутся тендеры', async () => {
    serve([]);
    renderPage();
    expect(await screen.findByText(/Тендер объявляется с карточки утверждённой заявки/)).toBeInTheDocument();
  });
});
