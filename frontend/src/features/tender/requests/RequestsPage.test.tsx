/**
 * Реестр заявок на тендер (T1.4, план §3.4): номер ссылкой на карточку,
 * статус, проект из справочника; фильтры `status` и `q` уходят параметрами;
 * «Создать заявку» — по узлу `tender.requests` `create`.
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { createTestQueryClient } from '@/test/renderWithProviders';

import { RequestsPage } from './RequestsPage';
import { REQUEST_ID, serveReference } from './testData';

const get = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get, post: vi.fn(), patch: vi.fn(), delete: vi.fn() } }));

const nodes = vi.hoisted(() => ({ value: {} as Record<string, string[]> }));
vi.mock('@/hooks/usePermissions', () => ({
  usePermissions: () => ({
    atLeast: () => true,
    can: (node: string, flag: string) => (nodes.value[node] ?? []).includes(flag),
    isLoading: false,
  }),
}));

const ROWS = [
  {
    id: REQUEST_ID, number: 'ЗТ-2026-000007', status: 'in_approval',
    status_display: 'На согласовании', project_id: 'p21', project_code: 'П-021',
    project_name: 'Склад', purchase_type: 'goods', need_date: '2099-11-01',
    created_at: '2026-10-07T09:00:00Z', author_id: 904, author_name: 'Иванов А.',
  },
];

function serve(rows: unknown = ROWS) {
  get.mockImplementation((url: string) => {
    if (url.endsWith('tender/v1/requests')) {
      return Promise.resolve({
        data: Array.isArray(rows) ? { results: rows, total: rows.length, page: 1, page_size: 50 } : rows,
      });
    }
    return Promise.resolve(serveReference(url) ?? { data: [] });
  });
}

function renderPage() {
  return render(
    <QueryClientProvider client={createTestQueryClient()}>
      <MemoryRouter initialEntries={['/tender/requests']}>
        <RequestsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('RequestsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    nodes.value = {};
  });

  it('строка: номер ссылкой на карточку, статус, проект, автор', async () => {
    serve();
    renderPage();

    const link = await screen.findByRole('link', { name: 'ЗТ-2026-000007' });
    expect(link).toHaveAttribute('href', `/tender/requests/${REQUEST_ID}`);
    const row = link.closest('tr') as HTMLElement;
    expect(within(row).getByText('На согласовании')).toBeInTheDocument();
    // Проект — из строки реестра (`project_code`), без отдельного запроса проектов.
    expect(within(row).getByText('П-021')).toBeInTheDocument();
    expect(get).not.toHaveBeenCalledWith(expect.stringContaining('requests/projects'), expect.anything());
    expect(within(row).getByText('Иванов А.')).toBeInTheDocument();
    expect(within(row).getByText('01.11.2099')).toBeInTheDocument();
  });

  it('ответ страницей {results} тоже читается', async () => {
    serve({ results: ROWS, total: 1 });
    renderPage();
    expect(await screen.findByRole('link', { name: 'ЗТ-2026-000007' })).toBeInTheDocument();
  });

  it('поиск уходит параметром q', async () => {
    serve();
    renderPage();
    await screen.findByRole('link', { name: 'ЗТ-2026-000007' });

    await userEvent.type(screen.getByRole('searchbox'), 'швеллер');
    await waitFor(() => expect(get).toHaveBeenCalledWith(
      expect.stringContaining('tender/v1/requests'),
      { params: expect.objectContaining({ q: 'швеллер' }) },
    ));
  });

  it('пустой реестр — объяснение', async () => {
    serve([]);
    renderPage();
    expect(await screen.findByText('Заявок пока нет')).toBeInTheDocument();
  });

  it('«Создать заявку» — только с правом create', async () => {
    serve();
    const { unmount } = renderPage();
    await screen.findByRole('link', { name: 'ЗТ-2026-000007' });
    expect(screen.queryByRole('link', { name: /Создать заявку/ })).not.toBeInTheDocument();
    unmount();

    nodes.value = { 'tender.requests': ['view', 'create'] };
    renderPage();
    expect(await screen.findByRole('link', { name: /Создать заявку/ }))
      .toHaveAttribute('href', '/tender/requests/new');
  });
});
