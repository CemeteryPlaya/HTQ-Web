/**
 * Подмодуль «Выгрузки» — экран фоновой выгрузки реестра по прямой ссылке
 * `/bpp/exports/:id` (задача 6, уведомление ведёт сюда). Пункта меню нет
 * намеренно: сюда не приходят иначе, чем по ссылке из уведомления или
 * колокольчика.
 */
import { lazy } from 'react';

import type { BppGatedModule } from '../core/moduleAccess';

export const bppModule: BppGatedModule = {
  key: 'exports',
  // После подотчёта — тоже документ без пункта меню.
  order: 910,
  routes: [
    { path: 'exports/:id', element: lazy(() => import('./ExportStatusPage')) },
  ],
};
