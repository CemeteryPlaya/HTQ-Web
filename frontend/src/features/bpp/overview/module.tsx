/**
 * Подмодуль «Обзор» — стартовая страница раздела по ролям (ТЗ §05, §17;
 * решение пользователя 01.10): показатели и карточки тех частей модуля,
 * которые открыты ролями пользователя, с числами его выборок.
 *
 * Первый пункт меню (`order: 5`), поэтому вход в `/bpp` ведёт сюда (индекс
 * раздела — первый видимый пункт, `BppLayout`). Виден при `bpp:read`: что
 * показать внутри, решает сервер по правам узлов (`GET overview`).
 */
import { lazy } from 'react';
import { LayoutGrid } from 'lucide-react';

import type { BppGatedModule } from '../core/moduleAccess';

export const bppModule: BppGatedModule = {
  key: 'overview',
  // Раньше пунктов ТЗ §05 (бюджеты — 10): страница входа в раздел.
  order: 5,
  menu: {
    labelKey: 'bpp.overview.title',
    labelFallback: 'Обзор',
    path: 'overview',
    icon: LayoutGrid,
  },
  visible: (permissions) => permissions.atLeast('bpp', 'read'),
  routes: [{ path: 'overview', element: lazy(() => import('./OverviewPage')) }],
};
