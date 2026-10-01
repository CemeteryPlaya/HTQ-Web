/**
 * Подмодуль «Альтернативы» — лента L-09 «Закупки для альтернатив» и форма
 * F-07 альтернативного предложения (A5.1, ТЗ §12). Виден при `bpp:read` и
 * признаке `view` на узле `bpp.alternatives` (СН, ФД, ТД, ОД, ГД, ПМ — со
 * своими документами); права повторно проверяет сервер. Карточка АП по
 * `/bpp/alternatives/:id` — цель ссылок уведомлений и записей KPI.
 */
import { lazy } from 'react';
import { Scale } from 'lucide-react';

import type { BppGatedModule } from '../core/moduleAccess';

export const bppModule: BppGatedModule = {
  key: 'alternatives',
  // Между «Счетами на оплату» (60) и «Оплатами факт» (70).
  order: 65,
  menu: {
    labelKey: 'bpp.alternatives.menu',
    labelFallback: 'Альтернативы',
    path: 'alternatives',
    icon: Scale,
  },
  visible: (permissions) =>
    permissions.atLeast('bpp', 'read') && permissions.can('bpp.alternatives', 'view'),
  routes: [
    { path: 'alternatives', element: lazy(() => import('./AlternativesFeedPage')) },
    { path: 'alternatives/:id', element: lazy(() => import('./OfferFormPage')) },
  ],
};
