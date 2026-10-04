/**
 * Подмодуль «Мои согласования» (ТЗ §05 п.3, D-34) — очередь движка
 * signoff, отфильтрованная до документов модуля.
 *
 * Виден при `bpp:read`. ТЗ называет ТД, ОД, ФД и ГД, но согласующим этапа
 * может оказаться и другая роль (замещение, временный исполнитель), а
 * пустая очередь безвредна — поэтому пункт не сужается до четырёх ролей.
 */
import { lazy } from 'react';
import { Stamp } from 'lucide-react';

import type { BppGatedModule } from '../core/moduleAccess';

export const bppModule: BppGatedModule = {
  key: 'approvals',
  // ТЗ §05: «Мои согласования» — пункт 3 меню (порядок — номер пункта × 10).
  order: 30,
  menu: {
    labelKey: 'bpp.approvals.title',
    labelFallback: 'Мои согласования',
    path: 'approvals',
    icon: Stamp,
  },
  visible: (permissions) => permissions.atLeast('bpp', 'read'),
  routes: [{ path: 'approvals', element: lazy(() => import('./MyApprovalsPage')) }],
};
