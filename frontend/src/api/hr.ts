/* ------------------------------------------------------------------ */
/*  HR module — API helpers                                            */
/* ------------------------------------------------------------------ */
import api from '@/api/client';
import { API_ENDPOINTS } from '@/api/endpoints';
import type {
  Department, Position, Employee, EmployeeStats, HRUserOption,
  Vacancy, Application,
} from '@/types/hr';

const HR = `${API_ENDPOINTS.hr}/`;

/* Unwrap paginated or plain array response */
function unwrap<T>(data: any): T[] {
  if (Array.isArray(data)) return data;
  if (Array.isArray(data?.results)) return data.results;
  if (Array.isArray(data?.items)) return data.items;
  return [];
}

const EMPLOYEE_FIELD_ALIASES: Record<string, string> = {
  user: 'user_id',
  position: 'position_id',
  department: 'department_id',
  date_hired: 'hire_date',
  date_dismissed: 'termination_date',
  notes: 'bio',
};

function toBackendRecord(data: Record<string, any>, aliases: Record<string, string>): Record<string, any> {
  const payload: Record<string, any> = {};
  Object.entries(data).forEach(([key, value]) => {
    if (value === undefined || value === '') return;
    payload[aliases[key] ?? key] = value;
  });
  return payload;
}

function normalizeEmployee(raw: any): Employee {
  const firstName = raw.first_name ?? '';
  const lastName = raw.last_name ?? '';
  const middleName = raw.middle_name ?? '';
  const fullName = raw.full_name ?? [lastName, firstName, middleName].filter(Boolean).join(' ');

  return {
    ...raw,
    user: raw.user ?? raw.user_id ?? null,
    user_id: raw.user_id ?? raw.user ?? null,
    full_name: fullName,
    position: raw.position ?? raw.position_id ?? null,
    position_id: raw.position_id ?? raw.position ?? null,
    position_title: raw.position_title ?? raw.position?.title ?? null,
    department: raw.department ?? raw.department_id ?? null,
    department_id: raw.department_id ?? raw.department ?? null,
    department_name: raw.department_name ?? raw.department?.name ?? null,
    date_hired: raw.date_hired ?? raw.hire_date ?? null,
    hire_date: raw.hire_date ?? raw.date_hired ?? null,
    date_dismissed: raw.date_dismissed ?? raw.termination_date ?? null,
    termination_date: raw.termination_date ?? raw.date_dismissed ?? null,
    notes: raw.notes ?? raw.bio ?? '',
    bio: raw.bio ?? raw.notes ?? '',
  };
}

/* ---------- Departments ---------- */
export const fetchDepartments = async (): Promise<Department[]> => {
  const res = await api.get(`${HR}departments/`);
  return unwrap<Department>(res.data);
};

export const createDepartment = async (data: Partial<Department>): Promise<Department> => {
  const res = await api.post(`${HR}departments/`, data);
  return res.data;
};

export const updateDepartment = async (id: number, data: Partial<Department>): Promise<Department> => {
  const res = await api.patch(`${HR}departments/${id}/`, data);
  return res.data;
};

export const deleteDepartment = async (id: number): Promise<void> => {
  await api.delete(`${HR}departments/${id}/`);
};

/* ---------- Positions ---------- */
/**
 * Справочник должностей целиком.
 *
 * ``limit`` обязателен: сервер отдаёт постраничный конверт с дефолтом в 20
 * записей, а пагинации ни на одной из четырёх страниц-потребителей нет. Без
 * этого параметра справочник молча обрезался — с 30 должностями страница
 * показывала 20, а селектор должности в карточке сотрудника не предлагал
 * остальные десять, то есть назначить на них было физически нельзя.
 *
 * 200 — потолок, разрешённый схемой (``PositionListQuery.limit`` le=200).
 * Если должностей станет больше, здесь понадобится настоящая пагинация, а
 * не увеличение числа.
 */
export const fetchPositions = async (): Promise<Position[]> => {
  const res = await api.get(`${HR}positions/`, { params: { limit: 200 } });
  return unwrap<Position>(res.data);
};

export const createPosition = async (data: Partial<Position>): Promise<Position> => {
  const res = await api.post(`${HR}positions/`, data);
  return res.data;
};

export const updatePosition = async (id: number, data: Partial<Position>): Promise<Position> => {
  const res = await api.patch(`${HR}positions/${id}/`, data);
  return res.data;
};

export const deletePosition = async (id: number): Promise<void> => {
  await api.delete(`${HR}positions/${id}/`);
};

/* ---------- Employees ---------- */
export const fetchEmployees = async (params?: Record<string, string>): Promise<Employee[]> => {
  const query = params ? '?' + new URLSearchParams(params).toString() : '';
  const res = await api.get(`${HR}employees/${query}`);
  return unwrap<Employee>(res.data).map(normalizeEmployee);
};

export const fetchEmployee = async (id: number): Promise<Employee> => {
  const res = await api.get(`${HR}employees/${id}/`);
  return normalizeEmployee(res.data);
};

export const fetchEmployeeStats = async (): Promise<EmployeeStats> => {
  const res = await api.get(`${HR}employees/stats/`);
  return res.data;
};

export const fetchEmployeeUsers = async (params?: Record<string, string>): Promise<HRUserOption[]> => {
  const query = params ? '?' + new URLSearchParams(params).toString() : '';
  const res = await api.get(`${HR}employees/users/${query}`);
  return unwrap<HRUserOption>(res.data);
};

/**
 * Заводит платформенного пользователя из HR-формы.
 *
 * `password` обязателен (бэкенд отбивает пустой 422). Раньше поля не было, и
 * `apps.users.interface.create_user` генерировал случайный пароль, которого не
 * видел никто: аккаунт существовал, но войти в него было невозможно до
 * админского сброса.
 *
 * `must_change_password` тут НЕ передаётся: на этом маршруте бэкенд ставит его
 * жёстко в true и поля в схеме нет. Пароль назначает HR и видит его открытым,
 * поэтому первый вход сотрудника обязан заканчиваться сменой — гарантия не
 * должна зависеть от того, что пришлёт клиент.
 */
export const createEmployeeUser = async (data: {
  first_name: string;
  last_name: string;
  patronymic?: string;
  email: string;
  password: string;
}): Promise<HRUserOption> => {
  const res = await api.post(`${HR}employees/users/`, data);
  return res.data;
};

export const createEmployee = async (data: Partial<Employee>): Promise<Employee> => {
  const res = await api.post(`${HR}employees/`, toBackendRecord(data as Record<string, any>, EMPLOYEE_FIELD_ALIASES));
  return normalizeEmployee(res.data);
};

export const updateEmployee = async (id: number, data: Partial<Employee>): Promise<Employee> => {
  const res = await api.put(`${HR}employees/${id}/`, toBackendRecord(data as Record<string, any>, EMPLOYEE_FIELD_ALIASES));
  return normalizeEmployee(res.data);
};

/**
 * Создаёт сотрудника вместе с опциональным блоком `card_t2`.
 *
 * Отдельно от `createEmployee`: тот прогоняет тело через
 * `toBackendRecord(..., EMPLOYEE_FIELD_ALIASES)`, который переименовывает
 * ключи по плоской карте алиасов и покалечил бы вложенный объект `card_t2`.
 * Здесь payload собирает вызывающий — ровно в форме бэкендовой
 * `EmployeeCreateRequest`.
 */
export const createEmployeeWithCard = async (payload: Record<string, unknown>): Promise<Employee> => {
  const res = await api.post(`${HR}employees/`, payload);
  return normalizeEmployee(res.data);
};

export const updateEmployeeWithCard = async (
  id: number,
  payload: Record<string, unknown>,
): Promise<Employee> => {
  const res = await api.put(`${HR}employees/${id}/`, payload);
  return normalizeEmployee(res.data);
};

export const deleteEmployee = async (id: number): Promise<void> => {
  await api.delete(`${HR}employees/${id}/`);
};

/* ---------- Employee Card ---------- */
export interface EmployeePmoEntry {
  pmo_id: number;
  pmo_name: string;
  pmo_code: string;
  pmo_status?: string;
  membership_type: string;
  position_in_pmo: string | null;
  allocation_percent: number;
  is_primary: boolean;
  from_date?: string | null;
  to_date?: string | null;
}

export interface EmployeeCardBrief {
  id: number;
  full_name: string;
  first_name: string | null;
  last_name: string | null;
  middle_name: string | null;
  avatar_url: string | null;
  position_title: string | null;
  department_name: string | null;
  status: string;
  email?: string | null;
  phone?: string | null;
}

export interface EmployeeCard {
  id: number;
  user_id: number | null;
  first_name: string | null;
  last_name: string | null;
  middle_name: string | null;
  full_name: string;
  avatar_url: string | null;
  bio: string | null;
  status: string;
  hire_date: string | null;
  termination_date: string | null;
  email: string | null;
  phone: string | null;
  department: { id: number; name: string; path: string } | null;
  position: { id: number; title: string; grade: number; level: number } | null;
  manager: EmployeeCardBrief | null;
  subordinates: EmployeeCardBrief[];
  pmos: EmployeePmoEntry[];
}

export const fetchEmployeeCard = async (id: number): Promise<EmployeeCard> => {
  const res = await api.get<EmployeeCard>(`${HR}employees/${id}/card`);
  return res.data;
};

export const fetchMyEmployeeCard = async (): Promise<EmployeeCard> => {
  const res = await api.get<EmployeeCard>(`${HR}employees/me/card`);
  return res.data;
};

export interface CardT2 {
  financial?: { salary: string | null; bonus: string | null; bank_account: string | null };
  personal?: { passport_data: string | null; inn: string | null; birth_date: string | null; birth_place: string | null; citizenship: string | null };
}

export const fetchCardT2 = async (employeeId: number): Promise<CardT2> => {
  const res = await api.get(`${HR}employees/${employeeId}/card/t2`);
  return res.data;
};

/** Секции Т-2 карточки — совпадают с ключами `EmployeeCardT2Patch` бэкенда. */
export type CardT2Section = 'financial' | 'personal' | 'certs';

/**
 * Пишет ОДНУ секцию Т-2 карточки.
 *
 * Бэкенд (`employee_card_t2_service.upsert`) применяет патч целиком или никак:
 * отказ прав на любой секции откатывает и уже применённые. Поэтому шлём по
 * одной секции за запрос — иначе отказ на «Финансах» молча потерял бы и
 * правки «Личных данных». Строку карточки upsert создаёт сам, если её ещё нет,
 * так что сотруднику не требуется никакой предварительной подготовки.
 *
 * Возвращает секции, видимые вызывающему после записи (ответ эндпойнта).
 */
export const updateCardT2 = async (
  employeeId: number,
  section: CardT2Section,
  values: Record<string, string | null>,
): Promise<CardT2> => {
  const res = await api.patch(`${HR}employees/${employeeId}/card/t2`, { [section]: values });
  return res.data;
};

/* ---------- Employee Share Links ---------- */
export interface EmployeeShareLinkCreateInput {
  employee_id: number;
  label?: string | null;
  viewer_label?: string | null;
  watermark_text?: string | null;
  link_type?: 'one_time' | 'time_limited' | 'permanent_with_expiry';
  expires_at?: string | null;
  default_language?: 'ru' | 'en';
}

export interface ShareLinkCreated {
  id: string;
  token: string;
  url: string;
  expires_at: string | null;
  link_type: string;
  target_type: string;
  target_employee_id: number | null;
}

export const createEmployeeShareLink = async (
  input: EmployeeShareLinkCreateInput,
): Promise<ShareLinkCreated> => {
  const res = await api.post<ShareLinkCreated>(`${HR}share-links/`, {
    target_type: 'employee',
    target_employee_id: input.employee_id,
    label: input.label ?? null,
    viewer_label: input.viewer_label ?? null,
    watermark_text: input.watermark_text ?? null,
    link_type: input.link_type ?? 'one_time',
    expires_at: input.expires_at ?? null,
    default_language: input.default_language ?? 'ru',
    max_level: 10,
  });
  return res.data;
};

/* ---------- Vacancies ---------- */
export const fetchVacancies = async (): Promise<Vacancy[]> => {
  const res = await api.get(`${HR}vacancies/`);
  return unwrap<Vacancy>(res.data);
};

export const createVacancy = async (data: Partial<Vacancy>): Promise<Vacancy> => {
  const res = await api.post(`${HR}vacancies/`, data);
  return res.data;
};

export const updateVacancy = async (id: number, data: Partial<Vacancy>): Promise<Vacancy> => {
  const res = await api.patch(`${HR}vacancies/${id}/`, data);
  return res.data;
};

export const deleteVacancy = async (id: number): Promise<void> => {
  await api.delete(`${HR}vacancies/${id}/`);
};

/* ---------- Applications ---------- */
export const fetchApplications = async (params?: Record<string, string>): Promise<Application[]> => {
  const query = params ? '?' + new URLSearchParams(params).toString() : '';
  const res = await api.get(`${HR}applications/${query}`);
  return unwrap<Application>(res.data);
};

export const createApplication = async (data: FormData): Promise<Application> => {
  const res = await api.post(`${HR}applications/`, data, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return res.data;
};

export const updateApplication = async (id: number, data: Partial<Application>): Promise<Application> => {
  const res = await api.patch(`${HR}applications/${id}/`, data);
  return res.data;
};

export const deleteApplication = async (id: number): Promise<void> => {
  await api.delete(`${HR}applications/${id}/`);
};

/* ---------- Time Tracking / Documents / Action Logs ----------
 * Хелперов здесь больше нет. Табель и документы страницы зовут напрямую
 * через `api` (см. pages/hr/HRTimeTracking.tsx, pages/hr/HRDocuments.tsx):
 * прежние обёртки писались под старый Django-монолит и били в маршруты,
 * которых в этом бэкенде нет (`time-tracking/{id}/`, `.../approve|reject`),
 * а их единственными потребителями были неподключённые страницы-дубли
 * из `src/pages/` — удалены вместе с ними.
 */

/* ---------- Production Calendar ---------- */
export interface WeekTemplate { id: number; name: string; is_default: boolean; days: Record<string, { type: string; hours: number }>; }
export interface CalendarDay { day: string; type: string; hours: number; note?: string | null; }

export const fetchWeekTemplates = async (): Promise<WeekTemplate[]> =>
  (await api.get(`${HR}calendar/templates`)).data;
export const createWeekTemplate = async (name: string, days: WeekTemplate['days']): Promise<WeekTemplate> =>
  (await api.post(`${HR}calendar/templates`, { name, days })).data;
export const setDefaultTemplate = async (id: number): Promise<WeekTemplate> =>
  (await api.post(`${HR}calendar/templates/${id}/default`)).data;
export const fetchCalendarYear = async (year: number): Promise<CalendarDay[]> =>
  (await api.get(`${HR}calendar/`, { params: { year } })).data;
export const upsertCalendarDay = async (day: string, data: { day_type: string; norm_hours: number; note?: string | null }) =>
  (await api.put(`${HR}calendar/${day}`, data)).data;
export const assignEmployeeTemplate = async (employeeId: number, week_template_id: number | null) =>
  (await api.put(`${HR}employees/${employeeId}/calendar-template`, { week_template_id })).data;

/* ---------- Shift Patterns ---------- */
export interface ShiftPattern { id: number; name: string; holidays_off: boolean; slots: { type: string; hours: number }[]; }

export const fetchShiftPatterns = async (): Promise<ShiftPattern[]> =>
  (await api.get(`${HR}calendar/shift-patterns`)).data;
export const createShiftPattern = async (name: string, slots: ShiftPattern['slots'], holidays_off: boolean): Promise<ShiftPattern> =>
  (await api.post(`${HR}calendar/shift-patterns`, { name, slots, holidays_off })).data;
export const deleteShiftPattern = async (id: number): Promise<void> => { await api.delete(`${HR}calendar/shift-patterns/${id}`); };
export const assignEmployeeShift = async (employeeId: number, shift_pattern_id: number, anchor_date: string) =>
  (await api.put(`${HR}employees/${employeeId}/shift`, { shift_pattern_id, anchor_date })).data;
export const setEmployeeDayOverride = async (employeeId: number, day: string, data: { day_type: string; norm_hours: number; note?: string | null }) =>
  (await api.put(`${HR}employees/${employeeId}/calendar/${day}`, data)).data;

/* ---------- Staffing ---------- */
export interface StaffingLine { id: number; position_id: number; department_id: number; grade: number | null; headcount: string; salary: string; fot: string; note?: string | null; }
export interface StaffingSummary { by_department: { department_id: number; department_name: string | null; fot: string }[]; total_fot: string; total_budgeted: string; total_filled: number; total_vacant: string; }

export const fetchStaffingLines = async (): Promise<StaffingLine[]> => (await api.get(`${HR}staffing/`)).data;
export const fetchStaffingSummary = async (): Promise<StaffingSummary> => (await api.get(`${HR}staffing/summary`)).data;
export const deleteStaffingLine = async (id: number): Promise<void> => { await api.delete(`${HR}staffing/${id}`); };

/* ---------- Org chart — ручная правка руководителей/подчинённых ---------- */
/**
 * Не порт: /org/tree — единственный org-запрос, который эта страница делала
 * раньше (inline axios в HROrgChart.tsx). relation_id/origin на рёбрах и
 * manager_source в meta dept-узлов — новые поля бэкенда (org_service.get_org_tree),
 * см. backend/apps/hr/services/org_service.py.
 */
/** Тип связи подчинения — совпадает с RelationType на бэкенде. */
export type RelationType = 'direct' | 'functional' | 'project';

export type OrgEdgeOrigin =
  | 'employee' | 'position' | 'department' | 'inferred'
  | 'structural' | 'membership' | 'employment';

export interface OrgNode {
  id: string;
  label: string;
  type: string;
  unit_type?: string | null;
  level?: number | null;
  weight?: number | null;
  meta?: Record<string, unknown>;
}

export interface OrgEdge {
  source: string;
  target: string;
  relation_type: string;
  relation_id: number | null;
  origin: OrgEdgeOrigin;
}

export interface OrgTree {
  nodes: OrgNode[];
  edges: OrgEdge[];
}

export interface EmployeeRelation {
  id: number;
  superior_employee_id: number;
  subordinate_employee_id: number;
  superior_name: string;
  subordinate_name: string;
  relation_type: string;
  note: string | null;
  created_at: string | null;
}

export interface DepartmentManagerResult {
  department_id: number;
  manager_id: number | null;
  manager_name: string | null;
  manager_position_id: number | null;
  manager_avatar_url: string | null;
}

export const fetchOrgTree = async (params: {
  mode: 'positions' | 'employees' | 'both';
  depth: number;
  lang: 'ru' | 'en';
  rootId?: string;
}): Promise<OrgTree> => {
  const query = new URLSearchParams({
    mode: params.mode, depth: String(params.depth), lang: params.lang,
  });
  if (params.rootId && params.rootId !== 'all') query.append('root_id', params.rootId);
  return (await api.get<OrgTree>(`${HR}org/tree?${query}`)).data;
};

export const createPositionRelation = async (data: {
  superior_position_id: number;
  subordinate_position_id: number;
  relation_type?: 'direct' | 'functional' | 'project';
}) => (await api.post(`${HR}org/relations`, data)).data;

export const deletePositionRelation = async (relationId: number): Promise<void> => {
  await api.delete(`${HR}org/relations/${relationId}`);
};

/**
 * Атомарно: у должности ровно один руководитель данного типа.
 * Заменяет пару DELETE+POST — упавший второй запрос раньше оставлял узел
 * вообще без руководителя. `superior_id: null` — снять и не назначать.
 */
export const setPositionSuperior = async (data: {
  subordinate_id: number;
  superior_id: number | null;
  relation_type?: RelationType;
}) => (await api.put(`${HR}org/relations/superior`, data)).data;

export const changePositionRelationType = async (
  relationId: number, relation_type: RelationType,
) => (await api.patch(`${HR}org/relations/${relationId}`, { relation_type })).data;

export const fetchEmployeeRelations = async (params: {
  employeeId?: number;
  departmentId?: number;
}): Promise<EmployeeRelation[]> => {
  const query: Record<string, string> = {};
  if (params.employeeId != null) query.employee_id = String(params.employeeId);
  if (params.departmentId != null) query.department_id = String(params.departmentId);
  return (await api.get<EmployeeRelation[]>(`${HR}org/employee-relations`, { params: query })).data;
};

export const createEmployeeRelation = async (data: {
  superior_employee_id: number;
  subordinate_employee_id: number;
  relation_type?: 'direct' | 'functional' | 'project';
  note?: string | null;
}): Promise<EmployeeRelation> => (await api.post(`${HR}org/employee-relations`, data)).data;

export const deleteEmployeeRelation = async (relationId: number): Promise<void> => {
  await api.delete(`${HR}org/employee-relations/${relationId}`);
};

/**
 * Персональный аналог `setPositionSuperior`. Для `direct` другого пути нет:
 * частичный unique допускает ровно одного прямого руководителя, поэтому
 * «создать новую, потом удалить старую» невозможно в принципе.
 */
export const setEmployeeSuperior = async (data: {
  subordinate_id: number;
  superior_id: number | null;
  relation_type?: RelationType;
}) => (await api.put(`${HR}org/employee-relations/superior`, data)).data;

export const changeEmployeeRelationType = async (
  relationId: number, relation_type: RelationType,
): Promise<EmployeeRelation> =>
  (await api.patch(`${HR}org/employee-relations/${relationId}`, { relation_type })).data;

export const setDepartmentManager = async (
  departmentId: number, employeeId: number | null,
): Promise<DepartmentManagerResult> =>
  (await api.put(`${HR}org/departments/${departmentId}/manager`, { employee_id: employeeId })).data;

