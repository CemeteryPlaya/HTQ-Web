/**
 * «Проектные роли» (спек 2026-10-06 §5): видна держателю `project.roles`,
 * остальным — «Недостаточно прав»; добавление шлёт роль на сервер.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { Permissions } from '@/hooks/usePermissions';
import type { DepthFlag } from '@/lib/auth/permissions';
import { createTestQueryClient } from '@/test/renderWithProviders';

import { ProjectRolesPage } from './ProjectRolesPage';

const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get, post, patch: vi.fn(), delete: vi.fn() } }));

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
const permissions = vi.fn(() => permissionsWith({ 'project.roles': ['edit'] }));
vi.mock('@/hooks/usePermissions', () => ({ usePermissions: () => permissions() }));

function renderPage() {
  return render(
    <QueryClientProvider client={createTestQueryClient()}>
      <MemoryRouter><ProjectRolesPage /></MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('ProjectRolesPage', () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    permissions.mockReturnValue(permissionsWith({ 'project.roles': ['edit'] }));
    get.mockResolvedValue({
      data: [
        { id: 1, name: 'Технический директор', level: 2, default_part: 'office', sort_order: 30, is_active: true },
        { id: 2, name: 'Прораб', level: 3, default_part: 'site', sort_order: 0, is_active: false },
      ],
    });
  });

  it('показывает справочник с уровнем, частью и выключенной ролью', async () => {
    renderPage();
    expect(await screen.findByText('Технический директор')).toBeInTheDocument();
    expect(screen.getByRole('cell', { name: 'L2' })).toBeInTheDocument();
    expect(screen.getByText('выключена')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Включить' })).toBeInTheDocument();
  });

  it('добавляет роль', async () => {
    post.mockResolvedValue({ data: { id: 3 } });
    renderPage();
    await screen.findByText('Технический директор');
    fireEvent.change(screen.getByLabelText('Название'), { target: { value: 'Сметчик' } });
    fireEvent.change(screen.getByLabelText('Часть по умолчанию'), { target: { value: 'site' } });
    fireEvent.click(screen.getByRole('button', { name: 'Добавить роль' }));
    await waitFor(() => expect(post).toHaveBeenCalledWith('project/v1/project-roles', {
      name: 'Сметчик', level: 3, default_part: 'site', sort_order: 0,
    }));
  });

  it('без узла project.roles — «Недостаточно прав» и без запроса', () => {
    permissions.mockReturnValue(permissionsWith({}));
    renderPage();
    expect(screen.getByText('Недостаточно прав для этого действия')).toBeInTheDocument();
    expect(get).not.toHaveBeenCalled();
  });
});
