import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { renderWithProviders } from '@/test/renderWithProviders';

// ── моки ───────────────────────────────────────────────────────────────────
//
// HRLayout тянет Header/Footer со всем окружением приложения — к предмету
// теста отношения не имеет (тот же приём, что в HRPositions.test.tsx).
// useHRLevel мокаем, чтобы управлять правами явно.

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
import HRDepartments from '../HRDepartments';

const mockedApi = vi.mocked(api, true);

const DEPARTMENTS = [
  {
    id: 1,
    name: 'ИТ-отдел',
    description: '',
    index: 1,
    created_at: '2026-01-01',
    positions: [{ id: 10, title: 'Инженер', department_id: 1 }],
  },
  {
    id: 2,
    name: 'Финансы',
    description: '',
    index: 2,
    created_at: '2026-01-01',
    positions: [],
  },
];

beforeEach(() => {
  vi.clearAllMocks();
  hrLevel.isSenior = true;
  mockedApi.get.mockImplementation((() => Promise.resolve({ data: DEPARTMENTS })) as never);
});

/** Строка-переключатель отдела: role="button" с явным aria-label. */
const deptRow = (name: string) =>
  screen.getByRole('button', { name: new RegExp(`Должности отдела ${name}`) });

describe('HRDepartments — раскрытие отдела', () => {
  it('по умолчанию отдел свёрнут: aria-expanded=false, должностей не видно', async () => {
    renderWithProviders(<HRDepartments />);
    await waitFor(() => expect(deptRow('ИТ-отдел')).toBeInTheDocument());

    expect(deptRow('ИТ-отдел')).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('Инженер')).not.toBeInTheDocument();
  });

  it('клик по СТРОКЕ (не по шеврону) раскрывает список должностей', async () => {
    const user = userEvent.setup();
    renderWithProviders(<HRDepartments />);
    await waitFor(() => expect(deptRow('ИТ-отдел')).toBeInTheDocument());

    await user.click(deptRow('ИТ-отдел'));

    expect(deptRow('ИТ-отдел')).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('Инженер')).toBeInTheDocument();
  });

  it('Enter на сфокусированной строке раскрывает карточку', async () => {
    const user = userEvent.setup();
    renderWithProviders(<HRDepartments />);
    await waitFor(() => expect(deptRow('ИТ-отдел')).toBeInTheDocument());

    deptRow('ИТ-отдел').focus();
    await user.keyboard('{Enter}');

    expect(deptRow('ИТ-отдел')).toHaveAttribute('aria-expanded', 'true');
  });

  it('отдел без должностей после раскрытия показывает «Нет должностей», а не пустоту', async () => {
    const user = userEvent.setup();
    renderWithProviders(<HRDepartments />);
    await waitFor(() => expect(deptRow('Финансы')).toBeInTheDocument());

    await user.click(deptRow('Финансы'));

    expect(deptRow('Финансы')).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText(/Нет должностей/)).toBeInTheDocument();
  });

  it('в свёрнутом виде бейдж сообщает, что должностей нет — раскрывать нечего', async () => {
    renderWithProviders(<HRDepartments />);
    await waitFor(() => expect(deptRow('Финансы')).toBeInTheDocument());

    expect(within(deptRow('Финансы')).getByText('нет должностей')).toBeInTheDocument();
    expect(within(deptRow('ИТ-отдел')).getByText('1 должностей')).toBeInTheDocument();
  });

  it('клик по кнопке действия НЕ сворачивает карточку (stopPropagation)', async () => {
    const user = userEvent.setup();
    // Отменённый confirm: handleDeleteDept выходит сразу, диалогов не
    // открывается — остаётся ровно то, что проверяем, всплытие клика.
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);
    renderWithProviders(<HRDepartments />);
    await waitFor(() => expect(deptRow('ИТ-отдел')).toBeInTheDocument());

    // Раскрыли...
    await user.click(deptRow('ИТ-отдел'));
    expect(deptRow('ИТ-отдел')).toHaveAttribute('aria-expanded', 'true');

    // ...и жмём «Удалить» внутри той же строки: карточка должна остаться
    // раскрытой, иначе кнопки действий воевали бы с переключателем.
    await user.click(within(deptRow('ИТ-отдел')).getByTitle('Удалить'));

    expect(confirmSpy).toHaveBeenCalled();
    expect(deptRow('ИТ-отдел')).toHaveAttribute('aria-expanded', 'true');
    confirmSpy.mockRestore();
  });
});
