/**
 * Подмодуль «Заявки на закупку» — пока только переходник: документ по
 * прямой ссылке `/bpp/requests/:id` (туда ведут согласование и колокольчик).
 *
 * Реестр L-02, форма F-02 и пункт меню — экраны B2.5 (Руслан); они заменят
 * этот файл своим манифестом. Пункта меню здесь нет намеренно: пункт без
 * реестра вёл бы в пустоту.
 */
import { documentRoute } from '../core/documentRoute';
import type { BppGatedModule } from '../core/moduleAccess';

export const bppModule: BppGatedModule = {
  key: 'requests',
  // ТЗ §05: «Заявки на закупку» — пункт 2 меню (порядок — номер пункта × 10).
  order: 20,
  routes: [
    { path: 'requests/:id', element: documentRoute(() => import('./RequestSignoffView')) },
  ],
};
