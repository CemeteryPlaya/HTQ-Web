/**
 * Блок «Альтернативы» форм договора и счёта (ТЗ §12.4): `can_propose=false`
 * прячет кнопку; чужой черновик не показывается; слот `renderSelect` зовётся
 * для каждой АП «Подано»; отозванные — приглушены; «Потребность» исходного
 * документа скрыта без даты; автор документа поднимает лимит (только с
 * `bpp.alternatives` create); без `bpp.alternatives` view сравнение не
 * запрашивается и блока нет.
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { createTestQueryClient } from '@/test/renderWithProviders';

import type { Comparison, ComparisonOffer } from './api';
import { AlternativesBlock } from './AlternativesBlock';

const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get, post } }));
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() } }));
vi.mock('@/hooks/useActiveProfile', () => ({
  useActiveProfile: () => ({ activeProfile: { id: '7' } }),
}));
const granted = vi.hoisted(() => ({ flags: new Set(['view', 'create']) }));
vi.mock('@/hooks/usePermissions', () => ({
  usePermissions: () => ({
    can: (node: string, flag: string) => node === 'bpp.alternatives' && granted.flags.has(flag),
    atLeast: () => true,
  }),
}));

const CP = {
  id: 'c', name: 'ТОО «Альфа»', short_name: '', reg_number: '100000000001',
  country_code: 'KZ', country_name: 'Казахстан', is_vat_payer: true, status: 'active', is_verified: true,
};

const offer = (id: string, over: Partial<ComparisonOffer> = {}): ComparisonOffer => ({
  kind: 'offer', id, number: `АП-${id}`, version: 1, status: 'submitted', status_label: 'Подано',
  counterparty: { ...CP, id: `c-${id}`, name: `Поставщик ${id}` }, currency_code: 'KZT',
  amount: '2450000.00', amount_kzt: '2450000.00', with_vat: true, vat_rate: '16.00', vat_amount: null,
  source_amount_kzt: '2800000.00', saving: { amount: '350000.00', pct: '12.50', more_expensive: false },
  delivery_date: '2099-02-01', payment_terms: 'postpay', payment_terms_note: '', justification: '',
  files: [{ id: 'f', filename: 'kp.pdf' }], author: { id: 904, name: 'Иванов А.', role: 'sn' },
  own_document: false, submitted_at: '2026-09-29T05:00:00Z', url: `/bpp/alternatives/${id}`,
  ...over,
});

const data = (over: Partial<Comparison> = {}): Comparison => ({
  source: {
    kind: 'source', source_type: 'invoice', id: 'inv', number: 'СЧ-2026-000140',
    status: 'under_review', status_label: 'На рассмотрении ФД', url: '/bpp/invoices/inv',
    counterparty: CP, currency_code: 'KZT', amount: '2800000.00', amount_kzt: '2800000.00',
    with_vat: true, vat_rate: '16.00', vat_amount: null, delivery_date: '2099-01-10',
    payment_terms: null, author: { id: 7, name: 'Петров' },
  },
  offers: [offer('1'), offer('2')],
  positions: [{
    source_line_id: 'l1', item: 'ЗЗ-1-01', name: 'Швеллер', uom: 'т', qty: '10.000',
    source_price: '280000.00', source_amount: '2800000.00',
    offers: {
      1: { price: '245000.00', amount: '2450000.00', deviation_pct: '-12.50' },
      2: { price: '300000.00', amount: '3000000.00', deviation_pct: '7.14' },
    },
  }],
  limit: 3, submitted_count: 2, window_open: true, can_propose: true,
  propose_blocked_reason: null, my_offer_id: null, ...over,
});

function renderBlock(comparison: Comparison, renderSelect?: (o: ComparisonOffer) => React.ReactNode) {
  get.mockResolvedValue({ data: comparison });
  return render(
    <QueryClientProvider client={createTestQueryClient()}>
      <MemoryRouter>
        <AlternativesBlock sourceType="invoice" sourceId="inv" renderSelect={renderSelect} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('AlternativesBlock', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    granted.flags = new Set(['view', 'create']);
  });

  it('без bpp.alternatives view сравнение не запрашивается и блока нет', async () => {
    granted.flags = new Set();
    const { container } = renderBlock(data());
    // Даём запросу шанс уйти, если бы он был разрешён.
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(get).not.toHaveBeenCalled();
    expect(container.querySelector('[data-testid="alternatives-block"]')).toBeNull();
  });

  it('автор документа без bpp.alternatives create (ПМ) поля лимита не видит', async () => {
    granted.flags = new Set(['view']);
    renderBlock(data({ can_propose: false }));
    expect(await screen.findByText('Подано 2 из 3')).toBeInTheDocument();
    expect(screen.queryByLabelText('Лимит альтернатив:')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Поднять' })).toBeNull();
  });

  it('держатель create, но не автор документа, поля лимита не видит', async () => {
    const base = data();
    renderBlock({ ...base, source: { ...base.source, author: { id: 99, name: 'Другой' } } });
    expect(await screen.findByText('Подано 2 из 3')).toBeInTheDocument();
    expect(screen.queryByLabelText('Лимит альтернатив:')).toBeNull();
  });

  it('can_propose=true — кнопка «Предложить альтернативу» заводит черновик', async () => {
    post.mockResolvedValue({ data: { id: 'new-offer' } });
    renderBlock(data());
    await userEvent.click(await screen.findByRole('button', { name: 'Предложить альтернативу' }));
    await waitFor(() => expect(post).toHaveBeenCalled());
    expect(post.mock.calls[0][0]).toContain('alternatives/offers');
    expect(post.mock.calls[0][1]).toEqual({ source_type: 'invoice', source_id: 'inv' });
  });

  it('can_propose=false прячет кнопку', async () => {
    renderBlock(data({ can_propose: false, propose_blocked_reason: 'Окно закрыто' }));
    expect(await screen.findByText('Подано 2 из 3')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Предложить альтернативу' })).toBeNull();
  });

  it('нет альтернатив и подать нельзя — блока нет', async () => {
    const { container } = renderBlock(data({ offers: [], can_propose: false }));
    await waitFor(() => expect(get).toHaveBeenCalled());
    expect(container.querySelector('[data-testid="alternatives-block"]')).toBeNull();
  });

  it('чужой черновик не показывается, свой — и «Моя альтернатива»', async () => {
    renderBlock(data({
      offers: [
        offer('mine', { status: 'draft', status_label: 'Черновик' }),
        offer('alien', { status: 'draft', status_label: 'Черновик' }),
        offer('ok'),
      ],
      my_offer_id: 'mine',
    }));
    const block = await screen.findByTestId('alternatives-block');
    expect(within(block).getByRole('link', { name: 'АП-mine' })).toBeInTheDocument();
    expect(within(block).queryByText('АП-alien')).toBeNull();
    expect(within(block).getByRole('link', { name: 'Моя альтернатива' })).toHaveAttribute('href', '/bpp/alternatives/mine');
  });

  it('renderSelect зовётся для каждой «Подано», не для отозванных', async () => {
    const select = vi.fn((row: ComparisonOffer) => <button type="button">Выбрать {row.number}</button>);
    renderBlock(data({
      offers: [offer('1'), offer('2'), offer('3', { status: 'withdrawn', status_label: 'Отозвано' })],
    }), select);
    expect(await screen.findByRole('button', { name: 'Выбрать АП-1' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Выбрать АП-2' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Выбрать АП-3' })).toBeNull();
    expect(select).toHaveBeenCalledTimes(2);
  });

  it('потребность исходного показана, без даты — пусто; удорожание оранжевым', async () => {
    renderBlock(data({
      offers: [offer('2', { saving: { amount: '-200000.00', pct: '-7.14', more_expensive: true } })],
    }));
    expect(await screen.findByText('Потребность: 10.01.2099')).toBeInTheDocument();
    const dearer = screen.getByText('Дороже на 200 000,00 KZT (7,14 %)');
    expect(dearer.className).toContain('amber');
  });

  it('без даты потребности подписи «Потребность» нет', async () => {
    const base = data();
    renderBlock({ ...base, source: { ...base.source, delivery_date: null } });
    await screen.findByTestId('alternatives-block');
    expect(screen.queryByText(/Потребность/)).toBeNull();
  });

  it('отозванная АП приглушена, статус виден бейджем', async () => {
    renderBlock(data({ offers: [offer('9', { status: 'withdrawn', status_label: 'Отозвано' })] }));
    const head = (await screen.findByRole('link', { name: 'АП-9', hidden: false })).closest('th');
    expect(head?.className).toContain('opacity-50');
    expect(within(head as HTMLElement).getByText('Отозвано')).toBeInTheDocument();
  });

  it('автор документа поднимает лимит (от занятого до 10)', async () => {
    post.mockResolvedValue({ data: { alt_limit: 5 } });
    renderBlock(data());
    const field = await screen.findByLabelText('Лимит альтернатив:');
    const button = screen.getByRole('button', { name: 'Поднять' });
    expect(button).toBeDisabled();
    await userEvent.type(field, '11');
    expect(button).toBeDisabled();
    await userEvent.clear(field);
    await userEvent.type(field, '5');
    await userEvent.click(button);
    await waitFor(() => expect(post).toHaveBeenCalled());
    expect(post.mock.calls[0][0]).toContain('alternatives/sources/invoice/inv/limit');
    expect(post.mock.calls[0][1]).toEqual({ limit: 5 });
  });
});
