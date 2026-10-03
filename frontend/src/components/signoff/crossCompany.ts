/**
 * Помощники согласования между компаниями (мастер-план БЗО, B8.1) — отдельно
 * от компонентов, чтобы файлы компонентов экспортировали только компоненты
 * (иначе Vite теряет горячую перезагрузку).
 */
import type { InboxAllItem, PositionRef } from '@/types/signoff';

/** Ключ должности для словарей и React: компания и id — id повторяются по
 *  компаниям, поэтому одного id мало. */
export const refKey = (ref: PositionRef): string => `${ref.company}:${ref.position_id}`;

/** Задача другой компании, а не компании текущего адреса. */
export const isForeign = (item: InboxAllItem): boolean =>
  Boolean(item.company && !item.company.current);
