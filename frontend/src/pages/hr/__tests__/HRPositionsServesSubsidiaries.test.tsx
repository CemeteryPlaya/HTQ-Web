import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { renderWithProviders } from '@/test/renderWithProviders';

/**
 * «Обслуживает дочерние компании» в карточке должности (блок C, задача 3).
 *
 * Признак сам по себе прав не выдаёт — членство в дочерней компании заводится
 * отдельно (решения заказчика 1 и 3), поэтому рядом с включённым
 * переключателем обязан стоять текст об этом. Решение 5 добавляет
 * предпросмотр — какие роли должности реально поедут в дочерние компании.
 *
 * HRPositions.tsx не ходит через `@/api/hr` — все запросы идут через
 * `@/api/client` напрямую (см. HRPositions.test.tsx), а предпросмотр — через
 * `@/api/access` и `@/api/companies`, которые сами оборачивают тот же
 * `@/api/client`. Мокаем поэтому только `@/api/client`, тем же приёмом, что
 * и `HRPositionsExternalHierarchy.test.tsx`.
 */

vi.mock('@/components/hr/HRLayout', () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

// Права — usePermissions (задача 10 блока I): правка должностей под `hr:admin`.
const access = { hr: 'admin' as 'none' | 'read' | 'write' | 'admin' };
const ORDER = ['none', 'read', 'write', 'admin'];
vi.mock('@/hooks/usePermissions', () => ({
  usePermissions: () => ({
    // `company: null` — как отдавал НЕмокнутый хук до задачи 10 (ответ
    // `/access/v1/me` здесь подменялся пустым `data: []` через api.get).
    company: null,
    level: (m: string) => (m === 'hr' ? access.hr : 'none'),
    atLeast: (m: string, req: string) =>
      ORDER.indexOf(m === 'hr' ? access.hr : 'none') >= ORDER.indexOf(req),
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

const POSITIONS = [
  {
    id: 1,
    title: 'Генеральный директор',
    department_id: 1,
    department_name: 'Руководство',
    weight: 10,
    level: 1,
    grade: 10,
    is_system: false,
    is_manager: true,
    external_hierarchy: 'inherit',
    serves_subsidiaries: true,
    permissions: null,
  },
  {
    id: 2,
    title: 'Инженер',
    department_id: 1,
    department_name: 'Руководство',
    weight: 20,
    level: 1,
    grade: 5,
    is_system: false,
    is_manager: false,
    external_hierarchy: 'inherit',
    serves_subsidiaries: false,
    permissions: null,
  },
];

const DEPARTMENTS = [{ id: 1, name: 'Руководство' }];

const CATALOG = { hr_levels: [], permissions: [], level_presets: {} };

const PREVIEW_ROLES = [{ role_id: 9, code: 'budget-read', title: 'Чтение смет' }];

/** Ответы GET по URL — так же, как их зовёт страница (см. HRPositions.test.tsx). */
function stubGet(overrides: Record<string, unknown> = {}) {
  mockedApi.get.mockImplementation(((url: string) => {
    for (const [fragment, data] of Object.entries(overrides)) {
      if (url.includes(fragment)) return Promise.resolve({ data });
    }
    if (url.includes('next-weight')) {
      return Promise.resolve({
        data: { level_number: 1, weight: 20, weight_from: 0, weight_to: 99 },
      });
    }
    if (url.includes('positions/levels')) return Promise.resolve({ data: LEVELS });
    if (url.includes('permissions-catalog')) return Promise.resolve({ data: CATALOG });
    if (url.includes('departments')) return Promise.resolve({ data: DEPARTMENTS });
    if (url.includes('positions')) return Promise.resolve({ data: POSITIONS });
    return Promise.resolve({ data: [] });
  }) as never);
}

beforeEach(() => {
  vi.clearAllMocks();
  access.hr = 'admin';
  stubGet();
});

/** Открыть диалог редактирования уже существующей должности — через
 *  карандаш на карточке, найденной по названию. */
async function openEditDialog(user: ReturnType<typeof userEvent.setup>, title: string) {
  const card = await screen.findByText(title);
  const row = card.closest('div[class*="rounded-lg"]') as HTMLElement;
  await user.click(within(row).getByTitle(/редактировать|edit/i));
  return screen.findByRole('dialog');
}

/** Открыть диалог ролей должности — ключ на той же карточке. */
async function openRolesDialog(user: ReturnType<typeof userEvent.setup>, title: string) {
  const card = await screen.findByText(title);
  const row = card.closest('div[class*="rounded-lg"]') as HTMLElement;
  await user.click(within(row).getByTitle(/роли/i));
  return screen.findByRole('dialog');
}

describe('HRPositions — обслуживание дочерних компаний', () => {
  it('переключатель отражает значение должности', async () => {
    const user = userEvent.setup();
    renderWithProviders(<HRPositions />, { route: '/hr/positions' });
    const dialog = await openEditDialog(user, 'Генеральный директор');

    expect(
      within(dialog).getByRole('switch', { name: /обслуживает дочерние компании/i }),
    ).toBeChecked();
  });

  it('включение отправляет serves_subsidiaries: true при сохранении', async () => {
    mockedApi.put.mockResolvedValue({ data: {} });
    const user = userEvent.setup();
    renderWithProviders(<HRPositions />, { route: '/hr/positions' });
    const dialog = await openEditDialog(user, 'Инженер');

    expect(
      within(dialog).getByRole('switch', { name: /обслуживает дочерние компании/i }),
    ).not.toBeChecked();
    await user.click(within(dialog).getByRole('switch', { name: /обслуживает дочерние компании/i }));
    await user.click(within(dialog).getByRole('button', { name: /сохранить|save/i }));

    await waitFor(() => expect(mockedApi.put).toHaveBeenCalled());
    expect(mockedApi.put.mock.calls[0][1]).toMatchObject({ serves_subsidiaries: true });
  });

  it('при включённом переключателе виден текст про членство', async () => {
    const user = userEvent.setup();
    renderWithProviders(<HRPositions />, { route: '/hr/positions' });
    const dialog = await openEditDialog(user, 'Генеральный директор');

    expect(within(dialog).getByText(/членство/i)).toBeInTheDocument();
  });

  it('при включённом переключателе виден предпросмотр с названиями ролей должности', async () => {
    stubGet({ 'positions/1/roles': PREVIEW_ROLES });
    const user = userEvent.setup();
    renderWithProviders(<HRPositions />, { route: '/hr/positions' });
    const dialog = await openEditDialog(user, 'Генеральный директор');

    expect(await within(dialog).findByText(/Чтение смет/)).toBeInTheDocument();
  });

  it('в диалоге ролей предупреждение видно у обслуживающей должности и не видно у обычной', async () => {
    const user = userEvent.setup();
    renderWithProviders(<HRPositions />, { route: '/hr/positions' });

    const servingDialog = await openRolesDialog(user, 'Генеральный директор');
    expect(
      within(servingDialog).getByText(/обслуживает дочерние компании/i),
    ).toBeInTheDocument();
    await user.click(within(servingDialog).getByRole('button', { name: /отмена|cancel/i }));

    const ordinaryDialog = await openRolesDialog(user, 'Инженер');
    expect(
      within(ordinaryDialog).queryByText(/обслуживает дочерние компании/i),
    ).not.toBeInTheDocument();
  });
});
