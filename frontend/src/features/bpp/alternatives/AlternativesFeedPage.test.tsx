/**
 * Лента L-09 (ТЗ §12.2): фильтры панели и отбор ссылкой уведомления уходят в
 * запрос; строка без моей АП — «Предложить альтернативу», с моей — ссылка на
 * неё; «Показать всю ленту» снимает отбор по документу.
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { createTestQueryClient } from '@/test/renderWithProviders';

import { AlternativesFeedPage } from './AlternativesFeedPage';

const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get, post } }));
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() } }));
vi.mock('@/hooks/usePermissions', () => ({
  usePermissions: () => ({ can: () => true, atLeast: () => true }),
}));

const BASE = {
  source_type: 'invoice', kind_label: 'Счёт без договора', url: '/bpp/invoices/inv1',
  author_id: 7, author_name: 'Петров', project: { id: 'p', code: 'П-015', name: 'Объект' },
  article: { id: 'a', code: 'T', name: 'Металлопрокат' },
  counterparty: { id: 'c', name: 'ТОО «Альфа»', reg_number: '1' },
  positions: { names: ['Швеллер', 'Арматура'], more: 2, count: 4 },
  amount: '2800000.00', currency_code: 'KZT', sent_at: '2026-09-29T05:00:00Z', alt_limit: 3,
};
const ROWS = [
  { ...BASE, source_id: 'inv1', number: 'СЧ-2026-000140', offers_count: 0, my_offer: null },
  {
    ...BASE, source_id: 'inv2', number: 'СЧ-2026-000141', offers_count: 1,
    my_offer: { id: 'o1', number: 'АП-2026-000001', status: 'draft', status_label: 'Черновик' },
  },
];

function Probe() {
  const location = useLocation();
  return <output data-testid="search">{location.search}</output>;
}

function renderAt(route: string) {
  return render(
    <QueryClientProvider client={createTestQueryClient()}>
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route path="/bpp/alternatives" element={<><Probe /><AlternativesFeedPage /></>} />
          <Route path="/bpp/alternatives/:id" element={<div>Форма АП</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const feedCalls = () => get.mock.calls.filter(([url]) => String(url).includes('alternatives/feed'));

describe('AlternativesFeedPage', () => {
  afterEach(() => window.localStorage.clear());
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    get.mockImplementation((url: string) => {
      const target = String(url);
      if (target.includes('alternatives/feed')) {
        return Promise.resolve({ data: { items: ROWS, total: 2, page: 1, page_size: 50 } });
      }
      if (target.includes('counterparties')) {
        return Promise.resolve({ data: { items: [{
          id: 'cp-9', name: 'ТОО «Бета»', short_name: '', reg_number: '200000000002',
          country_code: 'KZ', is_vat_payer: true, status: 'active', is_verified: true,
        }] } });
      }
      if (target.includes('projects')) {
        return Promise.resolve({ data: [
          { id: 'pr1', code: 'П-1', name: 'Один' }, { id: 'pr2', code: 'П-2', name: 'Два' },
        ] });
      }
      return Promise.resolve({ data: [] });
    });
  });

  it('строки: «Предложить» у документа без моей АП, ссылка — у документа с ней', { timeout: 15000 }, async () => {
    renderAt('/bpp/alternatives');
    expect(await screen.findByText('СЧ-2026-000140', {}, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Предложить альтернативу' })).toHaveLength(1);
    expect(screen.getByRole('link', { name: 'АП-2026-000001' })).toHaveAttribute('href', '/bpp/alternatives/o1');
    expect(screen.getAllByText(/и ещё 2/)).toHaveLength(2);
  });

  it('«Предложить» заводит черновик и открывает форму', { timeout: 15000 }, async () => {
    post.mockResolvedValue({ data: { id: 'new1' } });
    renderAt('/bpp/alternatives');
    await userEvent.click(await screen.findByRole('button', { name: 'Предложить альтернативу' }, { timeout: 4000 }));
    expect(await screen.findByText('Форма АП')).toBeInTheDocument();
    expect(post.mock.calls[0][1]).toEqual({ source_type: 'invoice', source_id: 'inv1' });
  });

  it('фильтры панели уходят в запрос («без альтернатив», «только мои»)', { timeout: 15000 }, async () => {
    window.localStorage.setItem('bpp:registry:alternatives', JSON.stringify({
      pageSize: 50, sort: null, filters: { without_offers: '1', mine: 'yes', kind: 'invoice' }, hidden: [],
    }));
    renderAt('/bpp/alternatives');
    await screen.findByText('СЧ-2026-000140', {}, { timeout: 4000 });
    const call = feedCalls().at(-1)!;
    expect(call[1].params).toMatchObject({ without_offers: '1', mine: 'yes', kind: 'invoice' });
  });

  it('ссылка уведомления: source идёт в запрос, плашка снимается кнопкой', { timeout: 15000 }, async () => {
    renderAt('/bpp/alternatives?source=invoice:inv1');
    await screen.findByText('СЧ-2026-000140', {}, { timeout: 4000 });
    expect(String(feedCalls().at(-1)![0])).toContain('source=invoice%3Ainv1');
    expect(screen.getByRole('note')).toHaveTextContent('Отбор по документу');

    await userEvent.click(screen.getByRole('button', { name: 'Показать всю ленту' }));
    await waitFor(() => expect(screen.getByTestId('search').textContent).toBe(''));
    await waitFor(() => expect(String(feedCalls().at(-1)![0])).not.toContain('source='));
    expect(screen.queryByRole('note')).toBeNull();
  });

  it('проекты — множественный выбор: повторяемый project_id в запросе', { timeout: 20000 }, async () => {
    renderAt('/bpp/alternatives');
    await screen.findByText('СЧ-2026-000140', {}, { timeout: 4000 });
    await userEvent.click(screen.getByRole('button', { name: 'Проект' }));
    await userEvent.click(await screen.findByRole('menuitemcheckbox', { name: 'П-1 — Один' }));
    await userEvent.click(screen.getByRole('menuitemcheckbox', { name: 'П-2 — Два' }));
    await waitFor(() => expect(screen.getByTestId('search').textContent).toBe('?project_id=pr1&project_id=pr2'));
    await waitFor(() => expect(String(feedCalls().at(-1)![0])).toContain('project_id=pr1&project_id=pr2'));
  });

  it('автор — из строк ленты, уходит как author_id', { timeout: 20000 }, async () => {
    renderAt('/bpp/alternatives');
    await screen.findByText('СЧ-2026-000140', {}, { timeout: 4000 });
    await userEvent.click(screen.getByRole('combobox', { name: 'Автор' }));
    await userEvent.click(await screen.findByRole('option', { name: 'Петров' }));
    await waitFor(() => expect(String(feedCalls().at(-1)![0])).toContain('author_id=7'));
  });

  it('контрагент — общий CounterpartyPicker, уходит как counterparty_id', { timeout: 20000 }, async () => {
    renderAt('/bpp/alternatives');
    await screen.findByText('СЧ-2026-000140', {}, { timeout: 4000 });
    await userEvent.click(screen.getByPlaceholderText(/Наименование \(от 3 букв\)/));
    await userEvent.type(screen.getByPlaceholderText(/Наименование \(от 3 букв\)/), 'Бета');
    await userEvent.click(await screen.findByRole('button', { name: /ТОО «Бета»/ }, { timeout: 4000 }));
    await waitFor(() => expect(String(feedCalls().at(-1)![0])).toContain('counterparty_id=cp-9'));
    await userEvent.click(screen.getByRole('button', { name: 'Сбросить контрагента' }));
    await waitFor(() => expect(screen.getByTestId('search').textContent).toBe(''));
    expect(screen.queryByRole('button', { name: 'Сбросить контрагента' })).toBeNull();
  });
});
