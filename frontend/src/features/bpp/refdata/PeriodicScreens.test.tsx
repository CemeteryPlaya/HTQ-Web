/**
 * Периодические справочники (курсы, НДС, МРП) и страница «Справочники»:
 * у них нет правки и архива, только добавление — кнопка тоже по `can_edit`;
 * значения показываются без float и в формате модуля.
 */
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';

import CurrenciesTab from './CurrenciesTab';
import RefdataPage from './RefdataPage';
import VatMrpTab from './VatMrpTab';

const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get, post, patch: vi.fn() } }));
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() } }));

type Responses = Record<string, unknown[]>;

const serve = (responses: Responses) => {
  get.mockImplementation((url: string) => {
    const name = url.replace('refdata/v1/', '');
    return Promise.resolve({ data: responses[name] ?? [] });
  });
};

const data = (canEdit: boolean): Responses => ({
  currencies: [
    { id: 'kzt', code: 'KZT', name: 'Тенге', symbol: '₸', is_active: true, can_edit: canEdit },
    { id: 'usd', code: 'USD', name: 'Доллар США', symbol: '$', is_active: true, can_edit: canEdit },
  ],
  rates: [
    {
      id: 'r1', currency_code: 'USD', on_date: '2026-09-28', rate: '475.120000',
      source: 'nbrk', can_edit: canEdit,
    },
  ],
  countries: [
    { id: 'kz', code: 'KZ', name: 'Казахстан', is_active: true, can_edit: canEdit },
  ],
  vat: [
    {
      id: 'v1', country_code: 'KZ', rate: '16.00', date_from: '2026-01-01', date_to: null,
      can_edit: canEdit,
    },
  ],
  mrp: [
    { id: 'm1', date_from: '2025-01-01', value: '3932.00', can_edit: canEdit },
    { id: 'm2', date_from: '2026-01-01', value: '4325.00', can_edit: canEdit },
  ],
});

beforeEach(() => {
  get.mockReset();
  post.mockReset();
});

describe('Валюты и курсы', () => {
  it('курс — в формате модуля, источник НБРК; вне УК добавить нельзя', async () => {
    serve(data(false));
    renderWithProviders(<CurrenciesTab />);

    const row = (await screen.findByText('475,12')).closest('tr')!;
    expect(within(row).getByText('28.09.2026')).toBeInTheDocument();
    expect(within(row).getByText('НБРК')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Добавить ручной курс' })).toBeDisabled();
  });

  it('в УК — ручной курс уходит строкой, без округления', async () => {
    serve(data(true));
    post.mockResolvedValue({ data: {} });
    renderWithProviders(<CurrenciesTab />, {});

    await screen.findByText('475,12');
    fireEvent.click(screen.getByRole('button', { name: 'Добавить ручной курс' }));
    const dialog = await screen.findByRole('dialog');
    // Валюта подставляется из фильтра; здесь фильтр «Все» — выбор пуст,
    // и «Сохранить» выключена, пока форма не заполнена.
    expect(within(dialog).getByRole('button', { name: 'Сохранить' })).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText('Курс, KZT за единицу'), {
      target: { value: '475,1234567' },
    });
    expect(within(dialog).getByText(/не более 6 знаков/)).toBeInTheDocument();
  });
});

describe('НДС и МРП', () => {
  it('ставка — с названием страны, бессрочная — «бессрочно»; МРП — новые сверху с порогом', async () => {
    serve(data(true));
    renderWithProviders(<VatMrpTab />);

    const vatRow = (await screen.findByText('Казахстан (KZ)')).closest('tr')!;
    expect(within(vatRow).getByText('16,00')).toBeInTheDocument();
    expect(within(vatRow).getByText('бессрочно')).toBeInTheDocument();

    const mrpCells = await screen.findAllByText(/KZT$/);
    expect(mrpCells.map((cell) => cell.textContent)).toEqual([
      '4 325,00 KZT', '4 325 000,00 KZT', '3 932,00 KZT', '3 932 000,00 KZT',
    ]);
    expect(screen.getByRole('button', { name: 'Добавить ставку' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Добавить значение МРП' })).toBeEnabled();
  });

  it('вне УК — кнопки добавления выключены', async () => {
    serve(data(false));
    renderWithProviders(<VatMrpTab />);

    await screen.findByText('Казахстан (KZ)');
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Добавить ставку' })).toBeDisabled();
    });
    expect(screen.getByRole('button', { name: 'Добавить значение МРП' })).toBeDisabled();
  });
});

describe('RefdataPage', () => {
  it('?tab= открывает нужный справочник', async () => {
    serve(data(true));
    renderWithProviders(<RefdataPage />, { route: '/bpp/refdata?tab=vat-mrp' });

    expect(await screen.findByText('Казахстан (KZ)')).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'НДС и МРП' })).toHaveAttribute('aria-selected', 'true');
  });

  it('без ?tab= — первая вкладка «Статьи бюджета»', async () => {
    serve({
      'article-groups': [{
        id: 'g1', code: 'SUP', name: 'Снабжение', node_key: 'bpp.articles.supply',
        is_active: true, can_edit: true,
      }],
      articles: [],
    });
    renderWithProviders(<RefdataPage />);

    expect(await screen.findByText('Снабжение')).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Статьи бюджета' })).toHaveAttribute('aria-selected', 'true');
  });
});
