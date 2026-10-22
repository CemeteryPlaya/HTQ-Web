/**
 * Какой экран показать поставщику на отказ портала (план этапа 3 §1, T3.5).
 * Тело 404 причин не различает (неизвестный, отозванный, перевыпущенный
 * токен, тендер-черновик) — и экран один: «Ссылка недействительна».
 */
import { PortalError } from './client';

export type PortalScreen =
  | 'invalid' // 404 — ссылка недействительна
  | 'device' // 403/409 E-TND-06 — открыта на другом устройстве
  | 'closed' // 409 E-TND-05 — приём завершён
  | 'rate' // 429 E-RATE-01
  | 'unavailable' // 503 — сервис выключен / сканер файлов недоступен
  | 'network' // нет связи
  | 'generic';

export const DEVICE_CODE = 'E-TND-06';
export const CLOSED_CODE = 'E-TND-05';
export const CONFLICT_CODE = 'E-CON-01';

export function screenOf(error: unknown): PortalScreen {
  if (!(error instanceof PortalError)) return 'generic';
  if (error.code === DEVICE_CODE) return 'device';
  if (error.code === CLOSED_CODE) return 'closed';
  if (error.status === 404) return 'invalid';
  if (error.status === 429) return 'rate';
  if (error.status === 503) return 'unavailable';
  if (error.status === 0) return 'network';
  return 'generic';
}

/** Отказ, после которого форма жить не может, — экран целиком. */
export const isFatal = (screen: PortalScreen) => screen === 'invalid' || screen === 'device';

export const retryAfterOf = (error: unknown): number | null =>
  (error instanceof PortalError ? error.retryAfter : null);

/**
 * Ошибки по полям из конверта сервиса: `lines[i].x` → строка формы i-й
 * позиции (`line:<item_id>`), `requisites.x` и прочие — по имени.
 */
export function portalFieldErrors(error: unknown, itemIds: string[]): Record<string, string> {
  if (!(error instanceof PortalError)) return {};
  const out: Record<string, string> = {};
  for (const { field, message } of error.fields) {
    const match = /^lines\[(\d+)\]/.exec(field);
    const itemId = match ? itemIds[Number(match[1])] : undefined;
    const key = itemId ? `line:${itemId}` : field;
    if (!(key in out)) out[key] = message;
  }
  return out;
}
