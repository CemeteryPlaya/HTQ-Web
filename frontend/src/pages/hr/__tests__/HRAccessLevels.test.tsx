import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';

import { renderWithProviders } from '@/test/renderWithProviders';

/**
 * Раунд правок 1 задачи 8 блока I.
 *
 * `HRAccessLevels` показывает свой собственный уровень через `useHRLevel`
 * (задача 8 сняла отдельный запрос к `hr/v1/employees/hr-level/`). Первая
 * версия правки открывала блок «Ваш уровень доступа» условием
 * `!hrLevel.isLoading` — при сбое запроса прав (`isError: true`,
 * `level: null`, тот же результат, что и у штатного «доступа нет») блок всё
 * равно рендерился, и бейдж уверенно заявлял «Нет доступа», хотя причина —
 * не отсутствие прав, а неудавшаяся загрузка. Раньше, на старой сетевой
 * ручке, сбой запроса означал `data === undefined`, и блок молча не
 * показывался вовсе.
 *
 * Здесь проверяется именно это различие: «не загрузилось» не должно
 * визуально совпадать с «нет доступа». Осложнение: строка «Нет доступа»
 * встречается на странице ДВАЖДЫ независимо от состояния — статичная
 * легенда «🔒 Остальные сотрудники → Нет доступа» рендерится всегда, — так
 * что проверка идёт по количеству вхождений, а не по одному факту наличия.
 */

vi.mock('@/components/hr/HRLayout', () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

const hrLevel: {
  level: 'junior' | 'middle' | 'senior' | 'lead' | null;
  isLoading: boolean;
  isError: boolean;
  canReadAll: boolean;
  canWriteBasic: boolean;
  canCreateEmployee: boolean;
  canTransferEmployee: boolean;
  canDeleteEmployee: boolean;
  canListUserOptions: boolean;
  canManageUserOptions: boolean;
} = {
  level: null,
  isLoading: false,
  isError: false,
  canReadAll: false,
  canWriteBasic: false,
  canCreateEmployee: false,
  canTransferEmployee: false,
  canDeleteEmployee: false,
  canListUserOptions: false,
  canManageUserOptions: false,
};

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
import HRAccessLevels from '../HRAccessLevels';

const mockedApi = vi.mocked(api, true);

beforeEach(() => {
  vi.clearAllMocks();
  hrLevel.level = null;
  hrLevel.isLoading = false;
  hrLevel.isError = false;
  mockedApi.get.mockImplementation((() => Promise.resolve({ data: { items: [], total: 0 } })) as never);
});

describe('HRAccessLevels — блок «Ваш уровень доступа»', () => {
  it('при ошибке загрузки прав НЕ утверждает, что доступа нет', async () => {
    hrLevel.isLoading = false;
    hrLevel.isError = true;
    hrLevel.level = null;

    renderWithProviders(<HRAccessLevels />);
    await waitFor(() => expect(mockedApi.get).toHaveBeenCalled());

    // Заголовок «Ваш уровень доступа:» — маркер того, что блок вообще
    // отрисован. При ошибке он не должен появиться.
    expect(screen.queryByText('Ваш уровень доступа:')).not.toBeInTheDocument();
    // «Нет доступа» встречается в статичной легенде независимо от состояния
    // — при ошибке она должна остаться ЕДИНСТВЕННЫМ вхождением, а не
    // задвоиться бейджем блока (которого при ошибке быть не должно).
    expect(screen.getAllByText('Нет доступа')).toHaveLength(1);
  });

  it('без ошибки, при штатном отсутствии доступа, блок показывает «Нет доступа»', async () => {
    // Контрольный кейс: подтверждает, что правка не спрятала блок вообще
    // всегда, а только на время загрузки/при ошибке — сам штатный «доступа
    // нет» по-прежнему виден.
    hrLevel.isLoading = false;
    hrLevel.isError = false;
    hrLevel.level = null;

    renderWithProviders(<HRAccessLevels />);
    await waitFor(() => expect(mockedApi.get).toHaveBeenCalled());

    expect(await screen.findByText('Ваш уровень доступа:')).toBeInTheDocument();
    // Легенда (всегда) + бейдж блока (появился) = два вхождения.
    expect(screen.getAllByText('Нет доступа')).toHaveLength(2);
  });

  it('пока права ещё грузятся, блок тоже не показывается', async () => {
    hrLevel.isLoading = true;
    hrLevel.isError = false;
    hrLevel.level = null;

    renderWithProviders(<HRAccessLevels />);
    await waitFor(() => expect(mockedApi.get).toHaveBeenCalled());

    expect(screen.queryByText('Ваш уровень доступа:')).not.toBeInTheDocument();
    expect(screen.getAllByText('Нет доступа')).toHaveLength(1);
  });
});
