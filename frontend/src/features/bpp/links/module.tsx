/**
 * Документы модуля по прямой ссылке (`/bpp/requests/:id`) — без меню и без
 * гейта подмодуля по узлу: туда ведут карточка согласования и колокольчик, а
 * согласующий или временный исполнитель его должности может не иметь роли в
 * модуле. Видимость документа проверяет сервер (чужая заявка — 404), вход в
 * раздел — гейт `/bpp/*` (`bpp:read`).
 *
 * Реестр и создание заявки — в подмодуле `requests` с гейтом по узлу.
 */
import { lazy } from 'react';

import type { BppGatedModule } from '../core/moduleAccess';

export const bppModule: BppGatedModule = {
  key: 'links',
  order: 1000,
  routes: [
    { path: 'requests/:id', element: lazy(() => import('../requests/RequestFormPage')) },
  ],
};
