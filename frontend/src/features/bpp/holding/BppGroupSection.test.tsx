/**
 * Раздел БЗО «Сводки группы»: суммы — строками сервера через formatMoney;
 * без узла `bpp.holding` запрос не уходит; 403/404 — раздела нет (не ошибка
 * страницы); 503 — «сейчас недоступна».
 */
import { screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';

import { BppGroupSection } from './BppGroupSection';

const summary = vi.fn();
vi.mock('./api', () => ({ bppHoldingApi: { summary: () => summary() } }));
const can = vi.fn();
vi.mock('@/hooks/usePermissions', () => ({
  usePermissions: () => ({ can: (node: string, flag: string) => can(node, flag) }),
}));

const OK = {
  companies: [{
    company_slug: 'hold', company_name: 'Холдинг', budgets: 2, budgets_other_currency: 1,
    limit_kzt: '1500000.00',
    invoices_to_pay: { count: 2, amount_kzt: '150.00' },
    invoices_paid: { count: 3, amount_kzt: '50.00' },
    agreements_active: 4,
  }],
  totals: {
    budgets: 2, limit_kzt: '1500000.00',
    invoices_to_pay: { count: 2, amount_kzt: '150.00' },
    invoices_paid: { count: 3, amount_kzt: '50.00' },
    agreements_active: 4,
  },
};

// Как у настоящих ответов: 4xx — с `response`, 5xx клиент сворачивает в isServerError.
const failure = (status: number) => (status >= 500
  ? Object.assign(new Error('x'), { status, isServerError: true })
  : { response: { status, data: {} } });

describe('BppGroupSection', () => {
  beforeEach(() => {
    summary.mockReset();
    can.mockReset();
    can.mockImplementation((node: string, flag: string) => node === 'bpp.holding' && flag === 'view');
  });

  it('без узла bpp.holding — ни запроса, ни раздела', () => {
    can.mockReturnValue(false);
    const { container } = renderWithProviders(<BppGroupSection />);
    expect(summary).not.toHaveBeenCalled();
    expect(container.querySelector('[data-testid="bpp-holding-section"]')).toBeNull();
  });

  it('показывает компании и итог', async () => {
    summary.mockResolvedValue({ data: OK });
    renderWithProviders(<BppGroupSection />);
    expect(await screen.findByTestId('bpp-holding-section')).toBeTruthy();
    expect(screen.getByText('Холдинг')).toBeTruthy();
    expect(screen.getAllByText(/1 500 000,00/).length).toBeGreaterThan(0);
  });

  it('403 — раздела нет', async () => {
    summary.mockRejectedValue(failure(403));
    const { container } = renderWithProviders(<BppGroupSection />);
    await vi.waitFor(() => expect(summary).toHaveBeenCalled());
    await vi.waitFor(() => expect(screen.queryByTestId('bpp-holding-skeleton')).toBeNull());
    expect(container.querySelector('[data-testid="bpp-holding-section"]')).toBeNull();
    expect(screen.queryByTestId('bpp-holding-error')).toBeNull();
  });

  it('404 — раздела нет', async () => {
    summary.mockRejectedValue(failure(404));
    const { container } = renderWithProviders(<BppGroupSection />);
    await vi.waitFor(() => expect(summary).toHaveBeenCalled());
    await vi.waitFor(() => expect(screen.queryByTestId('bpp-holding-skeleton')).toBeNull());
    expect(container.querySelector('[data-testid="bpp-holding-section"]')).toBeNull();
    expect(screen.queryByTestId('bpp-holding-error')).toBeNull();
  });

  it('503 — сводка сейчас недоступна', async () => {
    summary.mockRejectedValue(failure(503));
    renderWithProviders(<BppGroupSection />);
    expect(await screen.findByTestId('bpp-holding-unavailable')).toBeTruthy();
  });
});
