/**
 * Реестр L-06 (ТЗ §10.5): вкладка — параметр `tab` адреса и запроса (смена
 * вкладки пишет его в адрес, «Все» и неизвестная — адрес без него); ФД на вкладке
 * «На решение ФД» не оплачивает отмеченные без причины и видит итог по
 * каждому счёту. Ссылка показателя дашборда «Оплаты» (D-S4-8): отбор из
 * адреса уходит в запрос как есть (режим ссылки — только при фильтрах, одна
 * вкладка в адресе — обычный реестр), сохранённые фильтры панели его не сужают,
 * «Показать весь реестр», смена вкладки и переход из меню возвращают обычный
 * реестр; экспорт очереди в режиме ссылки подписан «вся очередь».
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { Link, MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

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

/** Строка запроса текущего адреса — чтобы проверить, что вкладка живёт в нём. */
function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location-search">{location.search}</output>;
}

const locationSearch = () => screen.getByTestId('location-search').textContent;

function renderAt(route: string) {
  return render(
    <QueryClientProvider client={createTestQueryClient()}>
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route path="/bpp/invoices" element={(
            <>
              {/* Пункт меню «Счета» — тот же маршрут без параметров. */}
              <Link to="/bpp/invoices">Меню: Счета</Link>
              <LocationProbe />
              <InvoicesPage />
            </>
          )} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const lastRegistryUrl = () => String(get.mock.calls.filter(([url]) => String(url).includes('invoices')).at(-1)?.[0]);

describe('InvoicesPage', () => {
  afterEach(() => window.localStorage.clear());

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

  it('ссылка дашборда: отбор из адреса — в запрос, сохранённые фильтры не подмешиваются', { timeout: 20000 }, async () => {
    window.localStorage.setItem('bpp:registry:invoices', JSON.stringify({
      pageSize: 50, sort: null, filters: { status: 'draft', basis: 'contract' }, hidden: [],
    }));
    get.mockImplementation((url: string) => {
      if (url.includes('invoices')) {
        return Promise.resolve({ data: {
          items: [ROW], total: 1, page: 1, page_size: 50,
          totals: { amount_kzt: '1000.00', paid_bank_amount: '0.00' },
        } });
      }
      if (url.includes('projects')) {
        return Promise.resolve({ data: [{ id: 'p1', code: 'П-015', name: 'Объект' }] });
      }
      return Promise.resolve({ data: [] });
    });
    const link = 'tab=bank_unconfirmed&status=to_pay&status=paid&recon_status=full&recon_status=partial'
      + '&project_id=p1&article_id=a1&counterparty_id=c1&author_id=7'
      + '&bank_date_from=2026-09-01&bank_date_to=2026-09-30&bank_wait_days=3&junk=x';
    render(
      <QueryClientProvider client={createTestQueryClient()}>
        <MemoryRouter initialEntries={[`/bpp/invoices?${link}`]}>
          <Routes><Route path="/bpp/invoices" element={<InvoicesPage />} /></Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByRole('tab', { name: 'Оплачено, банк не подтвердил' }))
      .toHaveAttribute('aria-selected', 'true');
    const registryCall = () => get.mock.calls.find(([url]) => String(url).includes('invoices?'));
    await waitFor(() => expect(registryCall()).toBeDefined());
    const [url, config] = registryCall()!;
    const query = new URL(String(url), 'http://host').searchParams;
    expect(query.get('tab')).toBe('bank_unconfirmed');
    expect(query.getAll('status')).toEqual(['to_pay', 'paid']);
    expect(query.getAll('recon_status')).toEqual(['full', 'partial']);
    expect(Object.fromEntries([...query].filter(([key]) => !['status', 'recon_status'].includes(key))))
      .toEqual({
        tab: 'bank_unconfirmed', project_id: 'p1', article_id: 'a1', counterparty_id: 'c1',
        author_id: '7', bank_date_from: '2026-09-01', bank_date_to: '2026-09-30', bank_wait_days: '3',
      });
    // Сохранённые «Черновик» и «По договору» сузили бы выборку против карточки.
    expect(config.params).toEqual({ page: 1, page_size: 50 });

    const note = screen.getByRole('note');
    expect(note).toHaveTextContent('Отбор с дашборда оплат');
    expect(await within(note).findByText('Проект: П-015 — Объект')).toBeInTheDocument();
    expect(note).toHaveTextContent('Сверка с банком: Оплачен полностью, Оплачен частично');
    expect(note).toHaveTextContent('Платёж по банку: с 01.09.2026 по 30.09.2026');

    get.mockClear();
    await userEvent.click(within(note).getByRole('button', { name: 'Показать весь реестр' }));
    await waitFor(() => expect(get.mock.calls.some(([next]) => String(next).endsWith('bpp/v1/invoices'))).toBe(true));
    expect(screen.queryByRole('note')).toBeNull();
    expect(screen.getByRole('tab', { name: 'Все' })).toHaveAttribute('aria-selected', 'true');
    const plain = get.mock.calls.find(([next]) => String(next).endsWith('bpp/v1/invoices'))!;
    expect(plain[1].params).toMatchObject({ status: 'draft', basis: 'contract' });
  });

  it('ссылка дашборда: смена вкладки выходит из отбора — новая вкладка без параметров ссылки', { timeout: 20000 }, async () => {
    renderAt('/bpp/invoices?tab=fd&project_id=p1');
    expect(await screen.findByRole('tab', { name: 'На решение ФД' })).toHaveAttribute('aria-selected', 'true');
    await waitFor(() => expect(lastRegistryUrl()).toMatch(/invoices\?project_id=p1&tab=fd$/));

    await userEvent.click(screen.getByRole('tab', { name: 'К оплате' }));

    await waitFor(() => expect(lastRegistryUrl()).toMatch(/invoices\?tab=to_pay$/));
    expect(screen.getByRole('tab', { name: 'К оплате' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.queryByRole('note')).toBeNull();
    expect(locationSearch()).toBe('?tab=to_pay');
  });

  it('вкладка живёт в адресе: клик пишет ?tab=, «Все» его убирает; режима ссылки нет', { timeout: 20000 }, async () => {
    window.localStorage.setItem('bpp:registry:invoices', JSON.stringify({
      pageSize: 50, sort: null, filters: { basis: 'contract' }, hidden: [],
    }));
    renderAt('/bpp/invoices');
    expect(await screen.findByRole('tab', { name: 'Все' })).toHaveAttribute('aria-selected', 'true');

    await userEvent.click(screen.getByRole('tab', { name: 'Ждут закрывающих' }));

    await waitFor(() => expect(locationSearch()).toBe('?tab=awaiting_docs'));
    await waitFor(() => expect(lastRegistryUrl()).toMatch(/invoices\?tab=awaiting_docs$/));
    // Вкладка в адресе — не отбор ссылки: плашки нет, сохранённые фильтры панели работают.
    expect(screen.queryByRole('note')).toBeNull();
    const call = get.mock.calls.filter(([url]) => String(url).includes('invoices?tab=awaiting_docs')).at(-1)!;
    expect(call[1].params).toMatchObject({ basis: 'contract' });

    await userEvent.click(screen.getByRole('tab', { name: 'Все' }));
    await waitFor(() => expect(locationSearch()).toBe(''));
    expect(screen.getByRole('tab', { name: 'Все' })).toHaveAttribute('aria-selected', 'true');
  });

  it('адрес с одной вкладкой — обычный реестр этой вкладки, с панелью фильтров', { timeout: 20000 }, async () => {
    window.localStorage.setItem('bpp:registry:invoices', JSON.stringify({
      pageSize: 50, sort: null, filters: { basis: 'contract' }, hidden: [],
    }));
    renderAt('/bpp/invoices?tab=fd');
    expect(await screen.findByRole('tab', { name: 'На решение ФД' })).toHaveAttribute('aria-selected', 'true');
    await waitFor(() => expect(lastRegistryUrl()).toMatch(/invoices\?tab=fd$/));
    expect(screen.queryByRole('note')).toBeNull();
    const call = get.mock.calls.filter(([url]) => String(url).includes('invoices?tab=fd')).at(-1)!;
    expect(call[1].params).toMatchObject({ basis: 'contract' });
    expect(locationSearch()).toBe('?tab=fd');
  });

  it('смена вкладки начинает с первой страницы, поиск остаётся', { timeout: 20000 }, async () => {
    // 500 строк — третья страница существует, реестр её не прижимает.
    get.mockImplementation((url: string) => Promise.resolve({ data: url.includes('invoices') ? {
      items: [ROW], total: 500, page: 3, page_size: 50,
      totals: { amount_kzt: '1000.00', paid_bank_amount: '0.00' },
    } : [] }));
    renderAt('/bpp/invoices?page=3&q=145');

    await userEvent.click(await screen.findByRole('tab', { name: 'К оплате' }));
    await waitFor(() => expect(locationSearch()).toContain('tab=to_pay'));
    const search = new URLSearchParams(locationSearch() ?? '');
    expect(search.get('page')).toBeNull();
    expect(search.get('q')).toBe('145');
    await waitFor(() => expect(lastRegistryUrl()).toMatch(/invoices\?tab=to_pay$/));
  });

  it('«Статус сверки» — колонка и фильтр панели: фильтр уходит в запрос, режима ссылки нет', { timeout: 20000 }, async () => {
    // Сохранённый фильтр неизвестного реестру ключа отбрасывается при чтении —
    // значит, дошедший до запроса `recon_status` объявлен в панели.
    window.localStorage.setItem('bpp:registry:invoices', JSON.stringify({
      pageSize: 50, sort: null, filters: { recon_status: 'partial' }, hidden: [],
    }));
    get.mockImplementation((url: string) => Promise.resolve({ data: url.includes('invoices') ? {
      items: [{ ...ROW, recon_status: 'partial', paid_bank_amount: '400.00' }], total: 1,
      page: 1, page_size: 50, totals: { amount_kzt: '1000.00', paid_bank_amount: '400.00' },
    } : [] }));
    renderAt('/bpp/invoices');

    expect(await screen.findByRole('columnheader', { name: 'Статус сверки' })).toBeInTheDocument();
    const row = (await screen.findByText('СЧ-2026-000001')).closest('tr')!;
    expect(within(row).getByText('Оплачен частично')).toBeInTheDocument();
    await waitFor(() => {
      const call = get.mock.calls.filter(([url]) => String(url).includes('invoices')).at(-1)!;
      expect(call[1].params).toMatchObject({ recon_status: 'partial' });
    });
    expect(screen.queryByRole('note')).toBeNull();
    expect(locationSearch()).toBe('');
  });

  it.each(['all', 'bogus'])('?tab=%s приводится к адресу без параметра — вкладка «Все»', { timeout: 20000 }, async (value) => {
    renderAt(`/bpp/invoices?tab=${value}`);
    expect(await screen.findByRole('tab', { name: 'Все' })).toHaveAttribute('aria-selected', 'true');
    await waitFor(() => expect(locationSearch()).toBe(''));
    await waitFor(() => expect(lastRegistryUrl()).toMatch(/bpp\/v1\/invoices$/));
    expect(screen.queryByRole('note')).toBeNull();
  });

  it('ссылка дашборда: переход из меню «Счета» — вкладка «Все», а не вкладка ссылки', { timeout: 20000 }, async () => {
    renderAt('/bpp/invoices?tab=fd&project_id=p1');
    expect(await screen.findByRole('tab', { name: 'На решение ФД' })).toHaveAttribute('aria-selected', 'true');

    await userEvent.click(screen.getByRole('link', { name: 'Меню: Счета' }));

    await waitFor(() => expect(lastRegistryUrl()).toMatch(/bpp\/v1\/invoices$/));
    expect(screen.getByRole('tab', { name: 'Все' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.queryByRole('note')).toBeNull();
  });

  it('экспорт очереди в режиме ссылки подписан «вся очередь» — отбора ссылки он не знает', { timeout: 20000 }, async () => {
    renderAt('/bpp/invoices?tab=to_pay&project_id=p1');
    expect(await screen.findByRole('button', { name: 'Экспорт всей очереди к оплате' })).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Показать весь реестр' }));
    await userEvent.click(screen.getByRole('tab', { name: 'К оплате' }));
    expect(await screen.findByRole('button', { name: 'Экспорт очереди к оплате' })).toBeInTheDocument();
  });
});
