/**
 * Вкладка «Сравнение» (TND-020, TND-021): поставщики колонками, пометки
 * «аналог», «N из M ед.», «срок истёк», «нет курса», подсветка самого
 * дешёвого, отказавшиеся, экспорт и файл КП по ссылке с журналом.
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { createTestQueryClient } from '@/test/renderWithProviders';

import type { Comparison } from './comparison';
import { ComparisonTab } from './ComparisonTab';
import { TENDER_ID, comparisonData, supplier } from './testData';

const get = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get, post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() } }));
const toast = vi.hoisted(() => ({ error: vi.fn(), success: vi.fn(), info: vi.fn() }));
vi.mock('sonner', () => ({ toast }));

function serve(data: Comparison) {
  get.mockImplementation((url: string) => {
    if (url.endsWith(`tenders/${TENDER_ID}/comparison`)) return Promise.resolve({ data });
    if (url.endsWith(`tenders/${TENDER_ID}/comparison/export`)) {
      return Promise.resolve({
        data: new Blob(['x']),
        headers: { 'content-disposition': "attachment; filename*=utf-8''%D0%A2%D0%9D.xlsx" },
      });
    }
    if (url.includes('/offers/of-a/files/doc-1')) return Promise.resolve({ data: { url: 'https://s3/kp.pdf' } });
    return Promise.reject(new Error(`unexpected ${url}`));
  });
}

function renderTab() {
  return render(
    <QueryClientProvider client={createTestQueryClient()}>
      <ComparisonTab tenderId={TENDER_ID} tenderNumber="ТН-2026-000003" />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  get.mockReset();
  toast.error.mockReset();
});

describe('ComparisonTab', () => {
  it('поставщики — колонками, пометки аналога и частичного количества', async () => {
    serve(comparisonData());
    renderTab();
    const items = await screen.findByTestId('comparison-items');
    expect(within(items).getByRole('columnheader', { name: 'ТОО «Альфа»' })).toBeInTheDocument();
    expect(within(items).getByRole('columnheader', { name: 'ТОО «Бета»' })).toBeInTheDocument();
    expect(within(items).getByText('аналог')).toHaveAttribute('title', 'Аналог ГОСТ');
    expect(within(items).getByText('6 из 10 ед.')).toBeInTheDocument();
    expect(within(items).getByText('не предложено')).toBeInTheDocument();
    expect(within(items).getByText('в цене')).toBeInTheDocument();
    expect(within(items).getByText('не все предложили')).toBeInTheDocument();
  });

  it('самый дешёвый по позиции подсвечен', async () => {
    serve(comparisonData());
    renderTab();
    const row = (await screen.findByRole('rowheader', { name: /Арматура А500/ })).closest('tr') as HTMLElement;
    const cells = within(row).getAllByRole('cell');
    const cheapest = cells.filter((cell) => cell.getAttribute('data-cheapest') === 'true');
    expect(cheapest).toHaveLength(1);
    expect(cheapest[0]).toHaveTextContent('90,00 KZT');
  });

  it('сводка: покрытие, экономия и удорожание, отказавшиеся с причиной', async () => {
    serve(comparisonData());
    renderTab();
    const summary = await screen.findByTestId('comparison-summary');
    expect(within(summary).getByText('1 из 2')).toBeInTheDocument();
    expect(within(summary).getByText('300,00')).toBeInTheDocument();
    expect(within(summary).getByText('Дороже на 100,00')).toBeInTheDocument();
    expect(screen.getByText('ТОО «Гамма» — Нет на складе')).toBeInTheDocument();
  });

  it('нет курса и истёкший срок — предупреждения с именем поставщика', async () => {
    serve(comparisonData({
      suppliers: [
        supplier({ valid_until: '2026-10-01', valid_expired: true }),
        supplier({ invitation_id: 'inv-b', name: 'ТОО «Бета»', currency_code: 'CNY', rate: null,
          total_common_kzt: null, total_full_kzt: null, saving_common_kzt: null }),
      ],
      warnings: [
        { code: 'no_rate', invitation_id: 'inv-b', currency_code: 'CNY' },
        { code: 'valid_expired', invitation_id: 'inv-a', valid_until: '2026-10-01' },
      ],
    }));
    renderTab();
    const warnings = await screen.findByTestId('comparison-warnings');
    expect(within(warnings).getByText(/ТОО «Бета»: нет курса CNY/)).toBeInTheDocument();
    expect(within(warnings).getByText(/ТОО «Альфа»: срок действия предложения истёк 01\.10\.2026/)).toBeInTheDocument();
    expect(within(screen.getByTestId('comparison-summary')).getByText(/срок истёк/)).toBeInTheDocument();
    expect(within(screen.getByTestId('comparison-summary')).getByText(/CNY · нет курса/)).toBeInTheDocument();
  });

  it('экспорт скачивает xlsx с именем из ответа', async () => {
    serve(comparisonData());
    const createObjectURL = vi.fn(() => 'blob:x');
    Object.assign(URL, { createObjectURL, revokeObjectURL: vi.fn() });
    renderTab();
    await userEvent.click(await screen.findByRole('button', { name: /Экспорт в xlsx/ }));
    await waitFor(() => expect(createObjectURL).toHaveBeenCalled());
    expect(get).toHaveBeenCalledWith(expect.stringContaining('/comparison/export'), { responseType: 'blob' });
  });

  it('файл КП открывается по ссылке сервера', async () => {
    serve(comparisonData({ suppliers: [supplier({ files: [{ id: 'doc-1', name: 'КП.pdf', size: 10 }] })] }));
    const tab = { location: { href: '' }, close: vi.fn() };
    vi.spyOn(window, 'open').mockReturnValue(tab as unknown as Window);
    renderTab();
    await userEvent.click(await screen.findByRole('button', { name: 'КП.pdf' }));
    await waitFor(() => expect(tab.location.href).toBe('https://s3/kp.pdf'));
  });
});
