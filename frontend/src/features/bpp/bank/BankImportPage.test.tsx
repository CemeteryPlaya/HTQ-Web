/**
 * Экран загрузки выписки: опрос раз в 2 с, пока «Обрабатывается», и
 * остановка на «Загружена»; итог и ошибки строк на экране; строки — после
 * разбора; «Ошибка загрузки» показывает причину; тысячи ошибок строк — первые
 * 200 и «Показать ещё N».
 */
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { Permissions } from '@/hooks/usePermissions';
import { createTestQueryClient, renderWithProviders } from '@/test/renderWithProviders';

import { registryOpenState } from '../core/registryBack';

import { IMPORT_POLL_MS, type BankImportCard } from './api';
import { BankImportPage } from './BankImportPage';

const get = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get } }));

vi.mock('@/hooks/usePermissions', () => ({
  usePermissions: () => ({ atLeast: () => true, can: () => false }) as unknown as Permissions,
}));

const card = (over: Partial<BankImportCard> = {}): BankImportCard => ({
  id: 'imp-1', number: 'ВП-2026-0001',
  account: { id: 'acc-1', iban: 'KZ86125KZT5004100100', bank_name: 'Халык Банк', currency: 'KZT' },
  bank_name: 'Халык Банк', format: 'onec', period_from: '2026-09-01', period_to: '2026-09-15',
  status: 'processing', status_label: 'Обрабатывается', filename: 'kl_to_1c.txt', comment: '',
  rows_total: 3, debits: 2, rows_done: 0, duplicates: 0, errors_count: 0, lines: 0,
  matched: 0, unmatched: 0, author_id: 901, author_name: 'Тест Фд',
  created_at: '2026-09-28T05:00:00Z', finished_at: null,
  errors: [], failure: '', progress: 0, file: null, ...over,
});

const LINE = {
  id: 'line-1', row_no: 1, doc_date: '2026-09-03', doc_number: '117', amount: '1250000.00',
  currency: 'KZT', recipient_name: 'ТОО «Альфа»', recipient_bin: '100000000001',
  recipient_iban: 'KZ000000000000000001', purpose: 'Оплата по счёту СЧ-2026-000001',
  match_status: 'unmatched', match_status_label: 'Не сопоставлена', cancelled_at: null,
};

const cardCalls = () => get.mock.calls.filter(([url]) => url === 'bpp/v1/bank/imports/imp-1');

function serve(sequence: BankImportCard[]) {
  let index = 0;
  get.mockImplementation((url: string) => {
    if (url.endsWith('/lines')) {
      return Promise.resolve({ data: { items: [LINE], total: 1, page: 1, page_size: 50 } });
    }
    const next = sequence[Math.min(index, sequence.length - 1)];
    index += 1;
    return Promise.resolve({ data: next });
  });
}

function renderPage() {
  return renderWithProviders(
    <Routes>
      <Route path="/bpp/bank/:id" element={<BankImportPage />} />
    </Routes>,
    { route: '/bpp/bank/imp-1' },
  );
}

/** Экран, открытый переходом с состоянием (строка реестра, форма загрузки). */
function renderWithState(state: unknown) {
  return render(
    <QueryClientProvider client={createTestQueryClient()}>
      <MemoryRouter initialEntries={[{ pathname: '/bpp/bank/imp-1', state }]}>
        <Routes>
          <Route path="/bpp/bank/:id" element={<BankImportPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  get.mockReset();
  vi.useFakeTimers({ shouldAdvanceTime: true });
});

afterEach(() => {
  vi.useRealTimers();
});

describe('BankImportPage', () => {
  it('опрашивает, пока идёт разбор, и останавливается на «Загружена»', async () => {
    serve([
      card(),
      card({ rows_done: 1, progress: 50 }),
      card({
        status: 'loaded', status_label: 'Загружена', rows_done: 2, progress: 100, lines: 1,
        duplicates: 1, errors_count: 1,
        errors: ['Строка 3: не распознана дата „31.02.2026“'],
      }),
    ]);
    renderPage();

    expect(await screen.findByText('Обрабатывается')).toBeInTheDocument();
    expect(screen.getByRole('progressbar', { name: 'Ход разбора' })).toBeInTheDocument();
    expect(cardCalls()).toHaveLength(1);

    await act(() => vi.advanceTimersByTimeAsync(IMPORT_POLL_MS));
    await act(() => vi.advanceTimersByTimeAsync(IMPORT_POLL_MS));
    expect(await screen.findByText('Загружена')).toBeInTheDocument();
    expect(cardCalls()).toHaveLength(3);

    // Дальше опроса нет.
    await act(() => vi.advanceTimersByTimeAsync(IMPORT_POLL_MS * 3));
    expect(cardCalls()).toHaveLength(3);

    // Итог, ошибки строк и сами строки.
    const totals = screen.getByLabelText('Итог загрузки');
    expect(within(totals).getByText('Пропущено дублей').nextSibling).toHaveTextContent('1');
    expect(within(totals).getByText('Ошибок').nextSibling).toHaveTextContent('1');
    const errors = screen.getByRole('list', { name: 'Строки, которые не удалось разобрать' });
    expect(within(errors).getByText('Строка 3: не распознана дата „31.02.2026“')).toBeInTheDocument();
    expect(await screen.findByText('ТОО «Альфа»')).toBeInTheDocument();
    expect(screen.getByText('1 250 000,00 KZT')).toBeInTheDocument();
    expect(screen.getByText('Не сопоставлена')).toBeInTheDocument();
  });

  it('«Ошибка загрузки» — причина на экране, опроса и строк нет', async () => {
    serve([card({
      status: 'failed', status_label: 'Ошибка загрузки', progress: 100,
      failure: 'В файле больше 10 000 строк.',
    })]);
    renderPage();

    expect(await screen.findByText('В файле больше 10 000 строк.')).toBeInTheDocument();
    await act(() => vi.advanceTimersByTimeAsync(IMPORT_POLL_MS * 2));
    expect(cardCalls()).toHaveLength(1);
    expect(get.mock.calls.some(([url]) => String(url).endsWith('/lines'))).toBe(false);
  });

  it('«К списку» ведёт в реестр загрузок', async () => {
    serve([card({ status: 'loaded', status_label: 'Загружена' })]);
    renderPage();
    expect(await screen.findByRole('link', { name: 'К списку' })).toHaveAttribute('href', '/bpp/bank');
  });

  it('«К списку» возвращает на то место реестра, откуда открыли загрузку', async () => {
    serve([card({ status: 'loaded', status_label: 'Загружена' })]);
    renderWithState(registryOpenState('?page=3'));
    expect(await screen.findByRole('link', { name: 'К списку' }))
      .toHaveAttribute('href', '/bpp/bank?page=3');
  });

  it('предупреждения формы загрузки о пересечении периода — на экране', async () => {
    const warning = 'Период пересекается с загрузкой ВП-2026-0001 (01.09.2026–15.09.2026) этого счёта.';
    serve([card()]);
    renderWithState({ warnings: [warning] });
    expect(await screen.findByText(warning)).toBeInTheDocument();
  });

  it('упавший очередной опрос не прячет карточку, опрос продолжается', async () => {
    let calls = 0;
    get.mockImplementation(() => {
      calls += 1;
      return calls === 2
        ? Promise.reject({ response: { status: 502, data: {} } })
        : Promise.resolve({ data: card() });
    });
    renderPage();
    expect(await screen.findByText('Обрабатывается')).toBeInTheDocument();

    await act(() => vi.advanceTimersByTimeAsync(IMPORT_POLL_MS));
    expect(cardCalls()).toHaveLength(2);
    expect(screen.getByText('Обрабатывается')).toBeInTheDocument();
    expect(screen.queryByText('Не удалось загрузить выписку. Обновите страницу.')).toBeNull();

    await act(() => vi.advanceTimersByTimeAsync(IMPORT_POLL_MS));
    expect(cardCalls()).toHaveLength(3);
  });

  it('«Отменена» — без опроса и без строк', async () => {
    serve([card({ status: 'cancelled', status_label: 'Отменена', progress: 100 })]);
    renderPage();
    expect(await screen.findByText(/Загрузка отменена/)).toBeInTheDocument();
    await act(() => vi.advanceTimersByTimeAsync(IMPORT_POLL_MS * 2));
    expect(cardCalls()).toHaveLength(1);
    expect(get.mock.calls.some(([url]) => String(url).endsWith('/lines'))).toBe(false);
  });
  it('ошибок строк больше 200 — видны первые 200, остальные по кнопке; повторы текста не теряются', async () => {
    const errors = Array.from({ length: 250 }, (_, i) => `Строка ${i + 2}: не распознана дата`);
    errors.push('Строка 2: не распознана дата'); // тот же текст ещё раз
    serve([card({ status: 'failed', status_label: 'Ошибка загрузки', progress: 100, errors })]);
    renderPage();

    const list = await screen.findByRole('list', { name: 'Строки, которые не удалось разобрать' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(200);
    fireEvent.click(screen.getByRole('button', { name: 'Показать ещё 51' }));

    expect(within(list).getAllByRole('listitem')).toHaveLength(251);
    expect(within(list).getAllByText('Строка 2: не распознана дата')).toHaveLength(2);
    expect(screen.queryByRole('button', { name: /Показать ещё/ })).toBeNull();
  });
});
