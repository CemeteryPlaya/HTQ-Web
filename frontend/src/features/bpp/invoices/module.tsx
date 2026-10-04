/**
 * Подмодуль «Счета на оплату» (ТЗ §05 п.6, §10): реестр L-06 с вкладками.
 * Форма F-05 по прямой ссылке `/bpp/invoices/:id` — в подмодуле `links` без
 * гейта по узлу: туда ведут согласование и колокольчик. Счёт создаётся из
 * Плана закупок или из действующего договора, отдельной кнопки «Создать» нет.
 */
import { lazy } from 'react';
import { Receipt } from 'lucide-react';

import type { BppGatedModule } from '../core/moduleAccess';

export const bppModule: BppGatedModule = {
  key: 'invoices',
  // ТЗ §05: «Счета на оплату» — пункт 6 меню (порядок — номер пункта × 10).
  order: 60,
  menu: {
    labelKey: 'bpp.invoices.title',
    labelFallback: 'Счета на оплату',
    path: 'invoices',
    icon: Receipt,
  },
  visible: (permissions) =>
    permissions.atLeast('bpp', 'read') && permissions.can('bpp.invoices', 'view'),
  routes: [{ path: 'invoices', element: lazy(() => import('./InvoicesPage')) }],
};
