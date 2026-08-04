import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { renderWithProviders } from '@/test/renderWithProviders';

// ── моки ───────────────────────────────────────────────────────────────────
//
// HRLayout тянет Header/Footer со всем окружением приложения (профиль, роуты,
// сервис-реестр) — к предмету теста это отношения не имеет, поэтому сквозной
// враппер. useHRLevel мокаем, чтобы управлять правами (isSenior) явно, а не
// через ответ /employees/hr-level/.

vi.mock('@/components/hr/HRLayout', () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

const hrLevel = { isSenior: true };
vi.mock('@/hooks/useHRLevel', () => ({
  useHRLevel: () => hrLevel,
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
  { id: 2, level_number: 2, weight_from: 100, weight_to: 299, label: 'Директора', color: '#3b82f6' },
];

const POSITIONS = [
  {
    id: 7,
    title: 'Главный инженер',
    department_id: 1,
    department_name: 'ИТ',
    weight: 50,
    level: 1,
    grade: 5,
    is_system: false,
    permissions: null,
  },
];

const DEPARTMENTS = [{ id: 1, name: 'ИТ' }];

const CATALOG = { hr_levels: [], permissions: [], level_presets: {} };

/** Ответы GET по URL — так же, как их зовёт страница. */
function stubGet(overrides: Record<string, unknown> = {}) {
  mockedApi.get.mockImplementation(((url: string) => {
    for (const [fragment, data] of Object.entries(overrides)) {
      if (url.includes(fragment)) return Promise.resolve({ data });
    }
    if (url.includes('next-weight')) {
      return Promise.resolve({
        data: { level_number: 2, weight: 200, weight_from: 100, weight_to: 299 },
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
  hrLevel.isSenior = true;
  stubGet();
});

/** Открыть диалог редактирования уже существующей должности.
 *  Через карандаш на карточке — так не нужно трогать Radix-селекты
 *  названия/отдела, они уже заполнены. */
async function openEditDialog(user: ReturnType<typeof userEvent.setup>) {
  const card = await screen.findByText('Главный инженер');
  const row = card.closest('div[class*="rounded-lg"]') as HTMLElement;
  await user.click(within(row).getByTitle(/редактировать|edit/i));
  return screen.findByRole('dialog');
}

describe('HRPositions — вкладки', () => {
  it('показывает вкладку «Уровни» пользователю с правами', async () => {
    renderWithProviders(<HRPositions />, { route: '/hr/positions' });
    expect(await screen.findByRole('tab', { name: /уровни/i })).toBeInTheDocument();
  });

  it('прячет вкладки от пользователя без прав на правку', async () => {
    hrLevel.isSenior = false;
    renderWithProviders(<HRPositions />, { route: '/hr/positions' });
    await screen.findByText('Главный инженер');
    expect(screen.queryByRole('tab', { name: /уровни/i })).not.toBeInTheDocument();
  });

  it('открывает справочник уровней по ?tab=levels', async () => {
    renderWithProviders(<HRPositions />, { route: '/hr/positions?tab=levels' });
    // Подсказка под формой создания есть только в панели уровней.
    expect(await screen.findByText(/чем меньше номер/i)).toBeInTheDocument();
  });
});

describe('HRPositions — вес спрятан от HR', () => {
  it('не показывает вес на карточке должности', async () => {
    renderWithProviders(<HRPositions />, { route: '/hr/positions' });
    const card = await screen.findByText('Главный инженер');
    const row = card.closest('div[class*="rounded-lg"]') as HTMLElement;
    // 50 — вес должности; на карточке должен остаться только грейд.
    expect(within(row).queryByText('50')).not.toBeInTheDocument();
    expect(within(row).getByText(/грейд 5/i)).toBeInTheDocument();
  });

  it('держит поле «Вес» в свёрнутом блоке «Служебное»', async () => {
    const user = userEvent.setup();
    renderWithProviders(<HRPositions />, { route: '/hr/positions' });
    const dialog = await openEditDialog(user);

    const weight = within(dialog).getByLabelText(/^вес$/i);
    // Само поле в DOM есть (details не удаляет содержимое), но обязано лежать
    // ВНУТРИ <details> — иначе оно снова на виду у кадровика.
    expect(weight.closest('details')).not.toBeNull();
    expect(within(dialog).getByText(/служебное/i)).toBeInTheDocument();
  });

  it('блокирует сохранение, если вес вне диапазона выбранного уровня', async () => {
    const user = userEvent.setup();
    renderWithProviders(<HRPositions />, { route: '/hr/positions' });
    const dialog = await openEditDialog(user);

    const weight = within(dialog).getByLabelText(/^вес$/i);
    await user.clear(weight);
    await user.type(weight, '5000');   // L1 — это 0-99

    expect(within(dialog).getByText(/вне диапазона уровня/i)).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: /сохранить|save/i })).toBeDisabled();
  });
});

describe('HRPositions — ошибки сервера', () => {
  it('показывает detail от бэкенда и не закрывает диалог', async () => {
    const user = userEvent.setup();
    mockedApi.put.mockRejectedValue({
      response: { status: 409, data: { detail: 'Weight 100 is already taken' } },
    });

    renderWithProviders(<HRPositions />, { route: '/hr/positions' });
    const dialog = await openEditDialog(user);
    await user.click(within(dialog).getByRole('button', { name: /сохранить|save/i }));

    expect(await within(dialog).findByText(/already taken/i)).toBeInTheDocument();
    // Раньше 409 не показывался вообще; диалог обязан остаться открытым.
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('запрашивает свободный вес при открытии формы создания', async () => {
    const user = userEvent.setup();
    renderWithProviders(<HRPositions />, { route: '/hr/positions' });

    await user.click(await screen.findByRole('button', { name: /создать должность/i }));

    await waitFor(() => {
      expect(mockedApi.get).toHaveBeenCalledWith(
        expect.stringContaining('positions/levels/1/next-weight'),
      );
    });
  });
});
