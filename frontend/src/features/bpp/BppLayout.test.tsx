/**
 * Раздел «Закупки и оплаты» (ТЗ §05; задача 7 плана этапа 2 A):
 * - меню по правам — пункт подмодуля с `visible === false` не рисуется, а
 *   его маршрут отвечает «Нет доступа»;
 * - ссылки `/bpp/requests/<id>` и `/bpp/accountable/<id>` из колокольчика и
 *   карточки согласования открывают документ внутри раздела — через ту же
 *   таблицу маршрутов, что и приложение (`/bpp/*`).
 */
import { Suspense } from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

import { protectedRoutes } from '@/app/routing/routeDefinitions';
import { isRoutableUrl } from '@/components/signoff/routable';
import type { Permissions } from '@/hooks/usePermissions';
import type { AccessLevel } from '@/lib/auth/permissions';
import { createTestQueryClient } from '@/test/renderWithProviders';

import { BppLayout } from './BppLayout';
import type { BppGatedModule } from './core/moduleAccess';
import { bppModules } from './modules';

vi.mock('@/components/Header', () => ({ Header: () => null }));
vi.mock('@/components/Footer', () => ({ Footer: () => null }));

vi.mock('@/features/bpp/requests/RequestSignoffView', () => ({
  default: ({ id }: { id: string }) => <div>Заявка {id}</div>,
}));
vi.mock('@/features/bpp/accountable/AccountableSignoffView', () => ({
  default: ({ id }: { id: string }) => <div>Подотчёт {id}</div>,
}));

vi.mock('@/api/signoff', () => ({
  signoffApi: { inbox: vi.fn(() => Promise.resolve({ data: [] })) },
}));

const ORDER: AccessLevel[] = ['none', 'read', 'write', 'admin'];

function permissionsWith(levels: Record<string, AccessLevel>): Permissions {
  const level = (module: string) => levels[module] ?? 'none';
  return {
    company: 'hi-tech-qazaqstan',
    level,
    atLeast: (module, required) => ORDER.indexOf(level(module)) >= ORDER.indexOf(required),
    scope: () => null,
    depth: () => [],
    can: () => false,
    pageHidden: () => false,
    subordinateCompanies: [],
    inheritedFrom: [],
    companyArchived: false,
    isLoading: false,
    isError: false,
    refetch: () => {},
  };
}

const permissions = vi.fn(() => permissionsWith({ bpp: 'read' }));
vi.mock('@/hooks/usePermissions', () => ({ usePermissions: () => permissions() }));

function WhereAmI() {
  return <div data-testid="where">{useLocation().pathname}</div>;
}

function renderSection(route: string, modules?: BppGatedModule[]) {
  return render(
    <QueryClientProvider client={createTestQueryClient()}>
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route path="/bpp/*" element={<BppLayout modules={modules} />} />
        </Routes>
        <WhereAmI />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const Screen = (text: string) => {
  const Component = () => <div>{text}</div>;
  return Component;
};

const FAKE: BppGatedModule[] = [
  {
    key: 'budgets', order: 10,
    menu: { labelKey: 'bpp.test.budgets', labelFallback: 'Бюджеты', path: 'budgets' },
    visible: (p) => p.atLeast('bpp', 'admin'),
    routes: [{ path: 'budgets', element: Screen('Реестр бюджетов') }],
  },
  {
    key: 'plan', order: 40,
    menu: { labelKey: 'bpp.test.plan', labelFallback: 'План закупок', path: 'plan' },
    routes: [{ path: 'plan', element: Screen('Реестр плана') }],
  },
];

describe('BppLayout — меню по правам', () => {
  it('пункт с visible === false не рисуется, без visible — рисуется', () => {
    permissions.mockReturnValue(permissionsWith({ bpp: 'read' }));
    renderSection('/bpp/plan', FAKE);
    expect(screen.queryAllByRole('link', { name: 'Бюджеты' })).toHaveLength(0);
    expect(screen.getAllByRole('link', { name: 'План закупок' }).length).toBeGreaterThan(0);
    expect(screen.getByText('Реестр плана')).toBeInTheDocument();
  });

  it('маршрут скрытого подмодуля отвечает «Нет доступа», а не экраном', () => {
    permissions.mockReturnValue(permissionsWith({ bpp: 'read' }));
    renderSection('/bpp/budgets', FAKE);
    expect(screen.getByText('Нет доступа')).toBeInTheDocument();
    expect(screen.queryByText('Реестр бюджетов')).not.toBeInTheDocument();
  });

  it('с правом — и пункт, и экран', () => {
    permissions.mockReturnValue(permissionsWith({ bpp: 'admin' }));
    renderSection('/bpp/budgets', FAKE);
    expect(screen.getAllByRole('link', { name: 'Бюджеты' }).length).toBeGreaterThan(0);
    expect(screen.getByText('Реестр бюджетов')).toBeInTheDocument();
  });

  it('пункты — в порядке order, корень раздела ведёт на первый видимый', async () => {
    permissions.mockReturnValue(permissionsWith({ bpp: 'admin' }));
    renderSection('/bpp', FAKE);
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent('/bpp/budgets'));
    const [side] = screen.getAllByRole('navigation', { name: 'Меню раздела' });
    const labels = Array.from(side.querySelectorAll('a')).map((a) => a.textContent);
    expect(labels).toEqual(['Бюджеты', 'План закупок']);
  });

  it('неизвестный путь раздела — «нет такой страницы»', () => {
    renderSection('/bpp/nope', FAKE);
    expect(screen.getByText('Такой страницы в разделе нет')).toBeInTheDocument();
  });
});

describe('BppLayout — подмодули пакета', () => {
  it('«Мои согласования» — в меню при bpp:read', async () => {
    permissions.mockReturnValue(permissionsWith({ bpp: 'read' }));
    renderSection('/bpp');
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent('/bpp/approvals'));
    expect(screen.getAllByRole('link', { name: 'Мои согласования' }).length).toBeGreaterThan(0);
  });

  it('без bpp:read пункта нет, а маршрут — «Нет доступа»', () => {
    permissions.mockReturnValue(permissionsWith({}));
    renderSection('/bpp/approvals');
    expect(screen.queryAllByRole('link', { name: 'Мои согласования' })).toHaveLength(0);
    expect(screen.getByText('Нет доступа')).toBeInTheDocument();
  });

  it('у переходников заявки и подотчёта нет пунктов меню (реестры — B2.5)', () => {
    // Не точный список пунктов: он растёт с каждым подмодулем (справочники,
    // проекты, контрагенты), а проверяется здесь только отсутствие пунктов
    // у двух переходников.
    const keys = bppModules.filter((m) => m.menu).map((m) => m.key);
    expect(keys).toContain('approvals');
    expect(keys).not.toContain('requests');
    expect(keys).not.toContain('accountable');
    expect(bppModules.map((m) => m.key)).toEqual(
      expect.arrayContaining(['approvals', 'requests', 'accountable']),
    );
  });
});

describe('ссылки на документы из колокольчика и согласования', () => {
  const UUID = '3fa85f64-5717-4562-b3fc-2c963f66afa6';

  it('ссылки /bpp/<документ>/<id> ведут в живую страницу SPA', () => {
    expect(isRoutableUrl(`/bpp/requests/${UUID}`)).toBe(true);
    expect(isRoutableUrl(`/bpp/accountable/${UUID}`)).toBe(true);
  });

  it('раздел — один маршрут /bpp/* под гейтом bpp:read', () => {
    const bpp = protectedRoutes.filter((r) => r.path.startsWith('/bpp'));
    expect(bpp.map((r) => r.path)).toEqual(['/bpp/*']);
    expect(bpp[0].requiresAuth).toBe(true);
    expect(bpp[0].requires).toEqual({ module: 'bpp', level: 'read' });
  });

  it.each([
    [`/bpp/requests/${UUID}`, `Заявка ${UUID}`],
    [`/bpp/accountable/${UUID}`, `Подотчёт ${UUID}`],
  ])('%s открывает документ через таблицу маршрутов приложения', async (url, text) => {
    permissions.mockReturnValue(permissionsWith({ bpp: 'read' }));
    const route = protectedRoutes.find((r) => r.path === '/bpp/*')!;
    const Page = route.component;
    render(
      <QueryClientProvider client={createTestQueryClient()}>
        <MemoryRouter initialEntries={[url]}>
          <Suspense fallback={null}>
            <Routes>
              <Route path={route.path} element={<Page />} />
            </Routes>
          </Suspense>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findByText(text)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'К согласованиям' })).toHaveAttribute('href', '/signoff');
  });
});
