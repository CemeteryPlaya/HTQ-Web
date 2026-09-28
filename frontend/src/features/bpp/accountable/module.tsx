/**
 * Подмодуль «Подотчёт» — пока только переходник: документ по прямой ссылке
 * `/bpp/accountable/:id` (туда ведут согласование и колокольчик).
 *
 * Реестр и форма — экраны Руслана; они заменят этот файл своим манифестом.
 * Пункта меню здесь нет намеренно: пункт без реестра вёл бы в пустоту.
 */
import { documentRoute } from '../core/documentRoute';
import type { BppGatedModule } from '../core/moduleAccess';

export const bppModule: BppGatedModule = {
  key: 'accountable',
  // Подотчёта нет среди пунктов меню ТЗ §05 — в конец списка.
  order: 900,
  routes: [
    {
      path: 'accountable/:id',
      element: documentRoute(() => import('./AccountableSignoffView')),
    },
  ],
};
