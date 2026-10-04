/**
 * «Обзор» модуля по ролям (ТЗ §05, §17): карточки — только пришедших
 * блоков, раздел без карточек не рисуется; показатели сверху — «Ждут моего
 * решения» и главная очередь роли; бюджеты — каждый проект отдельно, без
 * общей суммы (у АДМ денег нет вовсе), строка — ссылка на карточку бюджета;
 * очереди счетов ведут на вкладку реестра (`?tab=`), статусы — без ссылки и
 * без нулей; «Создать» — по `can_create`; ошибка загрузки — с повтором;
 * ссылки «Обзора» — на настоящие маршруты подмодулей.
 */
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';

import { bppModules } from '../modules';
import {
  OVERVIEW_ENDPOINT, OVERVIEW_LINKS, type BudgetProjectMoney, type Overview,
} from './api';
import { OverviewPage } from './OverviewPage';

const get = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get, post: vi.fn() } }));

const budget = (n: number, over: Partial<BudgetProjectMoney> = {}): BudgetProjectMoney => ({
  budget_id: `b${n}`, project: { id: `p${n}`, code: `П-0${String(n).padStart(2, '0')}`, name: `Объект ${n}` },
  currency_code: 'KZT', limit_amount: '20000000.00', committed: '7500000.00',
  available: '12500000.00', ...over,
});

const FD: Overview = {
  shows_money: true,
  budgets: {
    total: 3, approved: 2, draft: 1, can_create: true,
    projects: [
      budget(1),
      budget(2, { currency_code: 'USD', limit_amount: '1000.00', committed: '1500.00',
        available: '-500.00' }),
    ],
  },
  approvals: { pending: 2 },
  requests: { total: 5, draft: 0, in_approval: 2, rework: 1, approved: 2, can_create: false },
  plan: { open: 4 },
  agreements: { total: 2, draft: 0, on_review: 1, rework: 0, active: 1 },
  invoices: { total: 6, draft: 1, returned: 0, tabs: { fd: 3, awaiting_docs: 0 } },
  accountable: { total: 1, awaiting_report: 1, can_create: false },
  bank: {},
  dashboard: {},
  alternatives: { feed: 2, submitted: 1 },
  kpi: { preliminary: 1, confirmed: 2, saving_confirmed: '350000.00' },
  admin: { no_executor: 0, routes: true, settings: true, refdata: true, projects: true },
};

const BUH: Overview = {
  shows_money: true,
  approvals: { pending: 0 },
  agreements: { total: 4, draft: 0, on_review: 0, rework: 0, active: 4 },
  invoices: { total: 9, draft: 0, returned: 0, tabs: { to_pay: 0, docs_provided: 2, bank_unconfirmed: 1 } },
  accountable: { total: 3, awaiting_report: 1, can_create: false, awaiting_accounting: 2 },
  bank: {},
  dashboard: {},
};

const ADM: Overview = {
  shows_money: false,
  budgets: { total: 3, approved: 2, draft: 1, can_create: false },
  approvals: { pending: 0 },
  requests: { total: 5, draft: 0, in_approval: 2, rework: 1, approved: 2, can_create: false },
  agreements: { total: 2, draft: 0, on_review: 1, rework: 0, active: 1 },
  admin: { no_executor: 2, routes: false, settings: true, refdata: true, projects: true },
};

const SN: Overview = {
  shows_money: true,
  budgets: {
    total: 12, approved: 12, draft: 0, can_create: false,
    projects: Array.from({ length: 12 }, (_, i) => budget(i + 1)),
  },
  approvals: { pending: 0 },
  requests: { total: 2, draft: 1, in_approval: 0, rework: 0, approved: 1, can_create: true },
  plan: { open: 1 },
  agreements: { total: 1, draft: 1, on_review: 0, rework: 0, active: 0 },
  invoices: { total: 1, draft: 0, returned: 0, tabs: { awaiting_docs: 1 } },
  accountable: { total: 0, awaiting_report: 0, can_create: true },
  alternatives: { feed: 3, mine_submitted: 1 },
  kpi: { preliminary: 0, confirmed: 1, saving_confirmed: '1000.00' },
};

function renderAs(overview: Overview) {
  get.mockResolvedValue({ data: overview });
  return renderWithProviders(<OverviewPage />, { route: '/bpp/overview' });
}

const block = (container: HTMLElement, key: string) =>
  container.querySelector<HTMLElement>(`[data-block="${key}"]`);
const stat = (container: HTMLElement, key: string) =>
  container.querySelector<HTMLElement>(`[data-stat="${key}"]`);
const blockKeys = (container: HTMLElement) =>
  Array.from(container.querySelectorAll<HTMLElement>('[data-block]')).map((el) => el.dataset.block);

beforeEach(() => {
  get.mockReset();
});

describe('«Обзор» — по ролям', () => {
  it('ФД: все блоки, бюджет каждого проекта отдельно, очередь «на решение ФД» — вкладка реестра', async () => {
    const { container } = renderAs(FD);
    await screen.findByText('Бюджет и закупки');
    expect(get).toHaveBeenCalledWith(OVERVIEW_ENDPOINT);

    expect(blockKeys(container)).toEqual([
      'budgets', 'requests', 'plan', 'agreements', 'invoices', 'accountable', 'bank', 'dashboard',
      'alternatives', 'kpi', 'admin',
    ]);
    // Общей суммы по проектам нет ни сверху, ни в карточке.
    expect(stat(container, 'available')).toBeNull();
    expect(stat(container, 'approvals')).toHaveAttribute('href', OVERVIEW_LINKS.approvals);
    expect(stat(container, 'approvals')).toHaveTextContent('2');
    expect(stat(container, 'fd')).toHaveAttribute('href', '/bpp/invoices?tab=fd');
    expect(stat(container, 'fd')).toHaveTextContent('3');

    const budgets = block(container, 'budgets')!;
    const rows = Array.from(budgets.querySelectorAll<HTMLElement>('[data-project]'));
    expect(rows.map((el) => el.dataset.project)).toEqual(['П-001', 'П-002']);
    expect(within(rows[0]).getByRole('link', { name: /Объект 1/ })).toHaveAttribute('href', '/bpp/budgets/b1');
    expect(within(rows[0]).getByText('12 500 000,00 KZT')).toBeInTheDocument();
    // Перерасход — красным, в валюте своего бюджета.
    expect(within(rows[1]).getByText('-500,00 USD')).toHaveClass('text-destructive');
    expect(within(budgets).getByRole('link', { name: 'Создать' }))
      .toHaveAttribute('href', OVERVIEW_LINKS.budgetNew);

    const invoices = block(container, 'invoices')!;
    // Очереди — ссылками на вкладку и с нулём; статус с нулём не показан.
    expect(within(invoices).getByRole('link', { name: /На решение ФД/ }))
      .toHaveAttribute('href', '/bpp/invoices?tab=fd');
    expect(within(invoices).getByRole('link', { name: /Ждут закрывающих/ }))
      .toHaveAttribute('href', '/bpp/invoices?tab=awaiting_docs');
    expect(within(invoices).queryByText('Возвращены на доработку')).not.toBeInTheDocument();
    expect(within(invoices).getByText('Черновики')).toBeInTheDocument();

    expect(within(block(container, 'kpi')!).getByText('350 000,00 KZT')).toBeInTheDocument();
    const admin = block(container, 'admin')!;
    expect(within(admin).getByRole('link', { name: 'Маршруты согласования' }))
      .toHaveAttribute('href', OVERVIEW_LINKS.routes);
  });

  it('БУХ: своих очередей — счета и подотчёт, без бюджетов, заявок и плана', async () => {
    const { container } = renderAs(BUH);
    await screen.findByText('Договоры и оплаты');

    expect(screen.queryByText('Бюджет и закупки')).not.toBeInTheDocument();
    expect(blockKeys(container)).toEqual(['agreements', 'invoices', 'accountable', 'bank', 'dashboard']);
    expect(stat(container, 'available')).toBeNull();
    expect(stat(container, 'to_pay')).toHaveAttribute('href', '/bpp/invoices?tab=to_pay');
    expect(stat(container, 'to_pay')).toHaveTextContent('0');

    const invoices = block(container, 'invoices')!;
    expect(within(invoices).getByRole('link', { name: /К оплате/ })).toHaveTextContent('0');
    expect(within(invoices).getByRole('link', { name: /Документы предоставлены/ }))
      .toHaveAttribute('href', '/bpp/invoices?tab=docs_provided');
    expect(within(invoices).getByRole('link', { name: /Оплачено, банк не подтвердил/ }))
      .toHaveAttribute('href', '/bpp/invoices?tab=bank_unconfirmed');
    expect(within(block(container, 'accountable')!).getByText('Ожидают выдачи бухгалтерией'))
      .toBeInTheDocument();
  });

  it('АДМ: количества без денег, «Нет исполнителя» и ссылки администрирования', async () => {
    const { container } = renderAs(ADM);
    await screen.findByText('Администрирование');

    expect(screen.queryByTestId('budget-projects')).not.toBeInTheDocument();
    expect(within(block(container, 'budgets')!).queryByRole('link', { name: 'Создать' }))
      .not.toBeInTheDocument();
    expect(stat(container, 'no_executor')).toHaveTextContent('2');

    const admin = block(container, 'admin')!;
    expect(within(admin).queryByRole('link', { name: 'Маршруты согласования' })).not.toBeInTheDocument();
    expect(within(admin).getByRole('link', { name: 'Справочники' }))
      .toHaveAttribute('href', OVERVIEW_LINKS.refdata);
    expect(within(admin).getByText(/временного исполнителя должности/)).toBeInTheDocument();
  });

  it('СН: «Создать» заявку, своя очередь закрывающих, нулевые статусы скрыты', async () => {
    const { container } = renderAs(SN);
    await screen.findByText('Альтернативы и KPI');

    expect(stat(container, 'awaiting_docs')).toHaveAttribute('href', '/bpp/invoices?tab=awaiting_docs');
    const requests = block(container, 'requests')!;
    expect(within(requests).getByRole('link', { name: 'Создать' }))
      .toHaveAttribute('href', OVERVIEW_LINKS.requestNew);
    expect(within(requests).getByText('Черновики')).toBeInTheDocument();
    expect(within(requests).queryByText('На согласовании')).not.toBeInTheDocument();
    expect(within(block(container, 'budgets')!).queryByRole('link', { name: 'Создать' }))
      .not.toBeInTheDocument();
    expect(within(block(container, 'alternatives')!).getByText('Мои поданные')).toBeInTheDocument();
    expect(block(container, 'admin')).toBeNull();
  });

  it('бюджеты: первые 10 проектов, «Показать все» раскрывает остальные', async () => {
    const { container } = renderAs(SN);
    await screen.findByText('Бюджет и закупки');
    const budgets = block(container, 'budgets')!;
    const rows = () => budgets.querySelectorAll('[data-project]');
    expect(rows()).toHaveLength(10);
    await userEvent.click(within(budgets).getByRole('button', { name: 'Показать все (12)' }));
    expect(rows()).toHaveLength(12);
    await userEvent.click(within(budgets).getByRole('button', { name: 'Свернуть' }));
    expect(rows()).toHaveLength(10);
  });

  it('ошибка загрузки — сообщение и «Повторить»', async () => {
    get.mockRejectedValueOnce(new Error('сеть')).mockResolvedValue({ data: SN });
    renderWithProviders(<OverviewPage />, { route: '/bpp/overview' });

    await userEvent.click(await screen.findByRole('button', { name: 'Повторить' }));
    expect(await screen.findByText('Бюджет и закупки')).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
  });
});

describe('ссылки «Обзора»', () => {
  it('ведут на маршруты подмодулей раздела', () => {
    const routes = new Set(bppModules.flatMap((m) => m.routes.map((r) => `/bpp/${r.path}`)));
    for (const href of Object.values(OVERVIEW_LINKS)) expect(routes).toContain(href);
  });
});
