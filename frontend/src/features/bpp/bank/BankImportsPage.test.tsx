/**
 * Реестр L-07 «Загрузки выписок»: сортировки у ручки нет — заголовки не
 * кнопки; «Кто загрузил» виден сразу, «Сопоставлено / Не сопоставлено» —
 * скрытые колонки; быстрый поиск — номер или комментарий, параметр `q`;
 * «Загрузить выписку» — только держателю `bpp.bank` `edit` и уносит место в
 * реестре, куда вернёт «Отмена» формы.
 */
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { Permissions } from '@/hooks/usePermissions';
import { renderWithProviders } from '@/test/renderWithProviders';

import type { BankImportRow } from './api';
import { BankImportForm } from './BankImportForm';
import { BankImportsPage } from './BankImportsPage';

const get = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get, post: vi.fn() } }));

vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() } }));

const canUpload = vi.hoisted(() => ({ value: true }));
vi.mock('@/hooks/usePermissions', () => ({
  usePermissions: () => ({
    atLeast: () => true,
    can: (node: string, flag: string) => (node === 'bpp.bank' && flag === 'edit' ? canUpload.value : true),
  }) as unknown as Permissions,
}));

const ROW: BankImportRow = {
  id: 'imp-1', number: 'ВП-2026-0001',
  account: { id: 'acc-1', iban: 'KZ86125KZT5004100100', bank_name: 'Халык Банк', currency: 'KZT' },
  bank_name: 'Халык Банк', format: 'csv', period_from: '2026-09-01', period_to: '2026-09-15',
  status: 'loaded', status_label: 'Загружена', filename: 'vypiska.csv', comment: '',
  rows_total: 3, debits: 2, rows_done: 2, duplicates: 0, errors_count: 0, lines: 2,
  matched: 1, unmatched: 1, author_id: 901, author_name: 'Тест Фд',
  created_at: '2026-09-28T05:00:00Z', finished_at: '2026-09-28T05:01:00Z',
};

beforeEach(() => {
  window.localStorage.clear();
  canUpload.value = true;
  get.mockReset();
  get.mockImplementation((url: string) => Promise.resolve({
    data: url.endsWith('bank/imports')
      ? { items: [ROW], total: 120, page: 1, page_size: 50 }
      : [],
  }));
});

afterEach(() => window.localStorage.clear());

function renderRegistry(route = '/bpp/bank') {
  return renderWithProviders(
    <Routes>
      <Route path="/bpp/bank" element={<BankImportsPage />} />
      <Route path="/bpp/bank/new" element={<BankImportForm />} />
    </Routes>,
    { route },
  );
}

describe('BankImportsPage', () => {
  it('сортировки у ручки нет — ни один заголовок не кнопка, «Статус» тоже', async () => {
    renderRegistry();
    await screen.findByRole('link', { name: 'ВП-2026-0001' });

    const table = screen.getByRole('table');
    const status = within(table).getByRole('columnheader', { name: 'Статус' });
    expect(within(status).queryByRole('button')).toBeNull();
    expect(status).not.toHaveAttribute('aria-sort');
    for (const header of within(table).getAllByRole('columnheader')) {
      expect(within(header).queryByRole('button')).toBeNull();
    }
  });

  it('«Кто загрузил» виден сразу, «Сопоставлено» и «Не сопоставлено» скрыты', async () => {
    renderRegistry();
    await screen.findByRole('link', { name: 'ВП-2026-0001' });

    const table = screen.getByRole('table');
    expect(within(table).getByRole('columnheader', { name: 'Кто загрузил' })).toBeInTheDocument();
    expect(within(table).getByText('Тест Фд')).toBeInTheDocument();
    expect(within(table).queryByRole('columnheader', { name: 'Сопоставлено' })).toBeNull();
    expect(within(table).queryByRole('columnheader', { name: 'Не сопоставлено' })).toBeNull();
  });

  it('быстрый поиск — номер или комментарий, уходит в запрос параметром `q`', async () => {
    const user = userEvent.setup();
    renderRegistry();
    await screen.findByRole('link', { name: 'ВП-2026-0001' });

    const search = screen.getByRole('textbox', { name: 'Быстрый поиск' });
    expect(search).toHaveAttribute('placeholder', 'Номер или комментарий');
    await user.type(search, 'вп-2026');

    const registryCalls = () => get.mock.calls.filter(([url]) => String(url).endsWith('bank/imports'));
    await waitFor(() => expect(registryCalls().at(-1)?.[1].params).toMatchObject({ q: 'вп-2026', page: 1 }));
    expect(registryCalls().at(-1)?.[1].params).not.toHaveProperty('search');
  });

  it('без права загрузки кнопки «Загрузить выписку» нет', async () => {
    canUpload.value = false;
    renderRegistry();
    await screen.findByRole('link', { name: 'ВП-2026-0001' });

    expect(screen.queryByRole('link', { name: 'Загрузить выписку' })).toBeNull();
  });

  it('«Загрузить выписку» уносит место в реестре — «Отмена» формы ведёт туда же', async () => {
    const user = userEvent.setup();
    renderRegistry('/bpp/bank?page=2');
    await screen.findByRole('link', { name: 'ВП-2026-0001' });
    const registryCalls = () => get.mock.calls.filter(([url]) => String(url).endsWith('bank/imports'));
    await waitFor(() => expect(registryCalls().at(-1)?.[1].params).toMatchObject({ page: 2 }));

    await user.click(screen.getByRole('link', { name: 'Загрузить выписку' }));

    expect(await screen.findByText('Загрузка выписки')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Отмена' })).toHaveAttribute('href', '/bpp/bank?page=2');
  });
});
