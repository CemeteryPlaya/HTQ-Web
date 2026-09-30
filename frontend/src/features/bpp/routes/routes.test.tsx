/**
 * «Маршруты согласования» раздела (В-09): пункт меню — у ФД и АДМ (узел
 * `bpp.routes` `edit`), список — только документы модуля `bpp.*`, карточка
 * маршрута — внутри раздела.
 */
import { screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { Permissions } from '@/hooks/usePermissions';
import type { DepthFlag } from '@/lib/auth/permissions';
import { renderWithProviders } from '@/test/renderWithProviders';
import type { ApprovalRoute, Subject } from '@/types/signoff';

import { moduleVisible } from '../core/moduleAccess';
import { bppModules } from '../modules';
import { bppModule as routesModule } from './module';
import RoutesPage from './RoutesPage';

const listSubjects = vi.hoisted(() => vi.fn());
const listRoutes = vi.hoisted(() => vi.fn());
vi.mock('@/api/signoff', () => ({ signoffApi: { listSubjects, listRoutes } }));

const withRights = (bpp: boolean, nodes: Record<string, DepthFlag[]>) => ({
  atLeast: (module: string) => bpp && module === 'bpp',
  can: (node: string, flag: DepthFlag) => (nodes[node] ?? []).includes(flag),
}) as unknown as Permissions;

const subject = (subject_type: string, label: string): Subject => ({
  subject_type, label, has_active_route: true, fields: [], scopes: [],
  approver_fields: [], requirement_fields: [],
});

const route = (id: number, subject_type: string, name: string) => ({
  id, subject_type, name, scope: '', scope_label: null, is_active: true, stages: [],
}) as unknown as ApprovalRoute;

describe('подмодуль «Маршруты согласования»', () => {
  it('пункт меню ведёт в routes, маршруты — список и карточка', () => {
    expect(routesModule.menu?.labelFallback).toBe('Маршруты согласования');
    expect(routesModule.routes.map((item) => item.path)).toEqual(['routes', 'routes/:id']);
    expect(bppModules.filter((module) => module.key === 'routes')).toHaveLength(1);
  });

  it('виден по bpp.routes edit: ФД и АДМ — да, без узла или без bpp:read — нет', () => {
    expect(moduleVisible(routesModule, withRights(true, { 'bpp.routes': ['edit'] }))).toBe(true);
    expect(moduleVisible(routesModule, withRights(true, { 'bpp.settings': ['view', 'edit'] })))
      .toBe(false);
    expect(moduleVisible(routesModule, withRights(false, { 'bpp.routes': ['edit'] }))).toBe(false);
  });
});

describe('RoutesPage', () => {
  it('показывает только документы модуля и ведёт на карточку внутри раздела', async () => {
    listSubjects.mockResolvedValue({
      data: [subject('bpp.agreement', 'Договор'), subject('contracts.agreement', 'Договор (старый)')],
    });
    listRoutes.mockResolvedValue({
      data: [route(5, 'bpp.agreement', 'Договор: ФД → ТД → ОД → ГД'),
        route(6, 'contracts.agreement', 'Старый маршрут')],
    });
    renderWithProviders(<RoutesPage />);

    const link = await screen.findByRole('link', { name: 'Договор: ФД → ТД → ОД → ГД' });
    expect(link).toHaveAttribute('href', '/bpp/routes/5');
    expect(screen.queryByText('Старый маршрут')).not.toBeInTheDocument();
    expect(screen.queryByText('Договор (старый)')).not.toBeInTheDocument();
  });
});
