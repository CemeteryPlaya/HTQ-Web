/**
 * Подмодуль «Договоры» (ТЗ §05 п.5, §09): реестр L-05. Форма F-04 по прямой
 * ссылке `/bpp/agreements/:id` — в подмодуле `links` без гейта по узлу:
 * туда ведут согласование и колокольчик. Договор создаётся из Плана закупок
 * (мастер F-03), отдельной кнопки «Создать» нет.
 */
import { lazy } from 'react';
import { FileSignature } from 'lucide-react';

import type { BppGatedModule } from '../core/moduleAccess';

export const bppModule: BppGatedModule = {
  key: 'agreements',
  // ТЗ §05: «Договоры» — пункт 5 меню (порядок — номер пункта × 10).
  order: 50,
  menu: {
    labelKey: 'bpp.agreements.title',
    labelFallback: 'Договоры',
    path: 'agreements',
    icon: FileSignature,
  },
  visible: (permissions) =>
    permissions.atLeast('bpp', 'read') && permissions.can('bpp.agreements', 'view'),
  routes: [{ path: 'agreements', element: lazy(() => import('./AgreementsPage')) }],
};
