/**
 * Подраздел «Обзор» — стартовая страница раздела «Тендеры» (T0.4). Пока
 * заглушка: заявки (T1.4) и тендеры (T2.3) придут своими подразделами, а
 * сводку по ним обзор получит, когда появятся сами документы.
 *
 * Первый пункт меню (`order: 5`), поэтому вход в `/tender` ведёт сюда
 * (индекс раздела — первый видимый пункт, `TenderLayout`).
 */
import { lazy } from 'react';
import { LayoutGrid } from 'lucide-react';

import type { TenderModule } from '../modules';

export const tenderModule: TenderModule = {
  key: 'overview',
  order: 5,
  menu: {
    labelKey: 'tender.overview.title',
    labelFallback: 'Обзор',
    path: 'overview',
    icon: LayoutGrid,
  },
  visible: (permissions) => permissions.atLeast('tender', 'read'),
  routes: [{ path: 'overview', element: lazy(() => import('./OverviewPage')) }],
};
