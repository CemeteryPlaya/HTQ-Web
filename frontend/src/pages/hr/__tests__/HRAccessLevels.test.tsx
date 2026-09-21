import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';

import { renderWithProviders } from '@/test/renderWithProviders';

/**
 * Раунд правок 1 задачи 8 блока I.
 *
 * `HRAccessLevels` показывает свой собственный уровень из `usePermissions`
 * (задача 8 сняла отдельный запрос к `hr/v1/employees/hr-level/`, задача
 * 10 — промежуточный `useHRLevel`). Первая версия правки открывала блок
 * «Ваш уровень доступа» условием `!isLoading` — при сбое запроса прав
 * (`isError: true`, модуля `hr` нет в карте — тот же результат, что и у
 * штатного «доступа нет») блок всё
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

// Задача 10 блока I: экран читает `usePermissions` напрямую. `hr: 'none'` —
// штатное «доступа нет» (модуля нет в карте), `isError` — «не загрузилось».
const access: {
  hr: 'none' | 'read' | 'write' | 'admin';
  isLoading: boolean;
  isError: boolean;
} = {
  hr: 'none',
  isLoading: false,
  isError: false,
};

vi.mock('@/hooks/usePermissions', () => ({
  usePermissions: () => ({
    company: 'demo',
    level: (m: string) => (m === 'hr' ? access.hr : 'none'),
    atLeast: (m: string, req: string) => {
      const order = ['none', 'read', 'write', 'admin'];
      return order.indexOf(m === 'hr' ? access.hr : 'none') >= order.indexOf(req);
    },
    scope: () => null,
    depth: () => [],
    can: () => false,
    pageHidden: () => false,
    subordinateCompanies: [],
    inheritedFrom: [],
    isLoading: access.isLoading,
    isError: access.isError,
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
import HRAccessLevels from '../HRAccessLevels';

const mockedApi = vi.mocked(api, true);

beforeEach(() => {
  vi.clearAllMocks();
  access.hr = 'none';
  access.isLoading = false;
  access.isError = false;
  mockedApi.get.mockImplementation((() => Promise.resolve({ data: { items: [], total: 0 } })) as never);
});

describe('HRAccessLevels — блок «Ваш уровень доступа»', () => {
  it('при ошибке загрузки прав НЕ утверждает, что доступа нет', async () => {
    access.isLoading = false;
    access.isError = true;
    access.hr = 'none';

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
    access.isLoading = false;
    access.isError = false;
    access.hr = 'none';

    renderWithProviders(<HRAccessLevels />);
    await waitFor(() => expect(mockedApi.get).toHaveBeenCalled());

    expect(await screen.findByText('Ваш уровень доступа:')).toBeInTheDocument();
    // Легенда (всегда) + бейдж блока (появился) = два вхождения.
    expect(screen.getAllByText('Нет доступа')).toHaveLength(2);
  });

  it('пока права ещё грузятся, блок тоже не показывается', async () => {
    access.isLoading = true;
    access.isError = false;
    access.hr = 'none';

    renderWithProviders(<HRAccessLevels />);
    await waitFor(() => expect(mockedApi.get).toHaveBeenCalled());

    expect(screen.queryByText('Ваш уровень доступа:')).not.toBeInTheDocument();
    expect(screen.getAllByText('Нет доступа')).toHaveLength(1);
  });
});
