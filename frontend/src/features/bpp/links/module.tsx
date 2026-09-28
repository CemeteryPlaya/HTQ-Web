/**
 * Документы модуля по прямой ссылке (`/bpp/requests/:id`, `/bpp/agreements/:id`,
 * `/bpp/invoices/:id`) — без меню и без гейта подмодуля по узлу: туда ведут
 * карточка согласования и колокольчик, а согласующий или временный
 * исполнитель его должности может не иметь роли в модуле. Видимость документа
 * проверяет сервер (чужой документ — 404), вход в раздел — гейт `/bpp/*`
 * (`bpp:read`).
 *
 * Договор и счёт пока открываются тем же телом, что и в карточке
 * согласования (`documentRoute`); формы F-04 / F-05 заменят эти строки.
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
    {
      path: 'agreements/:id',
      element: documentRoute(() => import('../agreements/AgreementSignoffView')),
    },
    {
      path: 'invoices/:id',
      element: documentRoute(() => import('../invoices/InvoiceSignoffView')),
    },
  ],
};
