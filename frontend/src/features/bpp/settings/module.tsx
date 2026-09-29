/**
 * Подмодуль «Настройки» (ТЗ §05 п.10 «Администрирование», §18; A3.1):
 * счета организации и шаблоны выписок.
 *
 * Виден при `bpp:read` и признаке `view` на узле `bpp.settings` (ФД — чтение,
 * АДМ — всё). БУХ читает справочник через `bpp.bank`, но пункта «Настройки»
 * у него нет: счёт он выбирает в форме загрузки, настраивать ему нечего.
 */
import { lazy } from 'react';
import { Settings } from 'lucide-react';

import type { BppGatedModule } from '../core/moduleAccess';

export const bppModule: BppGatedModule = {
  key: 'settings',
  // ТЗ §05: «Администрирование» — пункт 10 (порядок — номер пункта × 10).
  order: 100,
  menu: {
    labelKey: 'bpp.bankSettings.title',
    labelFallback: 'Настройки',
    path: 'settings',
    icon: Settings,
  },
  visible: (permissions) =>
    permissions.atLeast('bpp', 'read') && permissions.can('bpp.settings', 'view'),
  routes: [{ path: 'settings', element: lazy(() => import('./SettingsPage')) }],
};
