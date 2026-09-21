import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { renderWithProviders } from '@/test/renderWithProviders';

/**
 * Внешняя иерархия в карточке должности.
 *
 * Проверяется то, что отличает этот блок формы от остальных полей: участие во
 * внешней иерархии выбирается только у руководящей должности, и рядом стоит
 * подпись о том, что связь означает подчинение, а не передачу прав.
 *
 * HRPositions.tsx не ходит через `@/api/hr` — все запросы идут напрямую через
 * `@/api/client` (см. `HRPositions.test.tsx`), поэтому мокается он, а не
 * несуществующий здесь `@/api/hr`. По той же причине карточка открывается не
 * кликом по кнопке с именем должности (такой кнопки нет — заголовок лежит в
 * `<span>`), а кликом по карандашу редактирования внутри строки должности.
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
    is_manager: false,
    external_hierarchy: 'inherit',
    permissions: null,
  },
];

const DEPARTMENTS = [{ id: 1, name: 'Руководство' }];

const CATALOG = { hr_levels: [], permissions: [], level_presets: {} };

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

/** Открыть диалог редактирования уже существующей должности — через карандаш
 *  на карточке, как это устроено во всех остальных тестах этой страницы. */
async function openEditDialog(user: ReturnType<typeof userEvent.setup>) {
  const card = await screen.findByText('Генеральный директор');
  const row = card.closest('div[class*="rounded-lg"]') as HTMLElement;
  await user.click(within(row).getByTitle(/редактировать|edit/i));
  return screen.findByRole('dialog');
}

describe('HRPositions — внешняя иерархия', () => {
  it('участие нельзя выбрать, пока должность не руководящая', async () => {
    const user = userEvent.setup();
    renderWithProviders(<HRPositions />, { route: '/hr/positions' });
    const dialog = await openEditDialog(user);

    expect(within(dialog).getByRole('switch', { name: /Руководящая должность/ })).not.toBeChecked();
    expect(within(dialog).getByRole('combobox', { name: /внешней иерархии/i })).toBeDisabled();
  });

  it('подпись объясняет, что это подчинение, а не передача прав', async () => {
    const user = userEvent.setup();
    renderWithProviders(<HRPositions />, { route: '/hr/positions' });
    const dialog = await openEditDialog(user);

    expect(within(dialog).getByText(/подчинение, а не передач/i)).toBeInTheDocument();
  });

  it('оба поля уходят в PATCH', async () => {
    mockedApi.put.mockResolvedValue({ data: {} });
    const user = userEvent.setup();
    renderWithProviders(<HRPositions />, { route: '/hr/positions' });
    const dialog = await openEditDialog(user);

    await user.click(within(dialog).getByRole('switch', { name: /Руководящая должность/ }));
    await user.click(within(dialog).getByRole('button', { name: /сохранить|save/i }));

    await waitFor(() => expect(mockedApi.put).toHaveBeenCalled());
    expect(mockedApi.put.mock.calls[0][1]).toMatchObject({
      is_manager: true,
      external_hierarchy: 'inherit',
    });
  });
});
