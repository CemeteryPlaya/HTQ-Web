/**
 * Подмодуль «Контрагенты» — справочник модуля (ТЗ §18, реестр L-08; пункт
 * меню «Справочники» ТЗ §05 п.9, контрагенты — его часть).
 *
 * Виден при `bpp:read` и признаке `view` на узле `bpp.counterparties`: его
 * несут все роли модуля, кроме АДМ. Создание, правка и блокировка — свои
 * признаки узлов, их проверяют экраны (и сервер).
 */
import { lazy } from 'react';
import { Building2 } from 'lucide-react';

import type { BppGatedModule } from '../core/moduleAccess';

export const bppModule: BppGatedModule = {
  key: 'counterparties',
  // ТЗ §05: «Справочники» — пункт 9 (порядок — номер пункта × 10); сами
  // справочники refdata — 90, контрагенты — сразу за ними.
  order: 91,
  menu: {
    labelKey: 'bpp.counterparties.title',
    labelFallback: 'Контрагенты',
    path: 'counterparties',
    icon: Building2,
  },
  visible: (permissions) =>
    permissions.atLeast('bpp', 'read') && permissions.can('bpp.counterparties', 'view'),
  routes: [
    { path: 'counterparties', element: lazy(() => import('./CounterpartiesPage')) },
    { path: 'counterparties/new', element: lazy(() => import('./CounterpartyCreatePage')) },
    { path: 'counterparties/:id', element: lazy(() => import('./CounterpartyCardPage')) },
  ],
};
