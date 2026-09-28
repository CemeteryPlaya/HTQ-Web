/**
 * Карточка проекта (D-02; задача 9 плана этапа 2 A): показывает ровно то, что
 * отдал сервер, руководитель — участник и без кнопки «Убрать», правка и
 * участники — по узлам `project.projects`/`project.members`, чужой проект —
 * «Проект не найден» (сервер отвечает 404 и для несуществующего, и для
 * проекта-неучастия ПМ, разница фронту не видна).
 */
import { render, screen } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { Permissions } from '@/hooks/usePermissions';
import type { DepthFlag } from '@/lib/auth/permissions';
import { createTestQueryClient } from '@/test/renderWithProviders';

import { ProjectCardPage } from './ProjectCardPage';

const get = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get, post: vi.fn(), patch: vi.fn(), delete: vi.fn() } }));
vi.mock('@/api/hr', () => ({
  fetchEmployees: vi.fn(() => Promise.resolve([
    { id: 1, user: 7, user_id: 7, full_name: 'Иванов Иван' },
    { id: 2, user: 8, user_id: 8, full_name: 'Петров Пётр' },
  ])),
  fetchDepartments: vi.fn(() => Promise.resolve([])),
}));

function permissionsWith(depth: Record<string, DepthFlag[]>): Permissions {
  return {
    company: 'hi-tech-qazaqstan',
    level: () => 'write',
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
const PM = { 'project.projects': ['view'], 'project.members': [] } as Record<string, DepthFlag[]>;
const ADMIN = { 'project.projects': ['view', 'create', 'edit'], 'project.members': ['edit'] } as Record<string, DepthFlag[]>;
const permissions = vi.fn(() => permissionsWith(ADMIN));
vi.mock('@/hooks/usePermissions', () => ({ usePermissions: () => permissions() }));

const ID = '3fa85f64-5717-4562-b3fc-2c963f66afa6';

const project = (over: Record<string, unknown> = {}) => ({
  id: ID, code: 'PRJ-001', name: 'ЖК «Орда»', kind: 'project', status: 'active',
  country_code: 'KZ', manager_user_id: 7, customer_name: 'ТОО «Заказчик»',
  customer_counterparty_id: null, ...over,
});

function mockServer(members: number[] = [7, 8]) {
  get.mockImplementation((url: string) => {
    if (url === `project/v1/projects/${ID}/members`) return Promise.resolve({ data: members });
    if (url === `project/v1/projects/${ID}`) return Promise.resolve({ data: project() });
    return Promise.reject(new Error(`unexpected GET ${url}`));
  });
}

function renderCard() {
  return render(
    <QueryClientProvider client={createTestQueryClient()}>
      <MemoryRouter initialEntries={[`/bpp/projects/${ID}`]}>
        <Routes>
          <Route path="/bpp/projects/:id" element={<ProjectCardPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('ProjectCardPage', () => {
  beforeEach(() => {
    get.mockReset();
    permissions.mockReturnValue(permissionsWith(ADMIN));
  });

  it('карточка: код, вид, заказчик, руководитель и участники по именам', async () => {
    mockServer();
    renderCard();

    expect(await screen.findByRole('heading', { name: 'ЖК «Орда»' })).toBeInTheDocument();
    expect(screen.getByText('PRJ-001')).toBeInTheDocument();
    expect(screen.getByText('ТОО «Заказчик»')).toBeInTheDocument();
    // Участники грузятся отдельным запросом после карточки — ждём его.
    expect(await screen.findByText('Петров Пётр')).toBeInTheDocument();
    // Руководитель — и в реквизитах, и в списке участников с меткой.
    expect(screen.getAllByText('Иванов Иван').length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText('руководитель')).toBeInTheDocument();
  });

  it('у руководителя нет кнопки «Убрать участника», у прочих — есть с правом edit', async () => {
    mockServer();
    renderCard();
    await screen.findByText('Петров Пётр');

    expect(screen.queryByRole('button', { name: /Убрать участника Иванов Иван/ })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Убрать участника Петров Пётр/ })).toBeInTheDocument();
  });

  it('ПМ без узла project.members — ни «Изменить», ни «Убрать», ни добавления участника', async () => {
    permissions.mockReturnValue(permissionsWith(PM));
    mockServer();
    renderCard();

    expect(await screen.findByRole('heading', { name: 'ЖК «Орда»' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Изменить' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Убрать участника/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Добавить участника' })).not.toBeInTheDocument();
  });

  it('чужой проект (404 у сервера) — «Проект не найден», как у ПМ вне участия', async () => {
    get.mockRejectedValue({ response: { status: 404, data: { detail: 'Проект не найден.' } } });
    renderCard();
    expect(await screen.findByText('Проект не найден')).toBeInTheDocument();
  });
});
