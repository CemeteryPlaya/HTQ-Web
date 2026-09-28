/**
 * «Проекты» (D-02; задача 9 плана этапа 2 A): экран показывает ровно то,
 * что отдал сервер (ПМ видит только проекты-участия — фильтрует сервер),
 * «Только мои» — параметр `mine=1`, «Новый проект» — только с правом
 * `project.projects` `create`.
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { Permissions } from '@/hooks/usePermissions';
import type { DepthFlag } from '@/lib/auth/permissions';
import { createTestQueryClient } from '@/test/renderWithProviders';

import { ProjectsPage } from './ProjectsPage';

const get = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get, post: vi.fn(), patch: vi.fn() } }));
vi.mock('@/api/hr', () => ({
  fetchEmployees: vi.fn(() => Promise.resolve([
    { id: 1, user: 7, user_id: 7, full_name: 'Иванов Иван' },
  ])),
  fetchDepartments: vi.fn(() => Promise.resolve([])),
}));

function permissionsWith(depth: Record<string, DepthFlag[]>): Permissions {
  return {
    company: 'hi-tech-qazaqstan',
    level: () => 'read',
    atLeast: () => true,
    scope: () => null,
    depth: (node) => depth[node] ?? [],
    can: (node, flag) => (depth[node] ?? []).includes(flag),
    pageHidden: () => false,
    subordinateCompanies: [],
    inheritedFrom: [],
    companyArchived: false,
    isLoading: false,
    isError: false,
    refetch: () => {},
  };
}
const permissions = vi.fn(() => permissionsWith({ 'project.projects': ['view', 'create', 'edit'] }));
vi.mock('@/hooks/usePermissions', () => ({ usePermissions: () => permissions() }));

const PROJECTS = [
  {
    id: 'p-1', code: 'PRJ-001', name: 'ЖК «Орда»', kind: 'project', status: 'active',
    country_code: 'KZ', manager_user_id: 7, customer_name: '', customer_counterparty_id: null,
  },
  {
    id: 'p-2', code: 'OVH', name: 'Общие расходы', kind: 'company_overhead', status: 'closed',
    country_code: 'KZ', manager_user_id: 99, customer_name: '', customer_counterparty_id: null,
  },
];

function renderPage() {
  return render(
    <QueryClientProvider client={createTestQueryClient()}>
      <MemoryRouter>
        <ProjectsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('ProjectsPage', () => {
  beforeEach(() => {
    get.mockReset();
    get.mockResolvedValue({ data: PROJECTS });
    permissions.mockReturnValue(permissionsWith({ 'project.projects': ['view', 'create', 'edit'] }));
  });

  it('список проектов с сервера: код, вид, руководитель по имени, статус', async () => {
    renderPage();
    expect(await screen.findByText('ЖК «Орда»')).toBeInTheDocument();
    expect(screen.getByText('PRJ-001')).toBeInTheDocument();
    expect(screen.getByText('Общие расходы компании')).toBeInTheDocument();
    expect(await screen.findByText('Иванов Иван')).toBeInTheDocument();
    // Имени нет в кадровом списке — номер пользователя, а не пустота.
    expect(screen.getByText('Пользователь №99')).toBeInTheDocument();
    expect(screen.getByText('Активен')).toBeInTheDocument();
    expect(screen.getByText('Закрыт')).toBeInTheDocument();
    expect(get).toHaveBeenCalledWith('project/v1/projects', { params: {} });
  });

  it('«Только мои» уходит параметром mine=1', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText('ЖК «Орда»');
    await user.click(screen.getByRole('checkbox', { name: 'Только мои' }));
    await waitFor(() =>
      expect(get).toHaveBeenCalledWith('project/v1/projects', { params: { mine: 1 } }));
  });

  it('с правом create — кнопка «Новый проект», без него — нет', async () => {
    const first = renderPage();
    await screen.findByText('ЖК «Орда»');
    expect(screen.getByRole('button', { name: 'Новый проект' })).toBeInTheDocument();
    first.unmount();

    permissions.mockReturnValue(permissionsWith({ 'project.projects': ['view'] }));
    renderPage();
    await screen.findByText('ЖК «Орда»');
    expect(screen.queryByRole('button', { name: 'Новый проект' })).not.toBeInTheDocument();
  });

  it('пустой ответ — «Проектов, доступных вам, нет»', async () => {
    get.mockResolvedValue({ data: [] });
    renderPage();
    expect(await screen.findByText('Проектов, доступных вам, нет')).toBeInTheDocument();
  });
});
