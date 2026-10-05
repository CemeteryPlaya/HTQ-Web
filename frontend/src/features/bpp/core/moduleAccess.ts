/**
 * Видимость подмодуля раздела «Закупки и оплаты» по правам (ТЗ §05: пункт
 * меню показывается, только если у роли есть право хотя бы на просмотр
 * раздела; права повторно проверяет сервер).
 *
 * Манифест подмодуля (`BppModule`, `features/bpp/modules.ts`) полем прав не
 * владеет — он собран задачей 2 до каркаса. Поэтому признак — расширение
 * манифеста здесь: подмодуль объявляет `bppModule: BppGatedModule`, а
 * `BppLayout` спрашивает `moduleVisible`. Без `visible` подмодуль виден
 * всякому, кто вошёл в раздел (гейт `/bpp/*` — `bpp:read`).
 */
import type { Permissions } from '@/hooks/usePermissions';

import type { BppModule } from '../modules';

export interface BppGatedModule extends BppModule {
  /** `false` — пункта меню нет, а маршруты подмодуля отвечают «Нет доступа». */
  visible?: (permissions: Permissions) => boolean;
}

export function moduleVisible(module: BppModule, permissions: Permissions): boolean {
  const { visible } = module as BppGatedModule;
  return typeof visible === 'function' ? visible(permissions) : true;
}
