/**
 * Подмодуль «Заявки на закупку» (ТЗ §05 п.2, §07): реестр L-02 и создание F-02.
 *
 * Виден при `bpp:read` и признаке `view` на узле `bpp.requests`: СН и ПМ
 * видят свои заявки, директора — все (выборку режет сервер). Карточка по
 * прямой ссылке `/bpp/requests/:id` — в подмодуле `links` без этого гейта:
 * туда ведут согласование и колокольчик, а согласующий (или временный
 * исполнитель его должности) может не иметь роли в модуле — какую заявку
 * ему показать, решает сервер.
 */
import { lazy } from 'react';
import { ClipboardList } from 'lucide-react';

import type { BppGatedModule } from '../core/moduleAccess';

const RequestFormPage = lazy(() => import('./RequestFormPage'));

export const bppModule: BppGatedModule = {
  key: 'requests',
  // ТЗ §05: «Заявки на закупку» — пункт 2 меню (порядок — номер пункта × 10).
  order: 20,
  menu: {
    labelKey: 'bpp.requests.title',
    labelFallback: 'Заявки на закупку',
    path: 'requests',
    icon: ClipboardList,
  },
  visible: (permissions) =>
    permissions.atLeast('bpp', 'read') && permissions.can('bpp.requests', 'view'),
  routes: [
    { path: 'requests', element: lazy(() => import('./RequestsPage')) },
    { path: 'requests/new', element: RequestFormPage },
  ],
};
