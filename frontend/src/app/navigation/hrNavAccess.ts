/**
 * Видимость пунктов кадровой навигации — по правам, а не по кадровому уровню.
 *
 * ЗАЧЕМ. До задачи 10 блока I `HRLayout` и `ProfileSidebar` вели каждый свою
 * таблицу «маршрут → уровни junior/middle/senior/lead» поверх `useHRLevel`, и
 * таблицы уже разошлись (у сайдбара не было трети пунктов). Теперь правило
 * одно, а уровень как понятие ушёл: пункт ведёт на экран, и виден он тому,
 * кому на этом экране есть что делать, — ровно тем, что он спросит у
 * `usePermissions` (`/access/v1/me`).
 *
 * Предикат выбран по СМЫСЛУ экрана, а не по формальному соответствию
 * уровней (правило задачи: `level === 'lead'` ≠ `can('hr.x', 'delete')`):
 * - экран считает конкретный узел реестра — тот же узел, что проверяет
 *   бэкенд (`backend/apps/hr/legacy_roles.py::KEY_TO_NODE`): учётные записи
 *   (`hr.accounts`), заявки на идентичность (`hr.identity_requests`),
 *   штатка (`hr.staffing`), календарь (`hr.production_calendar`);
 * - экран правит справочник — `edit` на его узле (отделы, должности);
 * - у экрана нет своего узла ни в одной роли (подбор, учёт времени) —
 *   уровень модуля `write`, которым он открывался и раньше (middle);
 * - экран «по всей компании» (архив, PMO, история, публичные ссылки) —
 *   `write` с областью `company`: разница middle/senior в старой модели
 *   была ОБЛАСТЬЮ выдачи, а не признаком (решение 1 у `EMPLOYEES_VIEW_ALL`
 *   в `legacy_roles.py`), и `usePermissions().scope('hr')` — она и есть.
 *
 * Скрытие здесь — удобство, а не защита: рубеж стоит на бэкенде и на гейте
 * маршрута (`app/routing/routeDefinitions.ts`, все `/hr/*` под `hr:read`).
 * Соответствие четырём засеянным ролям (`access/migrations/0005`, `0008`)
 * закреплено тестом `hrNavAccess.test.ts`.
 */
import type { Permissions } from '@/hooks/usePermissions';

type Visible = (perm: Permissions) => boolean;

/** Любой кадровый доступ — модуль `hr` есть в карте. */
const anyHrAccess: Visible = (p) => p.atLeast('hr', 'read');

/** Пишет хоть что-то в кадрах (старый middle и выше). */
const hrWrite: Visible = (p) => p.atLeast('hr', 'write');

/** Пишет по ВСЕЙ компании, а не в своём отделе (старый senior и выше). */
const companyWideWrite: Visible = (p) =>
  p.atLeast('hr', 'write') && p.scope('hr')?.kind === 'company';

export const HR_NAV_VISIBLE: Record<string, Visible> = {
  // ── Персонал
  '/hr/employees': anyHrAccess,
  // Список учётных записей отдаёт `USERS_LIST` → `hr.accounts: view`
  // (apps/hr/views.py). Старая таблица держала пункт за одним lead, но
  // senior уже видел его с задачи 8 (роль hr-senior несёт delete на
  // оргструктуре и агрегируется в `admin`) — и по праву: список ему открыт.
  '/hr/accounts': (p) => p.can('hr.accounts', 'view'),
  '/hr/identity-requests': (p) => p.can('hr.identity_requests', 'view'),
  '/hr/recruitment': hrWrite,
  // Архив — уволенные по всей компании; область «свой отдел» его не видит.
  '/hr/archive': companyWideWrite,

  // ── Организация
  '/hr/departments': (p) => p.can('hr.departments', 'edit'),
  '/hr/positions': (p) => p.can('hr.positions', 'edit'),
  '/hr/org-chart': anyHrAccess,
  '/hr/pmo': companyWideWrite,

  // ── Учёт и время
  '/hr/time-tracking': hrWrite,
  '/hr/production-calendar': (p) => p.can('hr.production_calendar', 'view'),
  '/hr/staffing': (p) => p.can('hr.staffing', 'view'),
  '/hr/documents': anyHrAccess,

  // ── История и сервис
  '/hr/share-links': companyWideWrite,
  '/hr/history': companyWideWrite,
};

/**
 * Виден ли пункт с этим маршрутом. Маршрут без правила — ошибка
 * программиста, а не «скрыть на всякий случай»: молчаливое `false` спрятало
 * бы новый экран от всех, и заметили бы это не скоро.
 */
export function hrNavVisible(perm: Permissions, route: string): boolean {
  const rule = HR_NAV_VISIBLE[route];
  if (rule === undefined) {
    throw new Error(`hrNavVisible: для маршрута ${route} не задано правило видимости`);
  }
  return rule(perm);
}
