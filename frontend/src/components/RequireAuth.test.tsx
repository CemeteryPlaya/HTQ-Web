/**
 * Гейт маршрута по модулю и уровню (§6 B4 спеки стадии 2).
 *
 * Это UX-рубеж, а не защита: настоящий отказ выдаёт бэкенд на каждом вызове
 * API. Поэтому проверяется не «нельзя пройти», а «не показываем того, чего
 * сервер всё равно не даст» — и, отдельно, что ожидание прав не превращается
 * в отказ: иначе каждый заход на защищённую страницу выбрасывал бы на профиль
 * раньше, чем приедет ответ.
 */
import { StrictMode } from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { AccessLevel } from '@/lib/auth/permissions';

import { resetSessionRestoreForTests } from '@/lib/auth/sessionRestore';

import RequireAuth from './RequireAuth';

const activeProfile = {
  id: '1',
  username: 'volkov.d',
  roles: ['user'],
  must_change_password: false,
};

const useActiveProfile = vi.fn();
const permissionsSpy = vi.fn();
const refreshSpy = vi.fn();

// Обмен refresh → access — единственная функция интерцептора; здесь она
// подменена, чтобы тест видел, сколько раз RequireAuth её позвал.
vi.mock('@/api/client', () => ({
  default: {},
  refreshAccessToken: () => refreshSpy(),
}));

vi.mock('@/hooks/useActiveProfile', () => ({
  useActiveProfile: () => useActiveProfile(),
}));

vi.mock('@/hooks/usePermissions', () => ({
  usePermissions: () => permissionsSpy(),
  default: () => permissionsSpy(),
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

/**
 * Хост страницы. RequireAuth уводит с голого домена на экран выбора компании
 * (блок I.2), а jsdom по умолчанию стоит на голом `localhost:3000` — поэтому
 * тесты гейта по модулю живут на поддомене компании, как и настоящие страницы
 * за гейтом. Без этого каждый из них проверял бы редирект на выбор компании,
 * а не то, что заявлено в названии.
 */
const stubHost = (host: string) => {
  vi.stubGlobal('location', {
    host, hostname: host.split(':')[0], pathname: '/gated', search: '', hash: '', protocol: 'http:',
  });
};

afterEach(() => {
  vi.unstubAllGlobals();
});

beforeEach(() => {
  stubHost('htq.localhost:3000');
  useActiveProfile.mockReturnValue({
    activeProfile,
    isLoading: false,
    error: null,
    isLoggedIn: true,
    clearAuthStorage: vi.fn(),
    refetch: vi.fn(),
  });
  permissionsSpy.mockReturnValue(permissionsOf({ hr: 'write' }));
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
    permissionsSpy.mockReturnValue(permissionsOf({}, true));

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
    permissionsSpy.mockReturnValue({ ...permissionsOf({}), isError: true });

    renderGate({ module: 'hr', level: 'read' });

    // Не редирект на профиль: человеку показывают причину и дают повторить.
    expect(screen.queryByText('профиль')).not.toBeInTheDocument();
    expect(screen.getByText('auth.errors.permissionsUnavailable')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'common.retry' })).toBeInTheDocument();
  });

  it('доступ при этом всё равно закрыт — отказ в закрытую', () => {
    permissionsSpy.mockReturnValue({ ...permissionsOf({ hr: 'admin' }), isError: true });

    renderGate({ module: 'hr', level: 'read' });

    expect(screen.queryByText('содержимое страницы')).not.toBeInTheDocument();
  });
});

describe('RequireAuth — голый домен (блок I.2)', () => {
  // Маршруты приложения передают `page`, а с ним RequireAuth спрашивает
  // `pageHidden` — здесь ни одна страница не закрыта.
  beforeEach(() => {
    permissionsSpy.mockReturnValue({ ...permissionsOf({ hr: 'write' }), pageHidden: () => false });
  });

  const PickerProbe = () => {
    const location = useLocation();
    const from = (location.state as { from?: { pathname: string } } | null)?.from;
    return <div>выбор компании; шёл на {from?.pathname ?? '—'}</div>;
  };

  const renderAt = (path: string) =>
    render(
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route
            path="/gated"
            element={
              <RequireAuth page="/gated">
                <div>содержимое страницы</div>
              </RequireAuth>
            }
          />
          <Route
            path="/companies/choose"
            element={
              // Как в App.tsx: `page` — путь своего маршрута.
              <RequireAuth page="/companies/choose">
                <PickerProbe />
              </RequireAuth>
            }
          />
          <Route path="/login" element={<div>страница входа</div>} />
        </Routes>
      </MemoryRouter>,
    );

  it('уводит на экран выбора компании и помнит, куда человек шёл', () => {
    stubHost('localhost:3000');

    renderAt('/gated');

    expect(screen.queryByText('содержимое страницы')).not.toBeInTheDocument();
    expect(screen.getByText('выбор компании; шёл на /gated')).toBeInTheDocument();
  });

  it('сам экран выбора на голом домене не уводит по кругу', () => {
    stubHost('htq.group');

    renderAt('/companies/choose');

    expect(screen.getByText('выбор компании; шёл на —')).toBeInTheDocument();
  });

  it('неаутентифицированного ведёт на вход, а не на выбор компании', () => {
    stubHost('htq.group');
    useActiveProfile.mockReturnValue({
      activeProfile: null,
      isLoading: false,
      error: null,
      isLoggedIn: false,
      clearAuthStorage: vi.fn(),
      refetch: vi.fn(),
    });

    renderAt('/gated');

    expect(screen.getByText('страница входа')).toBeInTheDocument();
  });
});

/**
 * Переезд сессии на поддомен компании (блок I.2, A1). Вошёл на голом домене —
 * на поддомене access-токена нет, но refresh-cookie родительского домена
 * видна. RequireAuth обязан обменять её ДО редиректа на /login, иначе человек
 * входит второй раз в каждой компании и теряет глубокую ссылку.
 */
describe('RequireAuth — восстановление сессии по refresh-cookie', () => {
  let loggedIn = false;

  const clearRefreshCookie = () => {
    document.cookie = 'refresh=; Max-Age=0; Path=/';
  };

  beforeEach(() => {
    loggedIn = false;
    resetSessionRestoreForTests();
    refreshSpy.mockReset();
    window.localStorage.clear();
    // На поддомене только refresh-cookie: access-токена нет ни в
    // localStorage, ни в cookie этого origin.
    document.cookie = 'refresh=refresh-from-parent-domain; Path=/';
    permissionsSpy.mockReturnValue({ ...permissionsOf({ hr: 'write' }), pageHidden: () => false });
    // Как настоящий useActiveProfile: «вошёл» — это наличие access-токена,
    // который появляется только после успешного обмена.
    useActiveProfile.mockImplementation(() => ({
      activeProfile: loggedIn ? activeProfile : null,
      isLoading: false,
      error: null,
      isLoggedIn: loggedIn,
      clearAuthStorage: vi.fn(),
      refetch: vi.fn(),
    }));
  });

  afterEach(() => {
    clearRefreshCookie();
    useActiveProfile.mockReset();
  });

  const renderDeepLink = () =>
    render(
      <StrictMode>
        <MemoryRouter initialEntries={['/gated']}>
          <Routes>
            <Route
              path="/gated"
              element={
                <RequireAuth page="/gated">
                  <div>содержимое страницы</div>
                </RequireAuth>
              }
            />
            <Route path="/login" element={<div>страница входа</div>} />
          </Routes>
        </MemoryRouter>
      </StrictMode>,
    );

  it('на поддомене с одной refresh-cookie обменивает её и открывает маршрут, а не /login', async () => {
    stubHost('htq.localhost:3000');
    refreshSpy.mockImplementation(async () => {
      loggedIn = true;
      return 'fresh-access';
    });

    renderDeepLink();

    expect(await screen.findByText('содержимое страницы')).toBeInTheDocument();
    expect(screen.queryByText('страница входа')).not.toBeInTheDocument();
  });

  it('неудачный обмен ведёт на /login', async () => {
    stubHost('htq.localhost:3000');
    refreshSpy.mockRejectedValue(new Error('refresh expired'));

    renderDeepLink();

    expect(await screen.findByText('страница входа')).toBeInTheDocument();
    expect(screen.queryByText('содержимое страницы')).not.toBeInTheDocument();
  });

  it('обмен вызывается один раз на загрузку — и в StrictMode, и при повторном заходе после неудачи', async () => {
    stubHost('htq.localhost:3000');
    refreshSpy.mockRejectedValue(new Error('refresh expired'));

    renderDeepLink();
    expect(await screen.findByText('страница входа')).toBeInTheDocument();

    // Повторный заход на защищённый маршрут в той же загрузке страницы:
    // обмен не повторяется, цикла «обмен → /login → обмен» нет.
    cleanup();
    renderDeepLink();
    expect(await screen.findByText('страница входа')).toBeInTheDocument();

    expect(refreshSpy).toHaveBeenCalledTimes(1);
  });

  it('без refresh-cookie обмена нет — сразу вход', () => {
    stubHost('htq.localhost:3000');
    clearRefreshCookie();

    renderDeepLink();

    expect(screen.getByText('страница входа')).toBeInTheDocument();
    expect(refreshSpy).not.toHaveBeenCalled();
  });
});
