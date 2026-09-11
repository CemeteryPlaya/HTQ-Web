/**
 * Гейт маршрута по модулю и уровню (§6 B4 спеки стадии 2).
 *
 * Это UX-рубеж, а не защита: настоящий отказ выдаёт бэкенд на каждом вызове
 * API. Поэтому проверяется не «нельзя пройти», а «не показываем того, чего
 * сервер всё равно не даст» — и, отдельно, что ожидание прав не превращается
 * в отказ: иначе каждый заход на защищённую страницу выбрасывал бы на профиль
 * раньше, чем приедет ответ.
 */
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { AccessLevel } from '@/lib/auth/permissions';

import RequireAuth from './RequireAuth';

const activeProfile = {
  id: '1',
  username: 'volkov.d',
  roles: ['user'],
  must_change_password: false,
};

const useActiveProfile = vi.fn();
const usePermissions = vi.fn();

vi.mock('@/hooks/useActiveProfile', () => ({
  useActiveProfile: () => useActiveProfile(),
}));

vi.mock('@/hooks/usePermissions', () => ({
  usePermissions: () => usePermissions(),
  default: () => usePermissions(),
}));

// Частичный мок: src/i18n.js тянет initReactI18next, поэтому полная подмена
// модуля роняет импорт раньше самого теста.
vi.mock('react-i18next', async (importOriginal) => ({
  ...(await importOriginal<typeof import('react-i18next')>()),
  useTranslation: () => ({ t: (key: string) => key }),
}));

const permissionsOf = (levels: Record<string, AccessLevel>, isLoading = false) => ({
  company: 'hi-tech-qazaqstan',
  level: (module: string) => levels[module] ?? 'none',
  atLeast: (module: string, required: AccessLevel) => {
    const order = ['none', 'read', 'write', 'admin'];
    return order.indexOf(levels[module] ?? 'none') >= order.indexOf(required);
  },
  scope: () => null,
  subordinateCompanies: [],
  isLoading,
  isError: false,
  refetch: vi.fn(),
});

const renderGate = (requires?: { module: string; level: AccessLevel }) =>
  render(
    <MemoryRouter initialEntries={['/gated']}>
      <Routes>
        <Route
          path="/gated"
          element={
            <RequireAuth requires={requires}>
              <div>содержимое страницы</div>
            </RequireAuth>
          }
        />
        <Route path="/myprofile" element={<div>профиль</div>} />
      </Routes>
    </MemoryRouter>,
  );

beforeEach(() => {
  useActiveProfile.mockReturnValue({
    activeProfile,
    isLoading: false,
    error: null,
    isLoggedIn: true,
    clearAuthStorage: vi.fn(),
    refetch: vi.fn(),
  });
  usePermissions.mockReturnValue(permissionsOf({ hr: 'write' }));
});

describe('RequireAuth — гейт по модулю и уровню', () => {
  it('пускает, когда уровень не ниже требуемого', () => {
    renderGate({ module: 'hr', level: 'read' });

    expect(screen.getByText('содержимое страницы')).toBeInTheDocument();
  });

  it('отправляет на профиль, когда уровень ниже требуемого', () => {
    renderGate({ module: 'hr', level: 'admin' });

    expect(screen.getByText('профиль')).toBeInTheDocument();
    expect(screen.queryByText('содержимое страницы')).not.toBeInTheDocument();
  });

  it('отправляет на профиль, когда модуля нет в правах вовсе', () => {
    renderGate({ module: 'contracts', level: 'read' });

    expect(screen.getByText('профиль')).toBeInTheDocument();
  });

  it('пускает на маршрут без гейта модуля', () => {
    renderGate(undefined);

    expect(screen.getByText('содержимое страницы')).toBeInTheDocument();
  });

  it('ждёт, а не отвергает, пока права ещё грузятся', () => {
    usePermissions.mockReturnValue(permissionsOf({}, true));

    renderGate({ module: 'hr', level: 'read' });

    // Ни содержимого (мы ещё не знаем прав), ни редиректа (иначе каждый
    // заход выбрасывал бы на профиль раньше ответа сервера).
    expect(screen.queryByText('содержимое страницы')).not.toBeInTheDocument();
    expect(screen.queryByText('профиль')).not.toBeInTheDocument();
  });

  /**
   * Неудачный запрос прав и отсутствие прав дают ОДНУ И ТУ ЖЕ пустую карту.
   * Пока их не разделили, недоступная ручка выглядела как «вам не выдали
   * роль»: закрывалось всё, включая администрирование, и причину искали в
   * ролях. Ровно так и вышло на первой живой проверке стадии 2.
   */
  it('различает «прав нет» и «права не загрузились»', () => {
    usePermissions.mockReturnValue({ ...permissionsOf({}), isError: true });

    renderGate({ module: 'hr', level: 'read' });

    // Не редирект на профиль: человеку показывают причину и дают повторить.
    expect(screen.queryByText('профиль')).not.toBeInTheDocument();
    expect(screen.getByText('auth.errors.permissionsUnavailable')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'common.retry' })).toBeInTheDocument();
  });

  it('доступ при этом всё равно закрыт — отказ в закрытую', () => {
    usePermissions.mockReturnValue({ ...permissionsOf({ hr: 'admin' }), isError: true });

    renderGate({ module: 'hr', level: 'read' });

    expect(screen.queryByText('содержимое страницы')).not.toBeInTheDocument();
  });
});
