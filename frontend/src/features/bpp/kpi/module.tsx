/**
 * Подмодуль «Отчёты» — R-01 «KPI снабжения» и карточка записи KPI (A5.2,
 * ТЗ §12.5–12.6). Виден при `bpp:read` и признаке `view` на узле `bpp.kpi`
 * (ФД, ОД, ГД; СН — со своими строками); права повторно проверяет сервер.
 */
import { lazy } from 'react';
import { BarChart3 } from 'lucide-react';

import type { BppGatedModule } from '../core/moduleAccess';

export const bppModule: BppGatedModule = {
  key: 'kpi',
  // После «Дашборда оплат» (80).
  order: 85,
  menu: {
    labelKey: 'bpp.kpi.menu',
    labelFallback: 'Отчёты',
    path: 'kpi',
    icon: BarChart3,
  },
  visible: (permissions) =>
    permissions.atLeast('bpp', 'read') && permissions.can('bpp.kpi', 'view'),
  routes: [
    { path: 'kpi', element: lazy(() => import('./KpiReportPage')) },
    { path: 'kpi/:id', element: lazy(() => import('./KpiRecordPage')) },
  ],
};
