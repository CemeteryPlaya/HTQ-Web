/**
 * Реестр L-08 «Контрагенты» (ТЗ §18, §19; задача 9 плана этапа 2 A):
 * строки сервера на экране, 50 строк на странице по умолчанию, поиск —
 * параметром `q`, «Создать» — только с правом `create`.
 */
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { Permissions } from '@/hooks/usePermissions';
import type { DepthFlag } from '@/lib/auth/permissions';
import { createTestQueryClient } from '@/test/renderWithProviders';

import { CounterpartiesPage } from './CounterpartiesPage';

const get = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get } }));

function permissionsWith(depth: Record<string, DepthFlag[]>): Permissions {
  return {
    company: 'hi-tech-qazaqstan',
    level: () => 'read',
    atLeast: () => true,
    scope: () => null,
    depth: (node) => depth[node] ?? [],
    can: (node, flag) => (depth[node] ?? []).includes(flag),
    pageHidden: () => false,
    subordinateCompanies: [],
    inheritedFrom: [],
    companyArchived: false,
    isLoading: false,
    isError: false,
    refetch: () => {},
  };
}
const permissions = vi.fn(() => permissionsWith({ 'bpp.counterparties': ['view', 'create'] }));
vi.mock('@/hooks/usePermissions', () => ({ usePermissions: () => permissions() }));

const row = (id: string, name: string, over: Record<string, unknown> = {}) => ({
  id, name, short_name: '', kind: 'legal', country_code: 'KZ', reg_number: '100000000001',
  is_vat_payer: false, status: 'active', is_verified: false, verified_override: null,
  verified_threshold: 3, successful_documents: 0, version: 1, ...over,
});

function mockServer(items: ReturnType<typeof row>[]) {
  get.mockImplementation((url: string) => {
    if (url.startsWith('refdata/')) {
      return Promise.resolve({ data: [{ code: 'KZ', name: 'Казахстан' }] });
    }
    return Promise.resolve({ data: { items, total: items.length, page: 1, page_size: 50 } });
  });
}

const registryCalls = () => get.mock.calls.filter(([url]) => url === 'bpp/v1/counterparties');

function renderPage() {
  return render(
    <QueryClientProvider client={createTestQueryClient()}>
      <MemoryRouter>
        <CounterpartiesPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('CounterpartiesPage', () => {
  beforeEach(() => {
    window.localStorage.clear();
    get.mockReset();
    permissions.mockReturnValue(permissionsWith({ 'bpp.counterparties': ['view', 'create'] }));
  });

  it('показывает строки сервера; по умолчанию 50 строк на странице, сортировка по имени', async () => {
    mockServer([
      row('1', 'ТОО «Альфа»', { status: 'blocked' }),
      row('2', 'ТОО «Бета»', { is_verified: true }),
    ]);
    renderPage();

    expect(await screen.findByText('ТОО «Альфа»')).toBeInTheDocument();
    expect(screen.getByText('ТОО «Бета»')).toBeInTheDocument();
    expect(screen.getByText('Заблокирован')).toBeInTheDocument();
    expect(screen.getByText('Проверенный')).toBeInTheDocument();

    const params = registryCalls()[0][1].params;
    expect(params).toMatchObject({ page: 1, page_size: 50, sort: 'name' });
    expect(screen.getByRole('combobox', { name: 'Строк на странице' })).toHaveTextContent('50');
  });

  it('с правом create — ссылка «Создать» на форму нового контрагента', async () => {
    mockServer([row('1', 'ТОО «Альфа»')]);
    renderPage();
    await screen.findByText('ТОО «Альфа»');
    expect(screen.getByRole('link', { name: 'Создать' })).toHaveAttribute('href', '/bpp/counterparties/new');
  });

  it('без права create кнопки «Создать» нет', async () => {
    permissions.mockReturnValue(permissionsWith({ 'bpp.counterparties': ['view'] }));
    mockServer([row('1', 'ТОО «Альфа»')]);
    renderPage();
    await screen.findByText('ТОО «Альфа»');
    expect(screen.queryByRole('link', { name: 'Создать' })).not.toBeInTheDocument();
  });

  it('пустой ответ — «ничего не найдено»', async () => {
    mockServer([]);
    renderPage();
    await waitFor(() => expect(registryCalls()).toHaveLength(1));
    expect(await screen.findByText(/Ничего не найдено/)).toBeInTheDocument();
  });
});
