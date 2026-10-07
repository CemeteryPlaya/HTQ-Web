/**
 * Подраздел «Потенциальные поставщики» (T2.3; план этапов 0–2 §4.1, §4.4):
 * справочник поставщиков, которых ещё нет среди контрагентов БЗО. Виден при
 * `tender:read` и признаке `view` на узле `tender.prospects`.
 */
import { lazy } from 'react';
import { Contact } from 'lucide-react';

import type { TenderModule } from '../modules';

export const tenderModule: TenderModule = {
  key: 'prospects',
  order: 30,
  menu: {
    labelKey: 'tender.prospects.title',
    labelFallback: 'Потенциальные поставщики',
    path: 'prospects',
    icon: Contact,
  },
  visible: (permissions) =>
    permissions.atLeast('tender', 'read') && permissions.can('tender.prospects', 'view'),
  routes: [{ path: 'prospects', element: lazy(() => import('./ProspectsPage')) }],
};
