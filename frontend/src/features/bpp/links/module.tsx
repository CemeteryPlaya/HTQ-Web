/**
 * Документы модуля по прямой ссылке (`/bpp/requests/:id`, `/bpp/agreements/:id`,
 * `/bpp/invoices/:id`) — без меню и без гейта подмодуля по узлу: туда ведут
 * карточка согласования и колокольчик, а согласующий или временный
 * исполнитель его должности может не иметь роли в модуле. Видимость документа
 * проверяет сервер (чужой документ — 404), вход в раздел — гейт `/bpp/*`
 * (`bpp:read`).
 *
 * Договор открывается формой F-04; счёт пока — тем же телом, что и в
 * карточке согласования (`documentRoute`), форма F-05 заменит эту строку.
 * Реестр и создание заявки — в подмодуле `requests` с гейтом по узлу.
 */
import { lazy } from 'react';

import { documentRoute } from '../core/documentRoute';
import type { BppGatedModule } from '../core/moduleAccess';

export const bppModule: BppGatedModule = {
  key: 'links',
  order: 1000,
  routes: [
    { path: 'requests/:id', element: lazy(() => import('../requests/RequestFormPage')) },
    { path: 'agreements/:id', element: lazy(() => import('../agreements/AgreementFormPage')) },
    {
      path: 'invoices/:id',
      element: documentRoute(() => import('../invoices/InvoiceSignoffView')),
    },
  ],
};
