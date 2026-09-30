/**
 * Результат сверки на экране загрузки (A4.2, часть 4): вкладки со
 * счётчиками, подсветка номера в назначении, ручное сопоставление (Σ больше
 * строки не уходит), комментарий не короче 10 символов, кнопки только с
 * правом `bpp.bank` edit, перечитывание после действия, число счетов в
 * диалоге отмены загрузки.
 */
import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { Permissions } from '@/hooks/usePermissions';
import { renderWithProviders } from '@/test/renderWithProviders';

import { splitPurpose } from './amounts';
import { AUTOMATCH_WINDOW_MS, IMPORT_POLL_MS, type BankImportCard, type LineMatch, type StatementLine } from './api';
import { BankImportPage } from './BankImportPage';

const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get, post } }));

const toastError = vi.hoisted(() => vi.fn());
vi.mock('sonner', () => ({ toast: { error: toastError, success: vi.fn(), info: vi.fn() } }));

const canEdit = vi.hoisted(() => ({ value: true }));
vi.mock('@/hooks/usePermissions', () => ({
  usePermissions: () => ({
    atLeast: () => true,
    can: (node: string, level: string) => node === 'bpp.bank' && (level !== 'edit' || canEdit.value),
  }) as unknown as Permissions,
}));

const group = (count: number, amount: string) => ({ count, amount });

const CARD: BankImportCard = {
  id: 'imp-1', number: 'ВП-2026-0001',
  account: { id: 'acc-1', iban: 'KZ86125KZT5004100100', bank_name: 'Халык Банк', currency: 'KZT' },
  bank_name: 'Халык Банк', format: 'onec', period_from: '2026-09-01', period_to: '2026-09-15',
  status: 'reconciled', status_label: 'Сверена', filename: 'kl_to_1c.txt', comment: '',
  rows_total: 6, debits: 5, rows_done: 5, duplicates: 1, errors_count: 0, lines: 5,
  matched: 2, needs_review: 1, unmatched: 1, excluded: 1,
  author_id: 901, author_name: 'Тест Фд', created_at: '2026-09-28T05:00:00Z', finished_at: null,
  errors: [], failure: '', progress: 100, file: null,
  totals: {
    matched: group(2, '2500000.00'), needs_review: group(1, '900000.00'),
    unmatched: group(1, '1250000.00'), excluded: group(1, '50000.00'), unallocated: '0.00',
  },
};

const MATCH: LineMatch = {
  id: 'm-1', invoice_id: 'inv-1', invoice_number: 'СЧ-2026-000001', invoice_url: '/bpp/invoices/inv-1',
  invoice_status: 'to_pay', invoice_status_label: 'К оплате', invoice_amount: '1500000.00',
  invoice_currency: 'KZT', paid_bank_amount: '1000000.00', recon_status: 'underpaid',
  recon_status_label: 'Недоплата', amount: '900000.00', state: 'review', manual: false,
  comment: '', review_reason: 'sum_mismatch', review_reason_label: 'Сумма не делится',
};

const LINE: StatementLine = {
  id: 'line-1', row_no: 1, doc_date: '2026-09-03', doc_number: '117', amount: '1250000.00',
  currency: 'KZT', recipient_name: 'ТОО «Альфа»', recipient_bin: '100000000001',
  recipient_iban: 'KZ000000000000000001', purpose: 'Оплата по счёту СЧ-2026-000001 за материалы',
  match_status: 'unmatched', match_status_label: 'Не сопоставлена', cancelled_at: null,
  found_numbers: [], matches: [],
};

const CANDIDATE = {
  id: 'inv-9', number: 'СЧ-2026-000009', status: 'to_pay', status_label: 'К оплате',
  amount: '1250000.00', currency_code: 'KZT', paid_bank_amount: '0.00', remainder: '1250000.00',
  recon_status: 'no_data', recon_status_label: 'Нет данных',
  counterparty: { id: 'cp-1', name: 'ТОО «Альфа»', reg_number: '100000000001' },
  same_bin: true, ext_number: '', ext_date: null,
};

let user: ReturnType<typeof userEvent.setup>;

/** Строки по вкладкам: ключ — параметр `tab` запроса. */
function serve(linesByTab: Partial<Record<string, StatementLine[]>>, card: BankImportCard = CARD) {
  get.mockImplementation((url: string, config?: { params?: Record<string, string> }) => {
    if (url.endsWith('/lines')) {
      const items = linesByTab[config?.params?.tab ?? ''] ?? [];
      return Promise.resolve({ data: { items, total: items.length, page: 1, page_size: 50 } });
    }
    if (url.endsWith('/candidates')) return Promise.resolve({ data: { items: [CANDIDATE] } });
    if (url.endsWith('/impact')) return Promise.resolve({ data: { invoices: 3, lines: 12 } });
    return Promise.resolve({ data: card });
  });
  post.mockResolvedValue({ data: {} });
}

const cardCalls = () => get.mock.calls.filter(([url]) => url === 'bpp/v1/bank/imports/imp-1');
const lineTabs = () => get.mock.calls
  .filter(([url]) => String(url).endsWith('/lines'))
  .map(([, config]) => (config as { params: { tab?: string } }).params.tab);

function renderPage() {
  return renderWithProviders(
    <Routes>
      <Route path="/bpp/bank/:id" element={<BankImportPage />} />
    </Routes>,
    { route: '/bpp/bank/imp-1' },
  );
}

beforeEach(() => {
  user = userEvent.setup();
  get.mockReset();
  post.mockReset();
  toastError.mockReset();
  canEdit.value = true;
});

describe('результат сверки', () => {
  it('вкладки со счётчиками и суммами; вкладка просит у сервера свои строки', async () => {
    serve({ matched: [{ ...LINE, match_status: 'matched', matches: [{ ...MATCH, state: 'active' }] }], unmatched: [LINE] });
    renderPage();

    expect(await screen.findByRole('tab', { name: 'Сопоставлены (2)' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Требуют проверки (1)' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Не сопоставлены (1)' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Исключены (1)' })).toBeInTheDocument();
    const totals = screen.getByLabelText('Итог сверки');
    expect(within(totals).getByText('2 500 000,00 KZT')).toBeInTheDocument();
    expect(await screen.findByRole('link', { name: 'СЧ-2026-000001' })).toHaveAttribute('href', '/bpp/invoices/inv-1');
    expect(lineTabs()).toEqual(['matched']);

    await user.click(screen.getByRole('tab', { name: 'Не сопоставлены (1)' }));
    expect(await screen.findByText('ТОО «Альфа»')).toBeInTheDocument();
    expect(lineTabs()).toContain('unmatched');
  });

  it('«Сверена» — строки на экране, опроса нет', async () => {
    serve({ matched: [LINE] });
    renderPage();
    expect(await screen.findByText('ТОО «Альфа»')).toBeInTheDocument();
    expect(cardCalls()).toHaveLength(1);
  });

  it('номер счёта в назначении подсвечен', async () => {
    serve({ matched: [{ ...LINE, found_numbers: ['СЧ-2026-000001'] }] });
    renderPage();
    const mark = await screen.findByText('СЧ-2026-000001', { selector: 'mark' });
    expect(mark.closest('span')).toHaveTextContent('Оплата по счёту СЧ-2026-000001 за материалы');
  });

  it('splitPurpose находит «грязный» номер', () => {
    const parts = splitPurpose('оплата сч 2026 000001, спасибо', ['СЧ-2026-000001']);
    expect(parts.filter((part) => part.hit).map((part) => part.text)).toEqual(['сч 2026 000001']);
  });

  it('splitPurpose находит номер с латинскими C/X и подсвечивает исходный текст', () => {
    // «cч» — латинская c, «CЧ» — латинская C: сервер такие номера находит (C/X → С/Х).
    const purpose = 'Opl. cч-2026-000001 и CЧ 2026 000002; Xerox';
    const parts = splitPurpose(purpose, ['СЧ-2026-000001', 'СЧ-2026-000002']);
    expect(parts.filter((part) => part.hit).map((part) => part.text))
      .toEqual(['cч-2026-000001', 'CЧ 2026 000002']);
    expect(parts.map((part) => part.text).join('')).toBe(purpose);
  });

  it('диалог ручного сопоставления не отправляет Σ больше суммы строки', async () => {
    serve({ matched: [], unmatched: [LINE] });
    renderPage();
    await user.click(await screen.findByRole('tab', { name: 'Не сопоставлены (1)' }));
    await user.click(await screen.findByRole('button', { name: 'Сопоставить вручную' }));
    await user.click(await screen.findByRole('button', { name: 'Выбрать счёт СЧ-2026-000009' }));

    const amount = screen.getByRole('textbox', { name: 'Сумма на счёт СЧ-2026-000009' });
    expect(amount).toHaveValue('1250000.00');
    expect(screen.getByText('Остаток к распределению: 0,00 KZT')).toBeInTheDocument();
    const submit = screen.getByRole('button', { name: 'Сопоставить' });
    expect(submit).toBeEnabled();

    await user.clear(amount);
    await user.type(amount, '1300000');
    expect(screen.getByText('Сумма распределения больше суммы платежа на 50 000,00 KZT')).toBeInTheDocument();
    expect(submit).toBeDisabled();
    await user.click(submit);
    expect(post).not.toHaveBeenCalled();

    await user.clear(amount);
    await user.type(amount, '1000000');
    expect(screen.getByText('Остаток к распределению: 250 000,00 KZT')).toBeInTheDocument();
    await user.click(submit);
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(post.mock.calls[0][0]).toBe('bpp/v1/bank/lines/line-1/match');
    expect(post.mock.calls[0][1]).toEqual({
      allocations: [{ invoice_id: 'inv-9', amount: '1000000.00' }], comment: '',
    });
  });

  it('отказ сервера по полю amount — у суммы, а не тостом', async () => {
    serve({ unmatched: [LINE] });
    post.mockRejectedValue({
      response: { status: 422, data: { detail: 'Сумма больше строки', code: 'E-VAL-01', fields: [{ field: 'amount', message: 'Сумма больше строки' }] } },
    });
    renderPage();
    await user.click(await screen.findByRole('tab', { name: 'Не сопоставлены (1)' }));
    await user.click(await screen.findByRole('button', { name: 'Сопоставить вручную' }));
    await user.click(await screen.findByRole('button', { name: 'Выбрать счёт СЧ-2026-000009' }));
    await user.click(screen.getByRole('button', { name: 'Сопоставить' }));

    expect(await screen.findByText('Сумма больше строки')).toBeInTheDocument();
    expect(toastError).not.toHaveBeenCalled();
  });

  it('без права bpp.bank edit кнопок действий нет, выгрузка есть', async () => {
    canEdit.value = false;
    serve({ matched: [], unmatched: [LINE] });
    renderPage();
    await user.click(await screen.findByRole('tab', { name: 'Не сопоставлены (1)' }));
    expect(await screen.findByText('ТОО «Альфа»')).toBeInTheDocument();

    expect(screen.queryByRole('button', { name: 'Сопоставить вручную' })).toBeNull();
    expect(screen.queryByRole('button', { name: /Исключить/ })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Отменить загрузку' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Сверить' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Выгрузить результат' })).toBeInTheDocument();
  });

  it('«Сверить» — у «Загружена» и с правом; ход — POST reconcile', async () => {
    serve({ matched: [] }, { ...CARD, status: 'loaded', status_label: 'Загружена', totals: undefined });
    renderPage();
    await user.click(await screen.findByRole('button', { name: 'Сверить' }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(post.mock.calls[0][0]).toBe('bpp/v1/bank/imports/imp-1/reconcile');
  });

  it('комментарий из 9 символов не отправляется, из 10 — отправляется; после действия всё перечитывается', async () => {
    serve({ matched: [], unmatched: [LINE] });
    renderPage();
    await user.click(await screen.findByRole('tab', { name: 'Не сопоставлены (1)' }));
    await user.click(await screen.findByRole('button', { name: /Исключить/ }));

    const dialog = await screen.findByRole('dialog');
    const comment = within(dialog).getByRole('textbox');
    const submit = within(dialog).getByRole('button', { name: 'Исключить' });
    await user.type(comment, '123456789');
    expect(within(dialog).getByText('Не короче 10 символов: 9 из 10')).toBeInTheDocument();
    expect(submit).toBeDisabled();
    await user.click(submit);
    expect(post).not.toHaveBeenCalled();

    const cardBefore = cardCalls().length;
    const linesBefore = lineTabs().length;
    await user.type(comment, '0');
    expect(submit).toBeEnabled();
    await user.click(submit);

    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(post.mock.calls[0][0]).toBe('bpp/v1/bank/lines/line-1/exclude');
    expect(post.mock.calls[0][1]).toEqual({ comment: '1234567890' });
    await waitFor(() => expect(cardCalls().length).toBeGreaterThan(cardBefore));
    await waitFor(() => expect(lineTabs().length).toBeGreaterThan(linesBefore));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  });

  it('«Подтвердить» показывает остаток счёта рядом с предложенным распределением', async () => {
    serve({ matched: [], review: [{ ...LINE, match_status: 'needs_review', matches: [MATCH], review_reason_label: 'Сумма не делится' }] });
    renderPage();
    await user.click(await screen.findByRole('tab', { name: 'Требуют проверки (1)' }));
    await user.click(await screen.findByRole('button', { name: 'Подтвердить' }));

    const preview = await screen.findByRole('list', { name: 'Предложенное распределение' });
    // Остаток 1 500 000 − 1 000 000 = 500 000; предложено 900 000 — переплата.
    expect(within(preview).getByText(/остаток счёта 500 000,00 KZT, распределено 900 000,00 KZT/)).toBeInTheDocument();
    expect(within(preview).getByText('— переплата')).toBeInTheDocument();
  });

  it('«Отменить загрузку» называет число затронутых счетов и отправляет отмену', async () => {
    serve({ matched: [] });
    renderPage();
    await user.click(await screen.findByRole('button', { name: 'Отменить загрузку' }));

    const dialog = await screen.findByRole('dialog');
    expect(await within(dialog).findByText('Отмена затронет счетов: 3, строк выписки: 12')).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: 'Отменить загрузку' }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(post.mock.calls[0][0]).toBe('bpp/v1/bank/imports/imp-1/cancel');
  });
});

describe('окно автосверки после «Загружена»', () => {
  const ago = (ms: number) => new Date(Date.now() - ms).toISOString();
  const loaded = (finishedAgo: number): BankImportCard => ({
    ...CARD, status: 'loaded', status_label: 'Загружена', finished_at: ago(finishedAgo), totals: undefined,
  });

  beforeEach(() => { vi.useFakeTimers({ shouldAdvanceTime: true }); });
  afterEach(() => { vi.useRealTimers(); });

  it('свежая «Загружена» опрашивается до «Сверена»; «Сверить» закрыта с подсказкой; строки читаются заново', async () => {
    let calls = 0;
    const sequence = [loaded(10_000), loaded(10_000), CARD];
    get.mockImplementation((url: string, config?: { params?: Record<string, string> }) => {
      if (url.endsWith('/lines')) {
        return Promise.resolve({ data: { items: [], total: 0, page: 1, page_size: 50, tab: config?.params?.tab } });
      }
      const next = sequence[Math.min(calls, sequence.length - 1)];
      calls += 1;
      return Promise.resolve({ data: next });
    });
    renderPage();

    const reconcile = await screen.findByRole('button', { name: 'Сверить' });
    expect(reconcile).toBeDisabled();
    expect(reconcile).toHaveAttribute('title', 'Автосверка ещё идёт — дождитесь её окончания');
    expect(screen.getByText('Идёт автосверка со счетами. Страница обновится сама.')).toBeInTheDocument();
    expect(cardCalls()).toHaveLength(1);
    const linesBefore = lineTabs().length;

    await act(() => vi.advanceTimersByTimeAsync(IMPORT_POLL_MS));
    await act(() => vi.advanceTimersByTimeAsync(IMPORT_POLL_MS));
    expect(await screen.findByText('Сверена')).toBeInTheDocument();
    expect(cardCalls()).toHaveLength(3);
    expect(screen.queryByRole('button', { name: 'Сверить' })).toBeNull();
    await waitFor(() => expect(lineTabs().length).toBeGreaterThan(linesBefore));

    await act(() => vi.advanceTimersByTimeAsync(IMPORT_POLL_MS * 3));
    expect(cardCalls()).toHaveLength(3);
  });

  it('«Загружена» старше окна не опрашивается, «Сверить» доступна', async () => {
    serve({ matched: [] }, loaded(AUTOMATCH_WINDOW_MS + 60_000));
    renderPage();

    expect(await screen.findByRole('button', { name: 'Сверить' })).toBeEnabled();
    expect(screen.queryByText(/Идёт автосверка/)).toBeNull();
    await act(() => vi.advanceTimersByTimeAsync(IMPORT_POLL_MS * 3));
    expect(cardCalls()).toHaveLength(1);
  });

  it('опрос останавливается, когда «Загружена» вышла за окно', async () => {
    serve({ matched: [] }, loaded(AUTOMATCH_WINDOW_MS - 1_000));
    renderPage();
    await screen.findByRole('button', { name: 'Сверить' });
    await act(() => vi.advanceTimersByTimeAsync(IMPORT_POLL_MS * 2));
    // Окно закрылось между опросами: один-два лишних запроса, дальше тишина.
    const settled = cardCalls().length;
    await act(() => vi.advanceTimersByTimeAsync(IMPORT_POLL_MS * 4));
    expect(cardCalls().length).toBe(settled);
    expect(settled).toBeLessThanOrEqual(3);
    expect(await screen.findByRole('button', { name: 'Сверить' })).toBeEnabled();
  });

  it('пустая сверенная загрузка (все четыре группы по нулю) объясняет, почему строк нет', async () => {
    const zero = { count: 0, amount: '0.00' };
    serve({ matched: [] }, {
      ...CARD,
      totals: { matched: zero, needs_review: zero, unmatched: zero, excluded: zero, unallocated: '0.00' },
    });
    renderPage();
    expect(await screen.findByText(/Новых списаний в выписке нет/)).toBeInTheDocument();
  });

  it('пустая вкладка при непустых группах — нейтральный текст', async () => {
    serve({ matched: [] });
    renderPage();
    expect(await screen.findByText('В этой вкладке строк нет.')).toBeInTheDocument();
  });
});
