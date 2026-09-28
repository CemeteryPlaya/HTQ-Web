/**
 * Подмодуль «Справочники» (ТЗ §05, §18; задача 9, A2.4): статьи бюджета,
 * валюты и курсы, НДС и МРП, единицы измерения, страны.
 *
 * Виден при `refdata:read` — у справочников свой модуль прав, отдельный от
 * `bpp` (аппка `apps.refdata`, схема `public`). Правку уровень не решает:
 * её включает `can_edit` из ответа сервера (правит только управляющая
 * компания, D-03), поэтому пункт один для всех, кто может читать.
 */
import { lazy } from 'react';
import { BookMarked } from 'lucide-react';

import type { BppGatedModule } from '../core/moduleAccess';

export const bppModule: BppGatedModule = {
  key: 'refdata',
  // ТЗ §05: «Справочники» — пункт 9 меню (порядок — номер пункта × 10).
  // Проекты и контрагенты по ТЗ — тоже справочники пункта 9, но свои
  // подмодули со своими пунктами меню (задача 9, соседние каталоги).
  order: 90,
  menu: {
    labelKey: 'bpp.refdata.title',
    labelFallback: 'Справочники',
    path: 'refdata',
    icon: BookMarked,
  },
  visible: (permissions) => permissions.atLeast('refdata', 'read'),
  routes: [{ path: 'refdata', element: lazy(() => import('./RefdataPage')) }],
};
