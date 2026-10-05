/**
 * Отчёт R-01: фильтр перечитывает отчёт; доля `null` — «—»; суммы через
 * `formatMoney`; клик по «Подтверждено» открывает записи с `status=confirmed`
 * и `buyer_id`.
 */
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';

import type { KpiReport, KpiReportRow } from './api';
import { KpiReportPage } from './KpiReportPage';

const get = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get, post: vi.fn() } }));
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() } }));

const row = (over: Partial<KpiReportRow>): KpiReportRow => ({
  buyer_id: 7, name: 'Снабженцев Иван', role: 'sn', role_label: 'Снабженец',
  submitted: 4, selected: 3, confirmed: 2, share_pct: '50.00',
  saving: '1250000.50', overspend: '800.00', own_document_count: 1, ...over,
});

const REPORT: KpiReport = {
  rows: [row({}), row({
    buyer_id: 8, name: 'Новичков Пётр', submitted: 0, selected: 0, confirmed: 0,
    share_pct: null, saving: '0.00', overspend: '0.00', own_document_count: 0,
  })],
  total: row({ buyer_id: null, name: null, role: '', role_label: '', submitted: 4, saving: '1250000.50' }),
  filters: {},
};

type Params = Record<string, string>;
const callsTo = (suffix: string) => get.mock.calls
  .filter(([url]) => String(url).endsWith(suffix))
  .map(([, config]) => ((config as { params?: Params } | undefined)?.params ?? {}));

beforeEach(() => {
  get.mockReset();
  get.mockImplementation((url: string) => {
    if (String(url).endsWith('kpi/report')) return Promise.resolve({ data: REPORT });
    if (String(url).endsWith('kpi/records')) return Promise.resolve({ data: { items: [], total: 0 } });
    if (String(url).includes('projects')) {
      return Promise.resolve({ data: [{ id: 'p1', code: 'П-015', name: 'Объект' }] });
    }
    if (String(url).includes('articles')) {
      return Promise.resolve({ data: [{ id: 'a1', code: 'T-METAL', name: 'Металлопрокат' }] });
    }
    return Promise.resolve({ data: [] });
  });
});

const renderPage = (route = '/bpp/kpi') => renderWithProviders(
  <Routes><Route path="/bpp/kpi" element={<KpiReportPage />} /></Routes>, { route });

describe('KpiReportPage', () => {
  it('показывает доли и суммы; доля null — «—»', { timeout: 20000 }, async () => {
    renderPage();
    const first = await screen.findByText('Снабженцев Иван', { selector: 'td' });
    const rowEl = first.closest('tr') as HTMLElement;
    expect(within(rowEl).getByText('50,00 %')).toBeInTheDocument();
    expect(within(rowEl).getByText('1 250 000,50 KZT')).toBeInTheDocument();
    const second = screen.getByText('Новичков Пётр', { selector: 'td' }).closest('tr') as HTMLElement;
    expect(within(second).getByText('—')).toBeInTheDocument();
    expect(screen.getByText('Итого', { selector: 'td' })).toBeInTheDocument();
  });

  it('смена проекта перечитывает отчёт с project_id', { timeout: 20000 }, async () => {
    renderPage();
    await screen.findByText('Снабженцев Иван', { selector: 'td' });
    await userEvent.click(screen.getByRole('combobox', { name: 'Проект' }));
    await userEvent.click(await screen.findByRole('option', { name: 'П-015 — Объект' }));
    await vi.waitFor(() => {
      expect(callsTo('kpi/report').some((p) => p.project_id === 'p1')).toBe(true);
    });
  });

  it('клик по «Подтверждено» открывает записи со status и buyer_id', { timeout: 20000 }, async () => {
    renderPage();
    await screen.findByText('Снабженцев Иван', { selector: 'td' });
    await userEvent.click(screen.getByRole('button', { name: 'Снабженцев Иван: Подтверждено' }));
    await vi.waitFor(() => {
      expect(callsTo('kpi/records').some((p) => p.status === 'confirmed' && p.buyer_id === '7')).toBe(true);
    });
    expect(await screen.findByText('Записей нет')).toBeInTheDocument();
  });

  it('без фильтра по покупателю отчёт и список покупателей — один запрос', { timeout: 20000 }, async () => {
    renderPage();
    await screen.findByText('Снабженцев Иван', { selector: 'td' });
    expect(callsTo('kpi/report')).toHaveLength(1);
  });

  it('«Удорожание» кликается — подтверждённые записи покупателя', { timeout: 20000 }, async () => {
    renderPage();
    await screen.findByText('Снабженцев Иван', { selector: 'td' });
    await userEvent.click(screen.getByRole('button', { name: 'Снабженцев Иван: Удорожание' }));
    await vi.waitFor(() => {
      expect(callsTo('kpi/records').some((p) => p.status === 'confirmed' && p.buyer_id === '7')).toBe(true);
    });
    expect(await screen.findByText('Снабженцев Иван — Удорожание: подтверждённые записи')).toBeInTheDocument();
  });

  it('записей больше, чем отдано, — «Показаны первые N из M»', { timeout: 20000 }, async () => {
    const base = get.getMockImplementation() as (url: string) => Promise<unknown>;
    get.mockImplementation((url: string) => (String(url).endsWith('kpi/records')
      ? Promise.resolve({ data: { total: 350, items: [{
        id: 'k1', offer_number: 'АП-2026-0001', buyer_name: 'Снабженцев Иван', source_number: 'СЧ-1',
        result_amount_kzt: '900000.00', saving_amount: '100000.00', status: 'confirmed',
      }] } })
      : base(url)));
    renderPage();
    await screen.findByText('Снабженцев Иван', { selector: 'td' });
    await userEvent.click(screen.getByRole('button', { name: 'Снабженцев Иван: Выбрано' }));
    expect(await screen.findByText('Показаны первые 1 из 350 — сузьте фильтры')).toBeInTheDocument();
    expect(screen.getByText('Новый документ, KZT')).toBeInTheDocument();
  });

  it('«по» раньше «с» — запроса нет, ошибка под полями', { timeout: 20000 }, async () => {
    renderPage('/bpp/kpi?period_from=2026-09-20&period_to=2026-09-01');
    expect(await screen.findByText('Дата «по» раньше даты «с»')).toBeInTheDocument();
    expect(callsTo('kpi/report')).toHaveLength(0);
  });
});
