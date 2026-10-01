/**
 * Форма F-07 (ТЗ §12.3): экономия и отклонение считаются на лету без `float`
 * (2 800 000 − 2 450 000 → «350 000,00 KZT (12,50 %)»); удорожание подсвечено
 * и обоснование короче 30 знаков не уходит; снятая галочка исключает позицию
 * из суммы и из запроса; ошибка `E-VAL-01` с `fields` — у своего поля.
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { createTestQueryClient } from '@/test/renderWithProviders';

import type { OfferCard } from './api';
import { OfferFormPage } from './OfferFormPage';

const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
const patch = vi.hoisted(() => vi.fn());
const del = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get, post, patch, delete: del } }));
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() } }));
vi.mock('@/hooks/usePermissions', () => ({
  usePermissions: () => ({ can: () => true, atLeast: () => true }),
}));
vi.mock('@/components/files/FilesPanel', () => ({ FilesPanel: () => <div>Панель файлов</div> }));
vi.mock('../core/HistoryTab', () => ({ HistoryTab: () => <div>История</div> }));

const ID = '5b1a7f64-5717-4562-b3fc-2c963f66afa6';
const SOURCE_ID = '3fa85f64-5717-4562-b3fc-2c963f66afa6';

const LINE_1 = {
  id: 'ol1', source_line_id: 'sl1', item: 'ЗЗ-2026-000001-01', name: 'Швеллер', qty: '10.000',
  source_price: '280000.00', price: '245000.00', amount: '2450000.00', deviation_pct: '-12.50',
};
const LINE_2 = {
  id: 'ol2', source_line_id: 'sl2', item: 'ЗЗ-2026-000001-02', name: 'Арматура', qty: '1.000',
  source_price: '100000.00', price: '90000.00', amount: '90000.00', deviation_pct: '-10.00',
};

const card = (over: Partial<OfferCard> = {}): OfferCard => ({
  id: ID, number: 'АП-2026-000001', version: 2, status: 'draft', status_label: 'Черновик',
  source: {
    type: 'invoice', id: SOURCE_ID, number: 'СЧ-2026-000140', status: 'under_review',
    status_label: 'На рассмотрении ФД', amount: '2800000.00', currency_code: 'KZT',
    counterparty: {
      id: 'c0', name: 'ТОО «Исходный»', short_name: '', reg_number: '100000000009',
      country_code: 'KZ', is_vat_payer: true, status: 'active', is_verified: true,
    },
    author_id: 7, author_name: 'Петров', alt_limit: 3, window_open: true,
    url: `/bpp/invoices/${SOURCE_ID}`,
  },
  project: { id: 'p1', code: 'П-015', name: 'Объект' },
  article: { id: 'a1', code: 'T', name: 'Металлопрокат' },
  author_id: 904, author_name: 'Иванов А.', author_role: 'sn', own_document: false,
  counterparty_id: 'c1',
  counterparty: {
    id: 'c1', name: 'ТОО «Альфа»', short_name: '', reg_number: '100000000001',
    country_code: 'KZ', is_vat_payer: true, status: 'active', is_verified: true,
  },
  currency_code: 'KZT', rate: null, amount: '2450000.00', amount_kzt: '2450000.00',
  with_vat: true, vat_rate: '16.00', vat_source: 'refdata', vat_amount: null,
  source_amount_kzt: '2800000.00', saving_amount: '350000.00', saving_pct: '12.50',
  more_expensive: false, delivery_date: '2099-01-15', payment_terms: 'postpay',
  payment_terms_note: '', justification: 'Тот же швеллер дешевле на двенадцать процентов.',
  submitted_at: null, decided_at: null, decision_comment: '', closed_reason: '',
  lines: [LINE_1],
  allowed_actions: ['save', 'submit', 'delete'],
  ...over,
});

function serve(offer: OfferCard, positions = [LINE_1]) {
  get.mockImplementation((url: string) => {
    if (url.endsWith(`offers/${ID}`)) return Promise.resolve({ data: offer });
    if (url.includes('/comparison')) {
      return Promise.resolve({ data: { positions: positions.map((row) => ({
        source_line_id: row.source_line_id, item: row.item, name: row.name, uom: 'т',
        qty: row.qty, source_price: row.source_price, source_amount: '0', offers: {},
      })) } });
    }
    return Promise.resolve({ data: [] });
  });
}

function renderForm() {
  return render(
    <QueryClientProvider client={createTestQueryClient()}>
      <MemoryRouter initialEntries={[`/bpp/alternatives/${ID}`]}>
        <Routes>
          <Route path="/bpp/alternatives/:id" element={<OfferFormPage />} />
          <Route path="/bpp/alternatives" element={<div>Лента</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const priceInput = (item: string) => screen.getByLabelText(`Цена АП за ед. ${item}`);

describe('OfferFormPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
  });

  it('экономия и отклонение считаются на лету без float', { timeout: 15000 }, async () => {
    serve(card({ lines: [{ ...LINE_1, price: null, amount: null, deviation_pct: null }], saving_amount: null, saving_pct: null }));
    renderForm();

    const input = await screen.findByLabelText('Цена АП за ед. ЗЗ-2026-000001-01', {}, { timeout: 4000 });
    await userEvent.type(input, '245 000');

    expect(screen.getByTestId('offer-saving')).toHaveTextContent('Экономия: 350 000,00 KZT (12,50 %)');
    expect(screen.getByTestId('offer-total')).toHaveTextContent('2 450 000,00 KZT');
    expect(screen.getByText('-12,50 %')).toBeInTheDocument();
  });

  it('удорожание подсвечено оранжевым, «Подать» не шлёт обоснование короче 30 знаков', { timeout: 20000 }, async () => {
    serve(card({ justification: 'Короткое обоснование.' }));
    post.mockResolvedValue({ data: card({ status: 'submitted', allowed_actions: ['withdraw'] }) });
    patch.mockResolvedValue({ data: card({ version: 3 }) });
    renderForm();

    const input = await screen.findByLabelText('Цена АП за ед. ЗЗ-2026-000001-01', {}, { timeout: 4000 });
    await userEvent.clear(input);
    await userEvent.type(input, '300 000');

    const saving = screen.getByTestId('offer-saving');
    expect(saving).toHaveTextContent('Дороже на 200 000,00 KZT (7,14 %)');
    expect(saving.className).toContain('amber');

    await userEvent.click(screen.getByRole('button', { name: 'Подать' }));
    expect(await screen.findByText(/не короче 30 знаков/, { selector: 'p.text-destructive' })).toBeInTheDocument();
    expect(post).not.toHaveBeenCalled();
    expect(patch).not.toHaveBeenCalled();
  });

  it('снятая галочка исключает позицию из суммы и из запроса', { timeout: 20000 }, async () => {
    serve(card({ lines: [LINE_1, LINE_2] }), [LINE_1, LINE_2]);
    patch.mockResolvedValue({ data: card({ version: 3 }) });
    renderForm();

    await screen.findByLabelText('Цена АП за ед. ЗЗ-2026-000001-02', {}, { timeout: 4000 });
    expect(screen.getByTestId('offer-total')).toHaveTextContent('2 540 000,00 KZT');
    await userEvent.click(screen.getByRole('checkbox', { name: 'Входит в АП ЗЗ-2026-000001-02' }));
    expect(screen.getByTestId('offer-total')).toHaveTextContent('2 450 000,00 KZT');
    expect(priceInput('ЗЗ-2026-000001-02')).toBeDisabled();

    await userEvent.click(screen.getByRole('button', { name: 'Сохранить черновик' }));
    await waitFor(() => expect(patch).toHaveBeenCalled());
    const [url, body] = patch.mock.calls[0];
    expect(url).toContain(`offers/${ID}`);
    expect(body.lines).toEqual([{ source_line_id: 'sl1', price: '245000.00' }]);
    expect(body.version).toBe(2);
  });

  it('E-VAL-01 с fields показывается у поля, а не только тостом', { timeout: 20000 }, async () => {
    serve(card());
    post.mockRejectedValue({
      response: {
        status: 422,
        data: {
          detail: 'Не удалось подать альтернативу.', code: 'E-VAL-01',
          fields: [{ field: 'files', message: 'Обязательное поле' }],
        },
      },
    });
    renderForm();

    await userEvent.click(await screen.findByRole('button', { name: 'Подать' }, { timeout: 4000 }));
    expect(await screen.findByText('Обязательное поле')).toBeInTheDocument();
    expect(post.mock.calls[0][0]).toContain(`offers/${ID}/submit`);
    expect(post.mock.calls[0][1]).toEqual({ version: 2 });
  });

  it('поданная АП — только просмотр, «Отозвать» по allowed_actions', { timeout: 15000 }, async () => {
    serve(card({ status: 'submitted', allowed_actions: ['withdraw'] }));
    renderForm();

    expect(await screen.findByRole('button', { name: 'Отозвать' }, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Подать' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Сохранить черновик' })).toBeNull();
    expect(screen.queryByLabelText('Цена АП за ед. ЗЗ-2026-000001-01')).toBeNull();
    expect(screen.getByText('Только просмотр')).toBeInTheDocument();
  });
});
