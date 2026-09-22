import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { renderWithProviders } from '@/test/renderWithProviders';

/**
 * Форма должности без кадрового «уровня доступа» (рулинг N финальной волны
 * блока I, находка F5 финального ревью).
 *
 * С блока I кадровый доступ выдают роли должности (диалог «Роли должности»),
 * а колонку `Position.permissions` кадровый домен не читает вовсе. Селект
 * «Уровень доступа HR» и кадровые галочки обещали доступ, которого держатель
 * не получал. Остаётся матрица ТОЛЬКО ключей вне `hr.*` (сегодня один —
 * `contracts.advance_payment.record_payment`, его читает `apps.contracts`),
 * а `hr_level` в запрос не уходит.
 *
 * Обвязка — та же, что у соседних `HRPositions*.test.tsx`: страница ходит
 * через `@/api/client`, диалог открывается карандашом в строке должности.
 */

vi.mock('@/components/hr/HRLayout', () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

vi.mock('@/hooks/usePermissions', () => ({
  usePermissions: () => ({
    company: null,
    level: (m: string) => (m === 'hr' ? 'admin' : 'none'),
    atLeast: (m: string) => m === 'hr',
    scope: () => ({ kind: 'company', id: null }),
    depth: () => [],
    can: () => false,
    pageHidden: () => false,
    subordinateCompanies: [],
    inheritedFrom: [],
    isLoading: false,
    isError: false,
    refetch: () => {},
  }),
}));

vi.mock('@/api/client', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

import api from '@/api/client';
import HRPositions from '../HRPositions';

const mockedApi = vi.mocked(api, true);

const LEVELS = [
  { id: 1, level_number: 1, weight_from: 0, weight_to: 99, label: 'Руководство', color: '#8b5cf6' },
];

const CONTRACTS_KEY = 'contracts.advance_payment.record_payment';

const POSITION = {
  id: 1,
  title: 'Бухгалтер',
  department_id: 1,
  department_name: 'Бухгалтерия',
  weight: 10,
  level: 1,
  grade: 10,
  is_system: false,
  is_manager: false,
  external_hierarchy: 'inherit',
  permissions: { hr_level: 'senior', permissions: ['hr.employees.view', CONTRACTS_KEY] },
};

const CATALOG = {
  hr_levels: [{ value: 'senior', label: 'Senior', description: 'Старший кадровик' }],
  permissions: [
    { key: 'hr.employees.view', label: 'Просмотр сотрудников', description: null, group: 'Сотрудники' },
    { key: CONTRACTS_KEY, label: 'Отметка об оплате аванса', description: null, group: 'Договоры' },
  ],
  level_presets: { senior: ['hr.employees.view'] },
};

function stubGet(position: typeof POSITION | Record<string, unknown> = POSITION) {
  mockedApi.get.mockImplementation(((url: string) => {
    if (url.includes('next-weight')) {
      return Promise.resolve({ data: { level_number: 1, weight: 20, weight_from: 0, weight_to: 99 } });
    }
    if (url.includes('positions/levels')) return Promise.resolve({ data: LEVELS });
    if (url.includes('permissions-catalog')) return Promise.resolve({ data: CATALOG });
    if (url.includes('departments')) return Promise.resolve({ data: [{ id: 1, name: 'Бухгалтерия' }] });
    if (url.includes('positions')) return Promise.resolve({ data: [position] });
    return Promise.resolve({ data: [] });
  }) as never);
}

async function openEditDialog(user: ReturnType<typeof userEvent.setup>) {
  const card = await screen.findByText('Бухгалтер');
  const row = card.closest('div[class*="rounded-lg"]') as HTMLElement;
  await user.click(within(row).getByTitle(/редактировать|edit/i));
  return screen.findByRole('dialog');
}

beforeEach(() => {
  vi.clearAllMocks();
  stubGet();
});

describe('HRPositions — матрица прав без кадрового уровня (рулинг N)', () => {
  it('селекта «Уровень доступа HR» нет, галочки — только вне hr.*', async () => {
    const user = userEvent.setup();
    renderWithProviders(<HRPositions />, { route: '/hr/positions' });
    const dialog = await openEditDialog(user);

    expect(within(dialog).queryByText(/Уровень доступа HR/)).not.toBeInTheDocument();
    expect(within(dialog).queryByText(/Без HR-доступа/)).not.toBeInTheDocument();
    expect(await within(dialog).findByRole('checkbox', { name: /Отметка об оплате аванса/ })).toBeChecked();
    expect(within(dialog).queryByRole('checkbox', { name: /Просмотр сотрудников/ })).not.toBeInTheDocument();
    expect(within(dialog).getByText(/до их перехода на роли access/)).toBeInTheDocument();
  });

  it('hr_level в запрос не уходит, скрытые hr.* ключи возвращаются нетронутыми', async () => {
    mockedApi.put.mockResolvedValue({ data: {} });
    const user = userEvent.setup();
    renderWithProviders(<HRPositions />, { route: '/hr/positions' });
    const dialog = await openEditDialog(user);

    await user.click(await within(dialog).findByRole('checkbox', { name: /Отметка об оплате аванса/ }));
    await user.click(within(dialog).getByRole('button', { name: /сохранить|save/i }));

    await waitFor(() => expect(mockedApi.put).toHaveBeenCalled());
    const payload = mockedApi.put.mock.calls[0][1] as { permissions: Record<string, unknown> };
    expect(payload.permissions).toEqual({ permissions: ['hr.employees.view'] });
    expect(payload.permissions).not.toHaveProperty('hr_level');
  });

  it('должность без прав и без галочек не трогает колонку (permissions: null)', async () => {
    stubGet({ ...POSITION, permissions: null });
    mockedApi.put.mockResolvedValue({ data: {} });
    const user = userEvent.setup();
    renderWithProviders(<HRPositions />, { route: '/hr/positions' });
    const dialog = await openEditDialog(user);

    await user.click(within(dialog).getByRole('button', { name: /сохранить|save/i }));

    await waitFor(() => expect(mockedApi.put).toHaveBeenCalled());
    expect((mockedApi.put.mock.calls[0][1] as { permissions: unknown }).permissions).toBeNull();
  });
});
