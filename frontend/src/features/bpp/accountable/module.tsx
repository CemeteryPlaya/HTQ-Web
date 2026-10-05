/**
 * Подмодуль «Подотчёт» (B4.1): реестр подотчётных средств. Форма заявки по
 * прямой ссылке `/bpp/accountable/:id` — в подмодуле `links` без гейта по
 * узлу: туда ведут согласование и колокольчик.
 */
import { lazy } from 'react';
import { Wallet } from 'lucide-react';

import type { BppGatedModule } from '../core/moduleAccess';

export const bppModule: BppGatedModule = {
  key: 'accountable',
  // Подотчёта нет среди пунктов меню ТЗ §05 — в конец списка.
  order: 900,
  menu: {
    labelKey: 'bpp.accountable.registryTitle',
    labelFallback: 'Подотчёт',
    path: 'accountable',
    icon: Wallet,
  },
  visible: (permissions) =>
    permissions.atLeast('bpp', 'read') && permissions.can('bpp.accountable', 'view'),
  routes: [{ path: 'accountable', element: lazy(() => import('./AccountablePage')) }],
};
