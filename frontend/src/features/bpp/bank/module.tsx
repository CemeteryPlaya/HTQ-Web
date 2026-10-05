/**
 * Подмодуль «Оплаты факт» (ТЗ §05 п.7, §11; A4.1): реестр загрузок выписок
 * L-07, форма загрузки и экран загрузки. Сверка со счетами — этап 4 (A4.2).
 *
 * Виден при `bpp:read` и признаке `view` на узле `bpp.bank` (ФД; БУХ —
 * просмотр). «Загрузить выписку» — признак `edit` того же узла (ФД).
 */
import { lazy } from 'react';
import { Landmark } from 'lucide-react';

import type { BppGatedModule } from '../core/moduleAccess';

export const bppModule: BppGatedModule = {
  key: 'bank',
  // ТЗ §05: «Оплаты факт» — пункт 7 меню (порядок — номер пункта × 10).
  order: 70,
  menu: {
    labelKey: 'bpp.bank.title',
    labelFallback: 'Оплаты факт',
    path: 'bank',
    icon: Landmark,
  },
  visible: (permissions) =>
    permissions.atLeast('bpp', 'read') && permissions.can('bpp.bank', 'view'),
  routes: [
    { path: 'bank', element: lazy(() => import('./BankImportsPage')) },
    { path: 'bank/new', element: lazy(() => import('./BankImportForm')) },
    { path: 'bank/:id', element: lazy(() => import('./BankImportPage')) },
  ],
};
