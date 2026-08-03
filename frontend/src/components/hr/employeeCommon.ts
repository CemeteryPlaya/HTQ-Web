/**
 * Форма сотрудника в понимании HR-UI + хелперы разбора связей.
 *
 * Общий модуль для страницы-списка (`pages/hr/HREmployees.tsx`) и формы
 * (`components/hr/EmployeeFormDialog.tsx`): раньше `Employee` был объявлен
 * локально в странице и ТЕНИЛ одноимённый импорт из `@/types/hr` — при
 * разделении на два файла дублировать эту путаницу нельзя.
 */

export interface Employee {
  id: number;
  // Backend EmployeeOut: ``user_id`` is the platform-user link.
  user_id?: number | null;
  // Legacy alias retained for older endpoints — read both when present.
  user?: number | null;
  // Names live separately on the backend; older responses sometimes
  // synthesised ``full_name`` — keep it optional as a fallback.
  first_name?: string;
  last_name?: string;
  middle_name?: string | null;
  full_name?: string;
  username?: string;
  email: string;
  // EmployeeOut returns ``position_id`` + nested ``position: {id, title}``.
  position_id?: number | null;
  position?: { id: number; title: string } | number | null;
  position_title?: string;
  department_id?: number | null;
  department?: { id: number; name: string } | number | null;
  department_name?: string;
  phone?: string;
  // EmployeeOut: ``hire_date`` / ``termination_date``. Older endpoints used
  // ``date_hired``/``date_dismissed`` — accept either.
  hire_date?: string | null;
  date_hired?: string | null;
  termination_date?: string | null;
  date_dismissed?: string | null;
  status: string;
  notes?: string;
  bio?: string;
  // Скалярные поля Т-2 (оклад, паспорт, СРО…) НЕ живут на Employee: они уехали
  // на отдельную модель EmployeeCard со своим эндпойнтом
  // `PATCH /hr/v1/employees/{id}/card/t2` и посекционным RBAC. Правятся на
  // карточке сотрудника (HREmployeeCard + CardT2SectionDialog) — сюда их
  // возвращать нельзя: POST/PUT /employees/ их не принимает и молча потеряет.
  // Synced from user-service via the replica worker; absent on bare-skeleton
  // employees that aren't linked to a platform user yet.
  avatar_url?: string | null;
}

/** Pull the int id from a relation that may arrive as either a flat int
 * or a nested ``{id, ...}`` object (depends on the endpoint version). */
export const relationId = (rel: unknown): number | null => {
  if (rel == null) return null;
  if (typeof rel === 'number') return rel;
  if (typeof rel === 'object' && 'id' in (rel as any)) return Number((rel as any).id);
  return null;
};

export const relationLabel = (rel: unknown, key: 'title' | 'name'): string => {
  if (rel && typeof rel === 'object' && key in (rel as any)) {
    return String((rel as any)[key] || '');
  }
  return '';
};
