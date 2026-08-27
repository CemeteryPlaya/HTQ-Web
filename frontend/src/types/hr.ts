/* ------------------------------------------------------------------ */
/*  HR module — shared types                                           */
/* ------------------------------------------------------------------ */

export interface Department {
  id: number;
  name: string;
  description: string;
  created_at: string;
}

export interface Position {
  id: number;
  title: string;
  department: number | null;
  department_id?: number | null;
  department_name: string | null;
  weight?: number;
  level?: number;
  grade?: number;
  is_system?: boolean;
  permissions?: {
    hr_level?: 'junior' | 'middle' | 'senior' | 'lead' | null;
    permissions?: string[];
  } | null;
}

/** Диапазон весов -> уровень иерархии должностей (hr/v1/positions/levels). */
export interface LevelThreshold {
  id: number;
  level_number: number;
  weight_from: number;
  weight_to: number;
  label: string | null;
  color: string | null;
}

/** Ответ hr/v1/positions/levels/{n}/next-weight — подсказка для селекта уровня. */
export interface NextWeightForLevel {
  level_number: number;
  weight: number;
  weight_from: number;
  weight_to: number;
}

export type EmployeeStatus =
  | 'active'
  | 'inactive'
  | 'terminated'
  | 'suspended'
  | 'pending'
  | 'rejected'
  | 'on_leave'
  | 'dismissed';

export interface Employee {
  id: number;
  user: number | null;
  user_id?: number | null;
  first_name?: string;
  last_name?: string;
  middle_name?: string | null;
  full_name: string;
  username?: string;
  email: string;
  position: number | null;
  position_id?: number | null;
  position_title: string | null;
  department: number | null;
  department_id?: number | null;
  department_name: string | null;
  phone: string;
  date_hired: string | null;
  hire_date?: string | null;
  date_dismissed: string | null;
  termination_date?: string | null;
  status: EmployeeStatus;
  notes: string;
  bio?: string | null;
  salary?: string | number | null;
  bonus?: string | number | null;
  passport_data?: string | null;
  bank_account?: string | null;
  avatar_url?: string | null;
  created_at: string;
  updated_at: string;
}

export interface EmployeeStats {
  total: number;
  active: number;
  on_leave: number;
  dismissed: number;
}

export interface HRUserOption {
  id: number;
  full_name: string;
  email: string;
  username?: string;
  first_name?: string;
  last_name?: string;
  patronymic?: string;
  /** Данные для переноса в карточку — их отдаёт GET /employees/users/. */
  phone?: string;
  avatar_url?: string;
  bio?: string;
  /** Карточка сотрудника у этой учётки уже есть; null — ещё нет. */
  employee_id?: number | null;
}

/* ---------- Префилл: перенос уже имеющихся данных в карточку ---------- */

/** Откуда берём данные. Совпадает с SOURCE_* бэкенда. */
export type PrefillSourceType = 'user' | 'employee' | 'mailbox';

export interface PrefillSourceRef {
  type: PrefillSourceType;
  id: number;
}

/**
 * Состояние одного поля в предпросмотре:
 * - `fill`     — у сотрудника пусто, можно просто заполнить (отмечено по умолчанию);
 * - `conflict` — значения расходятся, решает человек (по умолчанию снято);
 * - `same`     — совпадает, переносить нечего.
 */
export type PrefillFieldState = 'fill' | 'conflict' | 'same';

export interface PrefillFieldDiff {
  field: string;
  current: string | number | null;
  incoming: string | number | null;
  /** Человекочитаемые значения: id отделов/должностей уже развёрнуты в названия. */
  current_display: string;
  incoming_display: string;
  state: PrefillFieldState;
}

export interface PrefillPreview {
  source: { type: PrefillSourceType; id: number; title: string; subtitle: string };
  values: Record<string, string | number>;
  fields: PrefillFieldDiff[];
  fillable: number;
  conflicts: number;
}

/** Ящик как источник (GET /employees/sources/mailboxes). */
export interface MailboxSource {
  id: number;
  address: string;
  local_part: string;
  domain: string;
  display_name: string;
  user_id: number | null;
  status: string;
}

export interface UserMatch extends HRUserOption {
  match_on: string[];
  match_kind: 'exact' | 'similar';
}

export interface EmployeeMatch {
  id: number;
  full_name: string;
  email: string;
  phone: string | null;
  user_id: number | null;
  department_name: string;
  position_title: string;
  status: string;
  match_on: string[];
  match_kind: 'exact' | 'similar';
}

/**
 * `employees` — карточка уже есть (заводить второй раз не надо);
 * `users` — карточки нет, но есть учётка (вот откуда взять данные).
 */
export interface MatchSuggestions {
  users: UserMatch[];
  employees: EmployeeMatch[];
}

export interface BulkImportSkipped {
  user_id: number;
  reason: 'user_not_found' | 'no_email' | 'already_linked' | 'email_taken' | 'create_failed';
}

export interface BulkImportResult {
  created: Employee[];
  skipped: BulkImportSkipped[];
  created_count: number;
  skipped_count: number;
}

export type VacancyStatus = 'open' | 'closed' | 'on_hold';

export interface Vacancy {
  id: number;
  title: string;
  department: number | null;
  department_name: string | null;
  description: string;
  requirements: string;
  salary_min: string | null;
  salary_max: string | null;
  status: VacancyStatus;
  created_by: number | null;
  created_by_name: string | null;
  applications_count: number;
  created_at: string;
  updated_at: string;
}

export type ApplicationStatus = 'new' | 'reviewed' | 'interview' | 'offered' | 'rejected' | 'hired';

export interface Application {
  id: number;
  vacancy: number;
  vacancy_title: string;
  first_name: string;
  last_name: string;
  email: string;
  phone: string;
  resume: string | null;
  cover_letter: string;
  status: ApplicationStatus;
  notes: string;
  created_at: string;
  updated_at: string;
}

export type LeaveType = 'vacation' | 'sick_leave' | 'day_off' | 'business_trip' | 'unpaid';
export type LeaveStatus = 'pending' | 'approved' | 'rejected' | 'cancelled';

export interface TimeRecord {
  id: number;
  employee: number;
  employee_name: string;
  leave_type: LeaveType;
  start_date: string;
  end_date: string;
  duration_days: number;
  status: LeaveStatus;
  comment: string;
  approved_by: number | null;
  approved_by_name: string | null;
  created_at: string;
  updated_at: string;
}

export type DocType = 'contract' | 'amendment' | 'order' | 'certificate' | 'other';

/**
 * Документ так, как его отдаёт `GET /api/hr/v1/documents/`
 * (`apps.hr.services.document_service.serialize`).
 *
 * Прежний тип описывал ответ старого Django-монолита: `employee_name`,
 * `file`, `description`, `application*`, `uploaded_by_name`. Ничего этого
 * бэкенд не отдаёт — имена разворачиваются по справочнику сотрудников,
 * описание и ссылка на медиафайл лежат в `metadata`.
 */
export interface HRDocument {
  id: number;
  employee_id: number;
  title: string;
  doc_type: DocType;
  file_path: string;
  file_size: number;
  mime_type: string;
  metadata?: {
    media_file_id?: string;
    original_filename?: string;
    description?: string;
    uploaded_by_user_id?: number;
  } | null;
  uploaded_by: number | null;
  created_at: string;
  updated_at: string;
}

/** Элемент `documents` в ответе `GET /applications/archive/` — урезанная
 * проекция документа (`recruitment_service.archive()`). */
export interface HRArchiveDocument {
  id: number;
  title: string;
  doc_type: DocType;
  employee_id: number;
  created_at: string;
}

/** Элемент `applications` там же: id вакансии без названия, кандидат одной
 * строкой, дата подачи (не обновления). */
export interface HRArchiveApplication {
  id: number;
  vacancy_id: number;
  candidate_name: string;
  candidate_email: string | null;
  status: ApplicationStatus;
  created_at: string;
}

export interface HRArchiveResponse {
  applications: HRArchiveApplication[];
  documents: HRArchiveDocument[];
}

/* ---------- Action Logs ---------- */
export type HRActionType = 'create' | 'update' | 'delete' | 'approve' | 'reject' | 'status_change';
export type HRTargetType = 'employee' | 'department' | 'position' | 'vacancy' | 'application' | 'time_tracking' | 'document';

export interface HRActionLog {
  id: number;
  user: number | null;
  user_name: string;
  employee: number | null;
  employee_name: string | null;
  department: number | null;
  department_name: string | null;
  position: number | null;
  position_title: string | null;
  action: HRActionType;
  target_type: HRTargetType;
  target_id: number | null;
  target_repr: string;
  details: string;
  ip_address: string | null;
  created_at: string;
}

