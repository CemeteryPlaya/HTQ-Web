/**
 * Карточка записи KPI: «Аннулировать» скрыта без `bpp.kpi` edit; комментарий
 * из 9 знаков не отправляется; уходит `Idempotency-Key`; после аннулирования
 * перечитываются карточка и отчёт, после 409 — карточка; журнал подписан
 * по-человечески (действия, поля, суммы, статусы).
 */
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { Permissions } from '@/hooks/usePermissions';
import { renderWithProviders } from '@/test/renderWithProviders';

import type { KpiRecord } from './api';
import { KpiRecordPage } from './KpiRecordPage';

const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get, post } }));
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() } }));

const rights = vi.hoisted(() => ({ edit: true }));
vi.mock('@/hooks/usePermissions', () => ({
  usePermissions: () => ({
    atLeast: () => true, can: (_node: string, flag: string) => flag === 'view' || rights.edit,
  }) as unknown as Permissions,
}));

const RECORD: KpiRecord = {
  id: 'k1', version: 3, offer_id: 'o1', offer_number: 'АП-2026-0001', offer_url: '/bpp/alternatives/o1',
  buyer_id: 7, buyer_name: 'Снабженцев Иван', buyer_role: 'sn', own_document: true,
  project_id: 'p1', article_id: 'a1', source_type: 'invoice', source_id: 'i1',
  source_number: 'СЧ-2026-000001', source_url: '/bpp/invoices/i1', source_amount_kzt: '1000000.00',
  result_type: 'invoice', result_id: 'i2', result_number: 'СЧ-2026-000002', result_url: '/bpp/invoices/i2',
  result_amount_kzt: '900000.00', saving_amount: '100000.00', saving_pct: '10.00',
  status: 'confirmed', status_label: 'Подтверждён', status_changed_at: '2026-09-29T05:00:00Z',
  selected_at: '2026-09-28T05:00:00Z', selected_by_id: 2, annul_comment: '', annulled_by_id: null,
};

let current: KpiRecord;

const HISTORY = [
  {
    id: 'h1', action: 'created', actor_id: 2, actor_name: 'Финансов Ф.', comment: '', created_at: '2026-09-28T05:00:00Z',
    changes: { offer: 'АП-2026-0001', source_amount_kzt: '1000000.00' },
  },
  {
    id: 'h2', action: 'annulled_system', actor_id: null, comment: 'Документ отменён', created_at: '2026-09-29T05:00:00Z',
    changes: { status: ['confirmed', 'annulled'] },
  },
];

beforeEach(() => {
  get.mockReset();
  post.mockReset();
  rights.edit = true;
  current = RECORD;
  get.mockImplementation((url: string) => {
    if (String(url).includes('kpi/records/k1')) return Promise.resolve({ data: current });
    if (String(url).includes('history/bpp.kpirecord/k1')) return Promise.resolve({ data: HISTORY });
    return Promise.resolve({ data: [] });
  });
  post.mockImplementation(() => {
    current = { ...RECORD, status: 'annulled', version: 4, annul_comment: 'Документ отменён' };
    return Promise.resolve({ data: current });
  });
});

const renderCard = () => renderWithProviders(
  <Routes><Route path="/bpp/kpi/:id" element={<KpiRecordPage />} /></Routes>, { route: '/bpp/kpi/k1' });

const cardCalls = () => get.mock.calls.filter(([url]) => String(url).includes('kpi/records/k1'));

describe('KpiRecordPage', () => {
  it('ссылки на исходный документ, АП и новый документ', { timeout: 20000 }, async () => {
    renderCard();
    expect(await screen.findByRole('link', { name: 'Счёт СЧ-2026-000001' })).toHaveAttribute('href', '/bpp/invoices/i1');
    expect(screen.getByRole('link', { name: 'АП-2026-0001' })).toHaveAttribute('href', '/bpp/alternatives/o1');
    expect(screen.getByRole('link', { name: 'Счёт СЧ-2026-000002' })).toHaveAttribute('href', '/bpp/invoices/i2');
    expect(screen.getByTestId('own-document')).toBeInTheDocument();
  });

  it('«Аннулировать» скрыта без bpp.kpi edit', { timeout: 20000 }, async () => {
    rights.edit = false;
    renderCard();
    await screen.findByRole('link', { name: 'АП-2026-0001' });
    expect(screen.queryByRole('button', { name: 'Аннулировать' })).toBeNull();
  });

  it('журнал: подписи действий и полей, суммы и статусы', { timeout: 20000 }, async () => {
    renderCard();
    expect(await screen.findByText('Аннулирован системой')).toBeInTheDocument();
    const items = screen.getAllByRole('listitem');
    expect(items.some((li) => li.textContent === 'Статус: Подтверждён → Аннулирован')).toBe(true);
    expect(items.some((li) => li.textContent === 'Исходная сумма: 1 000 000,00')).toBe(true);
    expect(items.some((li) => li.textContent === 'Альтернативное предложение: АП-2026-0001')).toBe(true);
  });

  it('409 при аннулировании — карточка перечитывается, диалог остаётся', { timeout: 30000 }, async () => {
    post.mockImplementation(() => Promise.reject({ response: { status: 409, data: { detail: 'Запись изменилась' } } }));
    renderCard();
    await userEvent.click(await screen.findByRole('button', { name: 'Аннулировать' }));
    await userEvent.type(screen.getByRole('textbox'), '1234567890');
    const before = cardCalls().length;
    await userEvent.click(screen.getAllByRole('button', { name: 'Аннулировать' }).at(-1) as HTMLElement);
    await vi.waitFor(() => expect(cardCalls().length).toBeGreaterThan(before));
    expect(screen.getByRole('textbox')).toHaveValue('1234567890');
  });

  it('комментарий из 9 знаков не отправляется, из 10 — да; карточка и отчёт перечитываются', { timeout: 30000 }, async () => {
    const { queryClient } = renderCard();
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries');
    await userEvent.click(await screen.findByRole('button', { name: 'Аннулировать' }));
    const dialogButton = () => screen.getAllByRole('button', { name: 'Аннулировать' }).at(-1) as HTMLElement;
    await userEvent.type(screen.getByRole('textbox'), '123456789');
    expect(dialogButton()).toBeDisabled();
    expect(post).not.toHaveBeenCalled();

    await userEvent.type(screen.getByRole('textbox'), '0');
    const before = cardCalls().length;
    await userEvent.click(dialogButton());
    await vi.waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(post.mock.calls[0][1]).toEqual({ version: 3, comment: '1234567890' });
    expect(post.mock.calls[0][2].headers['Idempotency-Key']).toBeTruthy();
    await vi.waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ['bpp', 'kpi'] }));
    await vi.waitFor(() => expect(cardCalls().length).toBeGreaterThan(before));
    expect(await screen.findByTestId('annul-comment')).toHaveTextContent('Документ отменён');
    expect(screen.queryByRole('button', { name: 'Аннулировать' })).toBeNull();
  });
});
