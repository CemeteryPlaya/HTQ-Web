/**
 * Подмодуль «Дашборд оплат» D-01 (ТЗ §05 п.8, §11.5; A4.3): показатели —
 * ссылки на реестр счетов, столбцы по статьям проекта, линия «Оплачено по
 * банку» по неделям, топ-10 контрагентов.
 *
 * Виден при `bpp:read` и признаке `view` на узле `bpp.dashboard` (ФД, ТД,
 * ОД, ГД, БУХ — матрица ролей); права повторно проверяет сервер (403
 * `E-ACC-01`).
 */
import { lazy } from 'react';
import { LayoutDashboard } from 'lucide-react';

import type { BppGatedModule } from '../core/moduleAccess';

export const bppModule: BppGatedModule = {
  key: 'dashboard',
  // ТЗ §05: «Дашборд оплат» — пункт 8 меню, сразу после «Оплаты факт» (70).
  order: 80,
  menu: {
    labelKey: 'bpp.dashboard.title',
    labelFallback: 'Дашборд оплат',
    path: 'dashboard',
    icon: LayoutDashboard,
  },
  visible: (permissions) =>
    permissions.atLeast('bpp', 'read') && permissions.can('bpp.dashboard', 'view'),
  routes: [{ path: 'dashboard', element: lazy(() => import('./PaymentsDashboardPage')) }],
};
