/**
 * Дашборд D-01 «Оплаты» (ТЗ §11.5): карточка показателя ведёт на реестр
 * счетов по адресу сервера, без ссылки — просто карточка; смена фильтра
 * перечитывает дашборд, не роняя экран в скелетон; неверная дата периода —
 * ошибка, а не молча снятый фильтр; авторы счёта — из ответа дашборда, а не
 * из кадров; выключенный у компании подмодуль назван, а не выдан за «данных
 * нет»; графики получают суммы строками через `formatMoney`; без проекта —
 * подсказка вместо столбцов по статьям.
 */
import type { ReactNode } from 'react';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';

import type { PaymentsDashboard } from './api';
import { PaymentsDashboardPage } from './PaymentsDashboardPage';

const get = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get, post: vi.fn() } }));
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() } }));

const reportApiError = vi.hoisted(() => vi.fn());
vi.mock('@/lib/apiError', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/apiError')>()),
  reportApiError,
}));

// jsdom не меряет контейнер — recharts там ничего не рисует. Графики
// подменены: видно, какие строки данных им передал экран.
vi.mock('recharts', () => {
  const chart = (testId: string) => function Chart({ data, children }: { data: unknown; children?: ReactNode }) {
    return <div data-testid={testId} data-rows={JSON.stringify(data)}>{children}</div>;
  };
  const nothing = () => null;
  return {
    ResponsiveContainer: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
    BarChart: chart('bar-chart'),
    LineChart: chart('line-chart'),
    Bar: ({ dataKey }: { dataKey: string }) => <span data-testid={`bar-${dataKey}`} />,
    Line: nothing, CartesianGrid: nothing, Legend: nothing, Tooltip: nothing, XAxis: nothing, YAxis: nothing,
  };
});

const DASHBOARD: PaymentsDashboard = {
  filters: {},
  sections: { invoices: true, bank: true, budget: true },
  authors: [{ id: 7, name: 'Снабженцев Иван' }, { id: 99, name: null }],
  indicators: [
    { key: 'fd', label: 'Счета на решении ФД', count: 2, amount: '1500.00', link: '/bpp/invoices?tab=fd' },
    {
      key: 'to_pay', label: 'К оплате', count: 3, amount: '1250000.50',
      link: '/bpp/invoices?tab=to_pay&project_id=p1&author_id=7',
    },
    { key: 'unmatched', label: 'Несопоставленные списания', count: 4, amount: '800.00', link: null },
  ],
  article_chart: [],
  weekly_paid: [
    { week_start: '2026-09-07', amount: '0.00' },
    { week_start: '2026-09-14', amount: '99999999999999.99' },
  ],
  top_counterparties: [
    { counterparty_id: 'c1', name: 'ТОО «Альфа»', amount: '99999999999999.99' },
  ],
  as_of: '2026-09-30T04:00:00Z',
};

const ARTICLE_CHART = [{
  article_id: 'a1', code: 'T-METAL', name: 'Металлопрокат',
  limit: '1250000.50', committed: '400000.00', paid_fact: '100000.10',
}];

type Params = Record<string, string>;
/** Ответ дашборда на параметры запроса; тест может подменить. */
let dashboardReply: (params: Params) => Promise<unknown>;
let projectsReply: () => Promise<unknown>;

const dashboardCalls = () => get.mock.calls.filter(([url]) => String(url).includes('dashboard/payments'));
const withData = (patch: Partial<PaymentsDashboard>) => () => Promise.resolve({ data: { ...DASHBOARD, ...patch } });

beforeEach(() => {
  get.mockReset();
  reportApiError.mockReset();
  dashboardReply = (params) => Promise.resolve({
    data: { ...DASHBOARD, article_chart: params.project_id ? ARTICLE_CHART : [] },
  });
  projectsReply = () => Promise.resolve({ data: [{ id: 'p1', code: 'П-015', name: 'Объект' }] });
  get.mockImplementation((url: string, config?: { params?: Params }) => {
    if (url.includes('dashboard/payments')) return dashboardReply(config?.params ?? {});
    if (url.includes('projects')) return projectsReply();
    if (url.includes('articles')) {
      return Promise.resolve({ data: [{ id: 'a1', code: 'T-METAL', name: 'Металлопрокат', is_active: true }] });
    }
    return Promise.resolve({ data: { items: [], total: 0 } });
  });
});

function Registry() {
  const location = useLocation();
  return <div>Реестр счетов {location.search}</div>;
}

function renderDashboard(route = '/bpp/dashboard') {
  return renderWithProviders(
    <Routes>
      <Route path="/bpp/dashboard" element={<PaymentsDashboardPage />} />
      <Route path="/bpp/invoices" element={<Registry />} />
    </Routes>,
    { route },
  );
}

async function pickProject() {
  await userEvent.click(screen.getByRole('combobox', { name: 'Проект' }));
  await userEvent.click(await screen.findByRole('option', { name: 'П-015 — Объект' }));
}

describe('PaymentsDashboardPage', () => {
  it('карточка ведёт на реестр счетов по ссылке сервера; без ссылки — не ссылка', { timeout: 20000 }, async () => {
    renderDashboard();

    const toPay = await screen.findByRole('link', { name: /К оплате/ });
    expect(toPay).toHaveAttribute('href', '/bpp/invoices?tab=to_pay&project_id=p1&author_id=7');
    expect(toPay).toHaveTextContent('3 шт.');
    expect(toPay).toHaveTextContent('1 250 000,50 KZT');

    // «Несопоставленные» без права на выписки — карточка без перехода.
    expect(screen.getByText('Несопоставленные списания')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Несопоставленные списания/ })).toBeNull();

    await userEvent.click(toPay);
    expect(await screen.findByText(/Реестр счетов/)).toHaveTextContent(
      '?tab=to_pay&project_id=p1&author_id=7',
    );
  });

  it('смена фильтра перечитывает дашборд с новым параметром', { timeout: 20000 }, async () => {
    renderDashboard();
    await screen.findByRole('link', { name: /К оплате/ });
    expect(dashboardCalls()).toHaveLength(1);
    expect(dashboardCalls()[0][1]).toEqual({ params: {} });

    await pickProject();

    await waitFor(() => expect(dashboardCalls()).toHaveLength(2));
    expect(dashboardCalls()[1][1]).toEqual({ params: { project_id: 'p1' } });
    expect(await screen.findByTestId('bar-chart')).toBeInTheDocument();
  });

  it('пока новый отбор загружается, прежние цифры видны приглушёнными, без скелетона', { timeout: 20000 }, async () => {
    renderDashboard();
    await screen.findByRole('link', { name: /К оплате/ });
    let release: (value: unknown) => void = () => undefined;
    dashboardReply = () => new Promise((resolve) => { release = resolve; });

    await pickProject();
    await waitFor(() => expect(dashboardCalls()).toHaveLength(2));

    const card = screen.getByRole('link', { name: /К оплате/ });
    expect(card.closest('[aria-busy]')).toHaveAttribute('aria-busy', 'true');
    release({ data: { ...DASHBOARD, article_chart: ARTICLE_CHART } });
    expect(await screen.findByTestId('bar-chart')).toBeInTheDocument();
    expect(document.querySelector('[aria-busy]')).toBeNull();
  });

  it('фильтры из адреса уходят в запрос, посторонние параметры — нет', { timeout: 20000 }, async () => {
    renderDashboard('/bpp/dashboard?period_from=2026-09-01&period_to=2026-09-30&author_id=7&junk=1');
    await screen.findByRole('link', { name: /К оплате/ });
    expect(dashboardCalls()[0][1]).toEqual({
      params: { period_from: '2026-09-01', period_to: '2026-09-30', author_id: '7' },
    });
  });

  it('период «по» раньше «с» — ошибка на экране, дашборд не запрашивается', async () => {
    renderDashboard('/bpp/dashboard?period_from=2026-09-30&period_to=2026-09-01');
    expect(await screen.findByRole('alert')).toHaveTextContent('Дата «по» раньше даты «с».');
    expect(dashboardCalls()).toHaveLength(0);
  });

  it('несуществующая дата периода — ошибка, а не отчёт за всё время; сброс очищает поле', { timeout: 20000 }, async () => {
    renderDashboard();
    await screen.findByRole('link', { name: /К оплате/ });

    const from = screen.getByRole('textbox', { name: 'Оплата с' });
    await userEvent.type(from, '31022026');

    expect(from).toHaveValue('31.02.2026');
    expect(await screen.findByRole('alert')).toHaveTextContent('Дата периода введена неверно');
    expect(from).toHaveAttribute('aria-invalid', 'true');
    // Прежние цифры за «всё время» не выдаются за ответ на неверный отбор.
    expect(screen.queryByRole('link', { name: /К оплате/ })).toBeNull();
    expect(dashboardCalls()).toHaveLength(1);

    await userEvent.click(screen.getByRole('button', { name: 'Сбросить фильтры' }));
    expect(await screen.findByRole('link', { name: /К оплате/ })).toBeInTheDocument();
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.getByRole('textbox', { name: 'Оплата с' })).toHaveValue('');
  });

  it('авторы — из ответа дашборда, кадры не запрашиваются; без учётки и из адреса — «Пользователь №»', { timeout: 20000 }, async () => {
    renderDashboard('/bpp/dashboard?author_id=42');
    await screen.findByRole('link', { name: /К оплате/ });

    await userEvent.click(screen.getByRole('combobox', { name: 'Автор счёта' }));
    const list = await screen.findByRole('listbox');
    expect(within(list).getAllByRole('option').map((option) => option.textContent)).toEqual([
      'Все авторы', 'Пользователь №42', 'Снабженцев Иван', 'Пользователь №99',
    ]);
    expect(get.mock.calls.some(([url]) => String(url).includes('hr/'))).toBe(false);

    await userEvent.click(within(list).getByRole('option', { name: 'Снабженцев Иван' }));
    await waitFor(() => expect(dashboardCalls().at(-1)?.[1]).toEqual({ params: { author_id: '7' } }));
  });

  it('видимых счетов нет — подсказка у фильтра автора', { timeout: 20000 }, async () => {
    dashboardReply = withData({ authors: [] });
    renderDashboard();
    expect(await screen.findByText(/Видимых вам счетов пока нет/)).toBeInTheDocument();
  });

  it('графики получают суммы строками через formatMoney', { timeout: 20000 }, async () => {
    renderDashboard('/bpp/dashboard?project_id=p1');

    const bars = JSON.parse((await screen.findByTestId('bar-chart')).getAttribute('data-rows') ?? '[]');
    expect(bars).toEqual([expect.objectContaining({
      name: 'T-METAL Металлопрокат',
      limitText: '1 250 000,50', committedText: '400 000,00', paid_factText: '100 000,10',
    })]);
    expect(screen.getByTestId('bar-paid_fact')).toBeInTheDocument();

    const weeks = JSON.parse(screen.getByTestId('line-chart').getAttribute('data-rows') ?? '[]');
    // `Number("99999999999999.99")` теряет последний разряд — подпись из строки его хранит.
    expect(weeks.map((row: { week: string; amountText: string }) => [row.week, row.amountText])).toEqual([
      ['07.09.2026', '0,00'], ['14.09.2026', '99 999 999 999 999,99'],
    ]);
    expect(screen.getByRole('cell', { name: '99 999 999 999 999,99' })).toBeInTheDocument();
  });

  it('без проекта — подсказка выбрать проект вместо столбцов', async () => {
    renderDashboard();
    expect(await screen.findByText(/Выберите проект, чтобы увидеть лимиты/)).toBeInTheDocument();
    expect(screen.queryByTestId('bar-chart')).toBeNull();
  });

  it('проект без действующего бюджета — своя подсказка, без столбцов', async () => {
    dashboardReply = withData({ article_chart: [] });
    renderDashboard('/bpp/dashboard?project_id=p1');
    expect(await screen.findByText(/У проекта нет действующего бюджета/)).toBeInTheDocument();
    expect(screen.queryByTestId('bar-chart')).toBeNull();
  });

  it('«Оплачено факт» не посчитано (`null`) — ряда нет', { timeout: 20000 }, async () => {
    dashboardReply = withData({ article_chart: [{ ...ARTICLE_CHART[0], paid_fact: null }] });
    renderDashboard('/bpp/dashboard?project_id=p1');
    expect(await screen.findByTestId('bar-chart')).toBeInTheDocument();
    expect(screen.getByTestId('bar-limit')).toBeInTheDocument();
    expect(screen.queryByTestId('bar-paid_fact')).toBeNull();
  });

  it('банк выключен у компании — так и написано, а не «платежей нет»', { timeout: 20000 }, async () => {
    dashboardReply = withData({
      sections: { invoices: true, bank: false, budget: true },
      indicators: DASHBOARD.indicators.slice(0, 2), weekly_paid: [], top_counterparties: [],
    });
    renderDashboard();
    await screen.findByRole('link', { name: /К оплате/ });

    expect(screen.getByText(/Сверка с банком у компании выключена — показателей по выписке/)).toBeInTheDocument();
    expect(screen.getAllByText('Сверка с банком у компании выключена — оплат по банку нет.')).toHaveLength(2);
    expect(screen.queryByText('Платежей по банку за период нет.')).toBeNull();
  });

  it('счета и банк выключены — показателей нет, и это объяснено; бюджеты выключены — у столбцов', { timeout: 20000 }, async () => {
    dashboardReply = withData({
      sections: { invoices: false, bank: false, budget: false },
      authors: [], indicators: [], weekly_paid: [], top_counterparties: [],
    });
    renderDashboard('/bpp/dashboard?project_id=p1');

    expect(await screen.findByText(/Счета на оплату у компании выключены — показателей по счетам/)).toBeInTheDocument();
    expect(screen.getByText(/Сверка с банком у компании выключена — показателей по выписке/)).toBeInTheDocument();
    expect(screen.getByText('Бюджеты у компании выключены — лимитов по статьям нет.')).toBeInTheDocument();
    expect(screen.getAllByText('Счета на оплату у компании выключены — оплат по счетам нет.')).toHaveLength(2);
    expect(screen.getByText(/фильтр по автору не действует/)).toBeInTheDocument();
    expect(screen.queryByText(/Видимых вам счетов пока нет/)).toBeNull();
  });

  it('ошибка дашборда — reportApiError и строка на экране', { timeout: 20000 }, async () => {
    const failure = Object.assign(new Error('503'), { response: { status: 503, data: { detail: 'Модуль выключен' } } });
    dashboardReply = () => Promise.reject(failure);
    renderDashboard();

    expect(await screen.findByText('Не удалось загрузить дашборд оплат')).toBeInTheDocument();
    expect(reportApiError).toHaveBeenCalledWith(failure, 'Не удалось загрузить дашборд оплат');
  });

  it('ошибка списка проектов — reportApiError и подсказка у фильтра', { timeout: 20000 }, async () => {
    const failure = Object.assign(new Error('403'), { response: { status: 403, data: { detail: 'Нет прав' } } });
    projectsReply = () => Promise.reject(failure);
    renderDashboard();

    expect(await screen.findByText(/Не удалось загрузить проекты — фильтр по проекту недоступен/)).toBeInTheDocument();
    expect(reportApiError).toHaveBeenCalledWith(failure, 'Не удалось загрузить проекты');
  });
});
