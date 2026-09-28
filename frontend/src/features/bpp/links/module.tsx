/**
 * Документы модуля по прямой ссылке (`/bpp/requests/:id`, `/bpp/agreements/:id`,
 * `/bpp/invoices/:id`) — без меню и без гейта подмодуля по узлу: туда ведут
 * карточка согласования и колокольчик, а согласующий или временный
 * исполнитель его должности может не иметь роли в модуле. Видимость документа
 * проверяет сервер (чужой документ — 404), вход в раздел — гейт `/bpp/*`
 * (`bpp:read`).
 *
 * Договор открывается формой F-04, счёт — формой F-05. Реестры — в
 * подмодулях `requests`, `agreements`, `invoices` с гейтом по узлу.
 */
import { lazy } from 'react';

import type { BppGatedModule } from '../core/moduleAccess';

export const bppModule: BppGatedModule = {
  key: 'links',
  order: 1000,
  routes: [
    { path: 'requests/:id', element: lazy(() => import('../requests/RequestFormPage')) },
    { path: 'agreements/:id', element: lazy(() => import('../agreements/AgreementFormPage')) },
    { path: 'invoices/:id', element: lazy(() => import('../invoices/InvoiceFormPage')) },
  ],
};
