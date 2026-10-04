import type { CalendarEvent, ProductionDay } from '@/types/calendar';

/**
 * Правка события календаря — правило сервера (`tasks/services/calendar_service._is_editor`):
 * автор события или администратор/staff платформы. Узлы refdata сюда не относятся.
 */
export function canEditCalendarEvent(
  ev: Pick<CalendarEvent, 'creator_id' | 'creator'>,
  currentUserId: number | null,
  roles: string[] | undefined,
): boolean {
  if (currentUserId && (ev.creator_id ?? ev.creator) === currentUserId) return true;
  return Boolean(roles?.includes('staff') || roles?.includes('admin'));
}

/**
 * Правка дня производственного календаря: узел `refdata.production_calendar`
 * (`edit`) и управляющая компания. Признак компании приходит с сервера в
 * `can_edit` строк ответа (иначе в дочерней компании кнопка видна, а сервер даёт 403).
 */
export function canEditProductionDay(hasNodeEdit: boolean, days: ProductionDay[]): boolean {
  return hasNodeEdit && days.length > 0 && days.every((d) => d.can_edit === true);
}
