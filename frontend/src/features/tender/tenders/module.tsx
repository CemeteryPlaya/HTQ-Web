/**
 * Подраздел «Тендеры» (T2.3; план этапов 0–2 §4.4): реестр и карточка
 * тендера с участниками. Виден при `tender:read` и признаке `view` на узле
 * `tender.tenders`; объявляется тендер с карточки утверждённой заявки.
 */
import { lazy } from 'react';
import { Gavel } from 'lucide-react';

import type { TenderModule } from '../modules';

export const tenderModule: TenderModule = {
  key: 'tenders',
  order: 20,
  menu: {
    labelKey: 'tender.tenders.title',
    labelFallback: 'Тендеры',
    path: 'tenders',
    icon: Gavel,
  },
  visible: (permissions) =>
    permissions.atLeast('tender', 'read') && permissions.can('tender.tenders', 'view'),
  routes: [
    { path: 'tenders', element: lazy(() => import('./TendersPage')) },
    { path: 'tenders/:id', element: lazy(() => import('./TenderCardPage')) },
  ],
};
