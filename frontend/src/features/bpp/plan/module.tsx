/**
 * Подмодуль «План закупок» (ТЗ §05 п.4, §08): реестр позиций L-04 и мастер
 * F-03. Виден при `bpp:read` и признаке `view` на узле `bpp.plan` (СН, ПМ)
 * либо `bpp.plan.all` (ФД — все позиции, только просмотр).
 */
import { lazy } from 'react';
import { ListChecks } from 'lucide-react';

import type { BppGatedModule } from '../core/moduleAccess';

export const bppModule: BppGatedModule = {
  key: 'plan',
  // ТЗ §05: «План закупок» — пункт 4 меню (порядок — номер пункта × 10).
  order: 40,
  menu: {
    labelKey: 'bpp.plan.title',
    labelFallback: 'План закупок',
    path: 'plan',
    icon: ListChecks,
  },
  visible: (permissions) => permissions.atLeast('bpp', 'read')
    && (permissions.can('bpp.plan', 'view') || permissions.can('bpp.plan.all', 'view')),
  routes: [{ path: 'plan', element: lazy(() => import('./PlanPage')) }],
};
