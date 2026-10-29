/**
 * Подраздел «Заявки на тендер» (T1.4; план этапов 0–2 §3.5): реестр, форма
 * (создание и правка) и карточка с частями-ЗЗ.
 *
 * Виден при `tender:read` и признаке `view` на узле `tender.requests`:
 * автор видит свои заявки, держатель `tender.requests.all` — все (выборку
 * режет сервер). Создание — по `create` того же узла (кнопка реестра).
 */
import { lazy } from 'react';
import { ClipboardList } from 'lucide-react';

import type { TenderModule } from '../modules';

const RequestFormPage = lazy(() => import('./RequestFormPage'));

export const tenderModule: TenderModule = {
  key: 'requests',
  order: 10,
  menu: {
    labelKey: 'tender.requests.title',
    labelFallback: 'Заявки на тендер',
    path: 'requests',
    icon: ClipboardList,
  },
  visible: (permissions) =>
    permissions.atLeast('tender', 'read') && permissions.can('tender.requests', 'view'),
  routes: [
    { path: 'requests', element: lazy(() => import('./RequestsPage')) },
    { path: 'requests/new', element: RequestFormPage },
    { path: 'requests/:id', element: lazy(() => import('./RequestCardPage')) },
    { path: 'requests/:id/edit', element: RequestFormPage },
  ],
};
