/**
 * Подмодуль «Маршруты согласования» (В-09, отложенная часть B1.2): маршруты
 * документов модуля — заявки, договора, счёта, подотчёта и авансового
 * отчёта — правят ФД и АДМ, а не только администратор платформы.
 *
 * Виден при `bpp:read` и признаке `edit` на узле `bpp.routes` (access/0018).
 * Сервер проверяет то же право на каждой ручке маршрутов (`route_editors`
 * типов модуля в `signoff`).
 */
import { lazy } from 'react';
import { GitBranch } from 'lucide-react';

import type { BppGatedModule } from '../core/moduleAccess';

export const bppModule: BppGatedModule = {
  key: 'routes',
  // ТЗ §05 п.10 «Администрирование» — рядом с «Настройками» (100).
  order: 105,
  menu: {
    labelKey: 'bpp.routes.title',
    labelFallback: 'Маршруты согласования',
    path: 'routes',
    icon: GitBranch,
  },
  visible: (permissions) =>
    permissions.atLeast('bpp', 'read') && permissions.can('bpp.routes', 'edit'),
  routes: [
    { path: 'routes', element: lazy(() => import('./RoutesPage')) },
    { path: 'routes/:id', element: lazy(() => import('./RouteEditorPage')) },
  ],
};
