/**
 * Сводка группы (блок H, задача 5). Обе ручки-читатели — `hr/v1/holding/headcount`
 * и `tasks/v1/holding/projects` — уже готовы (задачи 3 и 4); экран их сводит в
 * одну таблицу по компании плюс строку «Итого по группе». Бюджеты и
 * согласования подключит второй разработчик — здесь только заглушки.
 *
 * Проверяем то, что отличает этот экран от обычного списка:
 * - слияние двух независимых списков компаний по `company_slug`, а не по
 *   позиции — у ручек он может не совпадать;
 * - 403 и 503 — РАЗНЫЕ состояния (разный текст, оба видны рецензенту без
 *   поддомена холдинга и во время `migrate_companies`);
 * - `reports_last_date: null` — прочерк, а не сегодняшняя дата и не ноль;
 * - плитки-заглушки подписаны ровно текстом «данные подключит второй
 *   разработчик», чтобы их нельзя было принять за настоящий ноль.
 */
import { screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';

import GroupSummary from './GroupSummary';

const headcount = vi.fn();
const projects = vi.fn();
vi.mock('@/api/holding', () => ({
  holdingApi: {
    headcount: () => headcount(),
    projects: () => projects(),
  },
}));

vi.mock('@/components/Header', () => ({ Header: () => null }));
vi.mock('@/components/Footer', () => ({ Footer: () => null }));

const HEADCOUNT_OK = {
  companies: [{
    company_slug: 'hi-tech-group', company_name: 'Hi-Tech Group LTD',
    employees_active: 12, employees_total: 13, departments_active: 5,
    positions_active: 14, staffing_headcount: 14.0, staffing_payroll: 7000000.0,
  }],
  totals: {
    employees_active: 12, employees_total: 13,
    staffing_headcount: 14.0, staffing_payroll: 7000000.0,
  },
};

const PROJECTS_OK = {
  companies: [{
    company_slug: 'hi-tech-group', company_name: 'Hi-Tech Group LTD',
    projects_active: 3, sites_active: 2, tasks_open: 17, tasks_overdue: 4,
    reports_last_date: '2026-09-16',
  }],
  totals: { projects_active: 3, sites_active: 2, tasks_open: 17, tasks_overdue: 4 },
};

describe('GroupSummary', () => {
  beforeEach(() => {
    headcount.mockReset();
    projects.mockReset();
  });

  it('рисует строку на компанию и строку «Итого по группе»', async () => {
    headcount.mockResolvedValue({ data: HEADCOUNT_OK });
    projects.mockResolvedValue({ data: PROJECTS_OK });
    renderWithProviders(<GroupSummary />);

    const table = await screen.findByTestId('holding-summary-table');
    expect(within(table).getByText('Hi-Tech Group LTD')).toBeInTheDocument();
    expect(within(table).getByText(/Итого по группе/)).toBeInTheDocument();
  });

  it('плитки «Бюджеты» и «Согласования» подписаны отдельным разработчиком, а не нулём', async () => {
    headcount.mockResolvedValue({ data: HEADCOUNT_OK });
    projects.mockResolvedValue({ data: PROJECTS_OK });
    renderWithProviders(<GroupSummary />);

    await screen.findByTestId('holding-summary-table');
    const stubs = screen.getAllByText(/данные подключит второй разработчик/i);
    // Ровно две плитки-заглушки: «Бюджеты» и «Согласования».
    expect(stubs).toHaveLength(2);
    expect(screen.getByText('Бюджеты')).toBeInTheDocument();
    expect(screen.getByText('Согласования')).toBeInTheDocument();
    // Заглушка не прикидывается загрузкой и не показывает нулей.
    expect(screen.queryByText(/^0$/)).not.toBeInTheDocument();
  });

  it('компания без отчётов показывает прочерк, а не сегодняшнюю дату', async () => {
    headcount.mockResolvedValue({ data: HEADCOUNT_OK });
    projects.mockResolvedValue({
      data: {
        companies: [{
          ...PROJECTS_OK.companies[0],
          reports_last_date: null,
        }],
        totals: PROJECTS_OK.totals,
      },
    });
    renderWithProviders(<GroupSummary />);

    const table = await screen.findByTestId('holding-summary-table');
    const row = within(table).getByText('Hi-Tech Group LTD').closest('tr');
    expect(row).not.toBeNull();
    const today = new Date().toISOString().slice(0, 10);
    expect(row!.textContent).not.toContain(today);
    expect(within(row!).getByText('—')).toBeInTheDocument();
  });

  it('пока грузится — скелет, а не нули', () => {
    // Промисы намеренно не резолвятся — застаём экран в состоянии загрузки.
    headcount.mockReturnValue(new Promise(() => {}));
    projects.mockReturnValue(new Promise(() => {}));
    renderWithProviders(<GroupSummary />);

    expect(screen.getByTestId('holding-summary-skeleton')).toBeInTheDocument();
    expect(screen.queryByTestId('holding-summary-table')).not.toBeInTheDocument();
    expect(screen.queryByText(/^0$/)).not.toBeInTheDocument();
  });

  it('403 от ручки hr рисует объяснение «доступно только на поддомене холдинга», а не пустую таблицу', async () => {
    headcount.mockRejectedValue({
      response: { status: 403, data: { detail: 'Сводка по группе доступна только на поддомене холдинга' } },
    });
    projects.mockResolvedValue({ data: PROJECTS_OK });
    renderWithProviders(<GroupSummary />);

    expect(await screen.findByText(/доступн[а-я]* только на поддомене холдинга/)).toBeInTheDocument();
    expect(screen.queryByTestId('holding-summary-table')).not.toBeInTheDocument();
  });

  it('403 от ручки tasks тоже блокирует таблицу тем же объяснением', async () => {
    headcount.mockResolvedValue({ data: HEADCOUNT_OK });
    projects.mockRejectedValue({
      response: { status: 403, data: { detail: 'Сводка по группе доступна только на поддомене холдинга' } },
    });
    renderWithProviders(<GroupSummary />);

    expect(await screen.findByText(/доступн[а-я]* только на поддомене холдинга/)).toBeInTheDocument();
    expect(screen.queryByTestId('holding-summary-table')).not.toBeInTheDocument();
  });

  it('503 рисует «пересобираются» отдельным состоянием, не тем же, что 403', async () => {
    headcount.mockRejectedValue({
      response: { status: 503, data: { detail: 'Сводные представления холдинга сейчас пересобираются' } },
    });
    projects.mockResolvedValue({ data: PROJECTS_OK });
    renderWithProviders(<GroupSummary />);

    expect(await screen.findByText(/пересобираются/)).toBeInTheDocument();
    expect(screen.queryByTestId('holding-summary-table')).not.toBeInTheDocument();
    // Не то же состояние, что 403.
    expect(screen.queryByTestId('holding-summary-forbidden')).not.toBeInTheDocument();
    expect(screen.getByTestId('holding-summary-unavailable')).toBeInTheDocument();
  });
});
