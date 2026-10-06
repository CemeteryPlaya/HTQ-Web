/**
 * Раздел «Тендеры» (`/tender/*`, T0.4): каркас по образцу «Закупок и
 * оплат» — меню из реестра подразделов по правам, «Нет доступа» на
 * маршруте закрытого подраздела, корень раздела ведёт на первый видимый
 * пункт («Обзор»), сам раздел — один маршрут под гейтом `tender:read`.
 */
import { Suspense } from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

import { protectedRoutes } from '@/app/routing/routeDefinitions';
import type { Permissions } from '@/hooks/usePermissions';
import type { AccessLevel } from '@/lib/auth/permissions';
import { createTestQueryClient } from '@/test/renderWithProviders';

import { TenderLayout } from './TenderLayout';
import type { TenderModule } from './modules';

vi.mock('@/components/Header', () => ({ Header: () => null }));
vi.mock('@/components/Footer', () => ({ Footer: () => null }));

const ORDER: AccessLevel[] = ['none', 'read', 'write', 'admin'];

function permissionsWith(levels: Record<string, AccessLevel>, isLoading = false): Permissions {
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
    isLoading,
    isError: false,
    refetch: () => {},
  };
}

const permissions = vi.fn(() => permissionsWith({ tender: 'read' }));
vi.mock('@/hooks/usePermissions', () => ({ usePermissions: () => permissions() }));

function WhereAmI() {
  return <div data-testid="where">{useLocation().pathname}</div>;
}

function renderSection(route: string, modules?: TenderModule[]) {
  return render(
    <QueryClientProvider client={createTestQueryClient()}>
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route path="/tender/*" element={<TenderLayout modules={modules} />} />
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

const FAKE: TenderModule[] = [
  {
    key: 'tenders', order: 20,
    menu: { labelKey: 'tender.test.tenders', labelFallback: 'Тендеры', path: 'tenders' },
    visible: (p) => p.atLeast('tender', 'admin'),
    routes: [{ path: 'tenders', element: Screen('Реестр тендеров') }],
  },
  {
    key: 'requests', order: 10,
    menu: { labelKey: 'tender.test.requests', labelFallback: 'Заявки', path: 'requests' },
    routes: [{ path: 'requests', element: Screen('Реестр заявок') }],
  },
];

describe('TenderLayout — меню по правам', () => {
  it('пункт с visible === false не рисуется, без visible — рисуется', () => {
    permissions.mockReturnValue(permissionsWith({ tender: 'read' }));
    renderSection('/tender/requests', FAKE);
    expect(screen.queryAllByRole('link', { name: 'Тендеры' })).toHaveLength(0);
    expect(screen.getAllByRole('link', { name: 'Заявки' }).length).toBeGreaterThan(0);
    expect(screen.getByText('Реестр заявок')).toBeInTheDocument();
  });

  it('маршрут скрытого подраздела отвечает «Нет доступа», а не экраном', () => {
    permissions.mockReturnValue(permissionsWith({ tender: 'read' }));
    renderSection('/tender/tenders', FAKE);
    expect(screen.getByText('Нет доступа')).toBeInTheDocument();
    expect(screen.queryByText('Реестр тендеров')).not.toBeInTheDocument();
  });

  it('пока права не пришли — не «Нет доступа»', () => {
    permissions.mockReturnValue(permissionsWith({}, true));
    renderSection('/tender/tenders', FAKE);
    expect(screen.queryByText('Нет доступа')).not.toBeInTheDocument();
  });

  it('пункты — в порядке, в котором их отдал реестр; корень ведёт на первый видимый', async () => {
    permissions.mockReturnValue(permissionsWith({ tender: 'admin' }));
    renderSection('/tender', [...FAKE].sort((a, b) => a.order - b.order));
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent('/tender/requests'));
    const [side] = screen.getAllByRole('navigation', { name: 'Меню раздела' });
    const labels = Array.from(side.querySelectorAll('a')).map((a) => a.textContent);
    expect(labels).toEqual(['Заявки', 'Тендеры']);
  });

  it('неизвестный путь раздела — «нет такой страницы»', () => {
    permissions.mockReturnValue(permissionsWith({ tender: 'read' }));
    renderSection('/tender/nope', FAKE);
    expect(screen.getByText('Такой страницы в разделе нет')).toBeInTheDocument();
  });

  it('заголовок раздела — «Тендеры»', () => {
    permissions.mockReturnValue(permissionsWith({ tender: 'read' }));
    renderSection('/tender/requests', FAKE);
    expect(screen.getByRole('heading', { level: 1, name: 'Тендеры' })).toBeInTheDocument();
  });
});

describe('TenderLayout — подразделы пакета', () => {
  it('при tender:read корень раздела ведёт на «Обзор» с заглушкой', async () => {
    permissions.mockReturnValue(permissionsWith({ tender: 'read' }));
    renderSection('/tender');
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent('/tender/overview'));
    expect(await screen.findByText('Здесь появятся заявки и тендеры')).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: 'Обзор' }).length).toBeGreaterThan(0);
  });

  it('без tender:read пункта «Обзор» нет, а маршрут — «Нет доступа»', () => {
    permissions.mockReturnValue(permissionsWith({}));
    renderSection('/tender/overview');
    expect(screen.queryAllByRole('link', { name: 'Обзор' })).toHaveLength(0);
    expect(screen.getByText('Нет доступа')).toBeInTheDocument();
  });
});

describe('маршрут раздела', () => {
  it('раздел — один маршрут /tender/* под гейтом tender:read', () => {
    const tender = protectedRoutes.filter((r) => r.path.startsWith('/tender'));
    expect(tender.map((r) => r.path)).toEqual(['/tender/*']);
    expect(tender[0].requiresAuth).toBe(true);
    expect(tender[0].requires).toEqual({ module: 'tender', level: 'read' });
  });

  it('маршрут приложения раскладывает раздел (ленивая загрузка TenderLayout)', async () => {
    permissions.mockReturnValue(permissionsWith({ tender: 'read' }));
    const route = protectedRoutes.find((r) => r.path === '/tender/*')!;
    const Page = route.component;
    render(
      <QueryClientProvider client={createTestQueryClient()}>
        <MemoryRouter initialEntries={['/tender/overview']}>
          <Suspense fallback={null}>
            <Routes>
              <Route path={route.path} element={<Page />} />
            </Routes>
          </Suspense>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findByText('Здесь появятся заявки и тендеры')).toBeInTheDocument();
  });
});
