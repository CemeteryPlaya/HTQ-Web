/* ------------------------------------------------------------------ */
/*  Tasks module — API helpers                                         */
/* ------------------------------------------------------------------ */
import api from '@/api/client';
import { API_ENDPOINTS } from '@/api/endpoints';
import type {
  Label, Project, Task, TaskComment, TaskAttachment, TaskStats, TaskStatus,
  TaskLink, Notification, TaskAssigneeRef, AssigneeRole, TaskTypeRef,
  Equipment, ResourceGanttResponse, Assignment, Site, ProjectSiteRef,
  Contractor, ContractorWorker, ContractorEngagement,
  Roadmap, RoadmapStatus, RoadmapMetrics, SiteBlock, BlockStatus, BlockVolume,
  BlockProgress, TaskVolume, ResourceRequirement, ReferenceRow,
  WorkVolumeType, WorkVolumeUnit, EquipmentUsage,
  DailyReport, DailyReportBoardRow, DailyReportRevision, PlanFactNode,
  ProjectStaffBoard, ProjectStaffReport, ProjectStaffRevision,
} from '@/types/tasks';
import i18next from '@/i18n';

const BASE = `${API_ENDPOINTS.tasks}/`;

/* Unwrap paginated or plain array response */
function unwrap<T>(data: any): T[] {
  if (Array.isArray(data)) return data;
  if (Array.isArray(data?.results)) return data.results;
  return [];
}

const TASK_FIELD_ALIASES: Record<string, string> = {
  reporter: 'reporter_id',
  assignee: 'assignee_id',
  supervisor: 'supervisor_id',
  department: 'department_id',
  project: 'project_id',
  roadmap: 'roadmap_id',
  site: 'site_id',
  site_block: 'site_block_id',
  contractor: 'contractor_id',
  contractor_worker: 'contractor_worker_id',
  parent: 'parent_id',
};

const ROADMAP_FIELD_ALIASES: Record<string, string> = {
  project: 'project_id',
  // Площадки в теле нет — роудмап живёт на блоке, см. types/tasks.ts.
  site_block: 'site_block_id',
  owner: 'owner_id',
  department: 'department_id',
};

const PROJECT_FIELD_ALIASES: Record<string, string> = {
  department: 'department_id',
  owner: 'owner_id',
};

function toBackendRecord(data: Record<string, any>, aliases: Record<string, string>): Record<string, any> {
  const payload: Record<string, any> = {};
  Object.entries(data).forEach(([key, value]) => {
    if (value === undefined || value === '') return;
    payload[aliases[key] ?? key] = value;
  });
  return payload;
}

function normalizeTask(raw: any): Task {
  return {
    ...raw,
    progress_percent: typeof raw.progress_percent === 'number' ? raw.progress_percent : 0,
    reporter: raw.reporter ?? raw.reporter_id,
    reporter_name: raw.reporter_name,
    assignee: raw.assignee ?? raw.assignee_id ?? null,
    assignee_name: raw.assignee_name,
    supervisor: raw.supervisor ?? raw.supervisor_id ?? null,
    supervisor_name: raw.supervisor_name,
    department: raw.department ?? raw.department_id ?? null,
    department_name: raw.department_name,
    department_ids: Array.isArray(raw.department_ids) ? raw.department_ids : [],
    departments: Array.isArray(raw.departments) ? raw.departments : [],
    project: raw.project ?? raw.project_id ?? null,
    project_name: raw.project_name,
    project_color: raw.project_color,
    roadmap: raw.roadmap ?? raw.roadmap_id ?? null,
    roadmap_name: raw.roadmap_name,
    roadmap_color: raw.roadmap_color,
    site: raw.site ?? raw.site_id ?? null,
    site_name: raw.site_name,
    site_color: raw.site_color,
    site_block: raw.site_block ?? raw.site_block_id ?? null,
    site_block_name: raw.site_block_name,
    contractor: raw.contractor ?? raw.contractor_id ?? null,
    contractor_name: raw.contractor_name,
    contractor_worker: raw.contractor_worker ?? raw.contractor_worker_id ?? null,
    contractor_worker_name: raw.contractor_worker_name,
    parent: raw.parent ?? raw.parent_id ?? null,
    parent_key: raw.parent_key,
    assignees: Array.isArray(raw.assignees) ? raw.assignees : [],
    delegates: Array.isArray(raw.delegates) ? raw.delegates : [],
    watchers: Array.isArray(raw.watchers) ? raw.watchers : [],
    subtasks: Array.isArray(raw.subtasks) ? raw.subtasks.map(normalizeTask) : raw.subtasks,
    volumes: Array.isArray(raw.volumes) ? raw.volumes : undefined,
  };
}

function normalizeRoadmap(raw: any): Roadmap {
  return {
    ...raw,
    planned_working_days: raw.planned_working_days ?? null,
    owner_id: raw.owner_id ?? null,
    department_id: raw.department_id ?? null,
    task_count: raw.task_count ?? 0,
    done_count: raw.done_count ?? 0,
    progress: raw.progress ?? 0,
  };
}

function normalizeProject(raw: any): Project {
  return {
    ...raw,
    owner_id: raw.owner_id ?? null,
    owner_name: raw.owner_name,
    department_id: raw.department_id ?? null,
    department_name: raw.department_name,
    sites: Array.isArray(raw.sites) ? raw.sites : [],
    site_ids: Array.isArray(raw.site_ids) ? raw.site_ids : [],
  };
}

function buildQuery(params?: Record<string, string>, aliases: Record<string, string> = {}): string {
  if (!params) return '';
  const mapped = toBackendRecord(params, aliases);
  return '?' + new URLSearchParams(mapped).toString();
}

/* ---------- Labels ---------- */
export const fetchLabels = async (): Promise<Label[]> => {
  const res = await api.get(`${BASE}labels/`);
  return unwrap<Label>(res.data);
};

export const createLabel = async (data: Partial<Label>): Promise<Label> => {
  const res = await api.post(`${BASE}labels/`, data);
  return res.data;
};

export const updateLabel = async (id: number, data: Partial<Label>): Promise<Label> => {
  const res = await api.patch(`${BASE}labels/${id}/`, data);
  return res.data;
};

export const deleteLabel = async (id: number): Promise<void> => {
  await api.delete(`${BASE}labels/${id}/`);
};

/* ---------- Projects (Roadmap) ---------- */
export const fetchProjects = async (params?: Record<string, string>): Promise<Project[]> => {
  const query = buildQuery(params, PROJECT_FIELD_ALIASES);
  const res = await api.get(`${BASE}projects/${query}`);
  return unwrap<Project>(res.data).map(normalizeProject);
};

export const fetchProject = async (id: number): Promise<Project> => {
  const res = await api.get(`${BASE}projects/${id}/`);
  return normalizeProject(res.data);
};

export const createProject = async (data: Partial<Project>): Promise<Project> => {
  const res = await api.post(`${BASE}projects/`, toBackendRecord(data as Record<string, any>, PROJECT_FIELD_ALIASES));
  return normalizeProject(res.data);
};

export const updateProject = async (id: number, data: Partial<Project>): Promise<Project> => {
  const res = await api.patch(`${BASE}projects/${id}/`, toBackendRecord(data as Record<string, any>, PROJECT_FIELD_ALIASES));
  return normalizeProject(res.data);
};

export const deleteProject = async (id: number): Promise<void> => {
  await api.delete(`${BASE}projects/${id}/`);
};

export const fetchProjectTasks = async (id: number): Promise<Task[]> => {
  const res = await api.get(`${BASE}projects/${id}/tasks/`);
  return unwrap<Task>(res.data).map(normalizeTask);
};

/* ---------- Роудмапы (пакеты работ на объекте) ---------- */
export const fetchRoadmaps = async (params?: {
  project_id?: number;
  /** Фильтр по площадке работает джойном через блок — на бэкенде. */
  site_id?: number;
  block_id?: number;
  status?: RoadmapStatus;
}): Promise<Roadmap[]> => {
  const res = await api.get(`${BASE}roadmaps/`, { params });
  return unwrap<Roadmap>(res.data).map(normalizeRoadmap);
};

export const fetchRoadmap = async (id: number): Promise<Roadmap> => {
  const res = await api.get(`${BASE}roadmaps/${id}/`);
  return normalizeRoadmap(res.data);
};

export const createRoadmap = async (data: Partial<Roadmap>): Promise<Roadmap> => {
  const res = await api.post(
    `${BASE}roadmaps/`,
    toBackendRecord(data as Record<string, any>, ROADMAP_FIELD_ALIASES),
  );
  return normalizeRoadmap(res.data);
};

export const updateRoadmap = async (
  id: number, data: Partial<Roadmap>,
): Promise<Roadmap> => {
  const res = await api.patch(
    `${BASE}roadmaps/${id}/`,
    toBackendRecord(data as Record<string, any>, ROADMAP_FIELD_ALIASES),
  );
  return normalizeRoadmap(res.data);
};

export const deleteRoadmap = async (id: number): Promise<void> => {
  await api.delete(`${BASE}roadmaps/${id}/`);
};

export const fetchRoadmapTasks = async (id: number): Promise<Task[]> => {
  const res = await api.get(`${BASE}roadmaps/${id}/tasks/`);
  return unwrap<Task>(res.data).map(normalizeTask);
};

/** План против факта по трём осям: срок, люди, техника. */
export const fetchRoadmapMetrics = async (id: number): Promise<RoadmapMetrics> => {
  const res = await api.get(`${BASE}roadmaps/${id}/metrics/`);
  return res.data;
};

/* ---------- Блоки объекта и объёмы работ ---------- */
export const fetchSiteBlocks = async (
  siteId: number, params?: { status?: BlockStatus },
): Promise<SiteBlock[]> => {
  const res = await api.get(`${BASE}sites/${siteId}/blocks/`, { params });
  return unwrap<SiteBlock>(res.data);
};

export const fetchSiteBlock = async (id: number): Promise<SiteBlock> => {
  const res = await api.get(`${BASE}blocks/${id}/`);
  return res.data;
};

export const createSiteBlock = async (
  siteId: number, data: Partial<SiteBlock>,
): Promise<SiteBlock> => {
  const res = await api.post(`${BASE}sites/${siteId}/blocks/`, data);
  return res.data;
};

export const updateSiteBlock = async (
  id: number, data: Partial<SiteBlock>,
): Promise<SiteBlock> => {
  const res = await api.patch(`${BASE}blocks/${id}/`, data);
  return res.data;
};

export const deleteSiteBlock = async (id: number): Promise<void> => {
  await api.delete(`${BASE}blocks/${id}/`);
};

/** Замена набора объёмов целиком — сервер разницу не вычисляет. */
export const setBlockVolumes = async (
  blockId: number,
  volumes: Array<{ volume_type_id: number; planned_quantity: number }>,
): Promise<BlockVolume[]> => {
  const res = await api.put(`${BASE}blocks/${blockId}/volumes/`, { volumes });
  return unwrap<BlockVolume>(res.data);
};

/** Выполнение блока в штуках, а не в статусах задач. */
export const fetchBlockProgress = async (id: number): Promise<BlockProgress> => {
  const res = await api.get(`${BASE}blocks/${id}/progress/`);
  return res.data;
};

export const fetchTaskVolumes = async (taskId: number): Promise<TaskVolume[]> => {
  const res = await api.get(`${BASE}tasks/${taskId}/volumes/`);
  return unwrap<TaskVolume>(res.data);
};

export const setTaskVolumes = async (
  taskId: number,
  // Только план. Факт правится ежедневными отчётами и в это тело не
  // приходит — сервер его отсюда и не читает (`set_task_volumes`).
  volumes: Array<{
    volume_type_id: number;
    planned_quantity: number;
  }>,
): Promise<TaskVolume[]> => {
  const res = await api.put(`${BASE}tasks/${taskId}/volumes/`, { volumes });
  return unwrap<TaskVolume>(res.data);
};

/* ---------- Ежедневные отчёты ---------- */
export const fetchTaskDailyReports = async (
  taskId: number,
): Promise<DailyReport[]> => {
  const res = await api.get(`${BASE}tasks/${taskId}/daily-reports/`);
  return unwrap<DailyReport>(res.data);
};

export const fetchRoadmapDailyReports = async (
  roadmapId: number, params?: { date_from?: string; date_to?: string },
): Promise<DailyReport[]> => {
  const res = await api.get(`${BASE}roadmaps/${roadmapId}/daily-reports/`,
                            { params });
  return unwrap<DailyReport>(res.data);
};

/**
 * Сводка «что отчитать за день» — основа страницы «Ежедневка».
 *
 * Один запрос вместо «список задач + карточка каждой»: плановые объёмы
 * приходят только в детальном ответе задачи, и страница на 15 строк стоила
 * бы 16 обращений.
 */
export const fetchDailyReportBoard = async (
  date?: string,
): Promise<DailyReportBoardRow[]> => {
  const res = await api.get(`${BASE}daily-reports/board/`,
                            { params: date ? { date } : undefined });
  return unwrap<DailyReportBoardRow>(res.data);
};

export const createDailyReport = async (
  taskId: number,
  data: {
    work_date: string; quantity: number; volume_type_id?: number;
    headcount?: number | null; comment?: string;
  },
): Promise<DailyReport> => {
  const res = await api.post(`${BASE}tasks/${taskId}/daily-reports/`, data);
  return res.data;
};

export const updateDailyReport = async (
  id: number, data: Partial<Pick<DailyReport,
    'work_date' | 'quantity' | 'headcount' | 'comment'>>,
): Promise<DailyReport> => {
  const res = await api.patch(`${BASE}daily-reports/${id}/`, data);
  return res.data;
};

export const deleteDailyReport = async (id: number): Promise<void> => {
  await api.delete(`${BASE}daily-reports/${id}/`);
};

export const fetchDailyReportRevisions = async (
  id: number,
): Promise<DailyReportRevision[]> => {
  const res = await api.get(`${BASE}daily-reports/${id}/revisions/`);
  return unwrap<DailyReportRevision>(res.data);
};

/* ---------- Отчёты по персоналу проекта ---------- */

/**
 * Проекты, по которым вызывающему разрешено вести численность.
 *
 * Не `fetchProjects()`: роут-гейт фронта (`requiresRole: 'hr'`) шире
 * серверного правила — в токене нет ролей вида `hr_manager`, только
 * `is_staff`/`is_superuser`. Сузить список может лишь сервер, иначе
 * селектор предлагал бы проекты, дающие 403.
 */
export const fetchStaffReportProjects = async (): Promise<Project[]> => {
  const res = await api.get(`${BASE}staff-reports/projects/`);
  return unwrap<Project>(res.data);
};

/**
 * Доска численности проекта на дату: блок × (факт, план, ежедневка).
 *
 * Один запрос вместо «блоки + отчёт каждого + план каждого»: план и сверка
 * с ежедневкой лежат в других таблицах, и страница на 12 блоков стоила бы
 * два десятка обращений.
 */
export const fetchProjectStaffBoard = async (
  projectId: number, date?: string,
): Promise<ProjectStaffBoard> => {
  const res = await api.get(`${BASE}projects/${projectId}/staff-board/`,
                            { params: date ? { date } : undefined });
  return res.data;
};

/**
 * Отчёт целиком — со строками. Доска отдаёт по блоку только свёртку
 * «план против факта», и восстанавливать из неё строки нельзя: роль с
 * нулём людей неотличима там от роли, которая есть только в плане.
 */
export const fetchProjectStaffReport = async (
  reportId: number,
): Promise<ProjectStaffReport> => {
  const res = await api.get(`${BASE}staff-reports/${reportId}/`);
  return res.data;
};

export const createProjectStaffReport = async (
  projectId: number,
  data: {
    site_block_id: number; work_date: string; comment?: string;
    lines: { work_role_id: number; headcount: number }[];
  },
): Promise<ProjectStaffReport> => {
  const res = await api.post(`${BASE}projects/${projectId}/staff-reports/`,
                             data);
  return res.data;
};

export const updateProjectStaffReport = async (
  reportId: number,
  data: {
    work_date?: string; comment?: string;
    lines?: { work_role_id: number; headcount: number }[];
  },
): Promise<ProjectStaffReport> => {
  const res = await api.patch(`${BASE}staff-reports/${reportId}/`, data);
  return res.data;
};

export const deleteProjectStaffReport = async (
  reportId: number,
): Promise<void> => {
  await api.delete(`${BASE}staff-reports/${reportId}/`);
};

export const fetchProjectStaffRevisions = async (
  reportId: number,
): Promise<ProjectStaffRevision[]> => {
  const res = await api.get(`${BASE}staff-reports/${reportId}/revisions/`);
  return unwrap<ProjectStaffRevision>(res.data);
};

/* ---------- План/факт ---------- */

/** `date` — отчётная дата; по умолчанию сервер берёт сегодня. */
export const fetchProjectPlanFact = async (
  projectId: number, params?: { date?: string },
): Promise<PlanFactNode> => {
  const res = await api.get(`${BASE}plan-fact/project/${projectId}/`, { params });
  return res.data;
};

export const fetchRoadmapPlanFact = async (
  roadmapId: number, params?: { date?: string },
): Promise<PlanFactNode> => {
  const res = await api.get(`${BASE}plan-fact/roadmap/${roadmapId}/`, { params });
  return res.data;
};

/* ---------- Учёт задействования техники ---------- */

/**
 * Что занято на дату D + история интервалов. Узел иерархии задаётся ровно
 * одним параметром — бэкенд отказывает (422), если их ноль или больше одного.
 */
export const fetchEquipmentUsage = async (
  scope: { project_id: number } | { site_id: number } | { block_id: number }
    | { roadmap_id: number } | { task_id: number },
  params?: { date?: string; date_from?: string; date_to?: string;
             category_id?: number },
): Promise<EquipmentUsage> => {
  const res = await api.get(`${BASE}equipment-usage/`,
                            { params: { ...scope, ...params } });
  return res.data;
};

/* ---------- Потребность в ресурсах (план количеством) ---------- */
export const fetchResourceRequirements = async (
  target: { task_id: number } | { roadmap_id: number },
): Promise<ResourceRequirement[]> => {
  const res = await api.get(`${BASE}resource-requirements/`, { params: target });
  return unwrap<ResourceRequirement>(res.data);
};

export const createResourceRequirement = async (
  data: Partial<ResourceRequirement>,
): Promise<ResourceRequirement> => {
  const res = await api.post(`${BASE}resource-requirements/`, data);
  return res.data;
};

export const updateResourceRequirement = async (
  id: number, data: Partial<ResourceRequirement>,
): Promise<ResourceRequirement> => {
  const res = await api.patch(`${BASE}resource-requirements/${id}/`, data);
  return res.data;
};

export const deleteResourceRequirement = async (id: number): Promise<void> => {
  await api.delete(`${BASE}resource-requirements/${id}/`);
};

/* ---------- Плоские справочники планирования ---------- */
export const fetchEquipmentCategories = async (
  params?: { active_only?: boolean },
): Promise<ReferenceRow[]> => {
  const res = await api.get(`${BASE}equipment-categories/`, { params });
  return unwrap<ReferenceRow>(res.data);
};

export const fetchWorkRoles = async (
  params?: { active_only?: boolean },
): Promise<ReferenceRow[]> => {
  const res = await api.get(`${BASE}work-roles/`, { params });
  return unwrap<ReferenceRow>(res.data);
};

export const fetchVolumeTypes = async (
  params?: { active_only?: boolean },
): Promise<WorkVolumeType[]> => {
  const res = await api.get(`${BASE}volume-types/`, { params });
  return unwrap<WorkVolumeType>(res.data);
};

export const createEquipmentCategory = async (
  data: { name: string },
): Promise<ReferenceRow> => {
  const res = await api.post(`${BASE}equipment-categories/`, data);
  return res.data;
};

export const createWorkRole = async (
  data: { name: string },
): Promise<ReferenceRow> => {
  const res = await api.post(`${BASE}work-roles/`, data);
  return res.data;
};

export const createVolumeType = async (
  data: { name: string; unit?: WorkVolumeUnit },
): Promise<WorkVolumeType> => {
  const res = await api.post(`${BASE}volume-types/`, data);
  return res.data;
};

/* ---------- Contractors (партнёры) ---------- */
export const fetchContractors = async (params?: {
  status?: string;
  search?: string;
}): Promise<Contractor[]> => {
  const res = await api.get(`${BASE}contractors/`, { params });
  return unwrap<Contractor>(res.data);
};

export const createContractor = async (data: Partial<Contractor>): Promise<Contractor> => {
  const res = await api.post(`${BASE}contractors/`, data);
  return res.data;
};

export const updateContractor = async (
  id: number, data: Partial<Contractor>,
): Promise<Contractor> => {
  const res = await api.patch(`${BASE}contractors/${id}/`, data);
  return res.data;
};

export const deleteContractor = async (id: number): Promise<void> => {
  await api.delete(`${BASE}contractors/${id}/`);
};

export const fetchContractorWorkers = async (
  contractorId: number, activeOnly = true,
): Promise<ContractorWorker[]> => {
  const res = await api.get(`${BASE}contractors/${contractorId}/workers/`, {
    params: { active_only: activeOnly },
  });
  return unwrap<ContractorWorker>(res.data);
};

export const createContractorWorker = async (
  contractorId: number, data: Partial<ContractorWorker>,
): Promise<ContractorWorker> => {
  const res = await api.post(`${BASE}contractors/${contractorId}/workers/`, data);
  return res.data;
};

export const updateContractorWorker = async (
  id: number, data: Partial<ContractorWorker>,
): Promise<ContractorWorker> => {
  const res = await api.patch(`${BASE}contractor-workers/${id}/`, data);
  return res.data;
};

/** Мягкое отключение: исторические задачи ссылаются на человека. */
export const deactivateContractorWorker = async (id: number): Promise<void> => {
  await api.delete(`${BASE}contractor-workers/${id}/`);
};

export const fetchEngagements = async (params?: {
  contractor_id?: number;
  project_id?: number;
  site_id?: number;
  active_only?: boolean;
}): Promise<ContractorEngagement[]> => {
  const res = await api.get(`${BASE}contractor-engagements/`, { params });
  return unwrap<ContractorEngagement>(res.data);
};

export const createEngagement = async (
  data: Partial<ContractorEngagement>,
): Promise<ContractorEngagement> => {
  const res = await api.post(`${BASE}contractor-engagements/`, data);
  return res.data;
};

export const deleteEngagement = async (id: number): Promise<void> => {
  await api.delete(`${BASE}contractor-engagements/${id}/`);
};

/* ---------- Sites (объекты/площадки) ---------- */
export const fetchSites = async (params?: {
  status?: string;
  search?: string;
}): Promise<Site[]> => {
  const res = await api.get(`${BASE}sites/`, { params });
  return unwrap<Site>(res.data);
};

export const fetchSite = async (id: number): Promise<Site> => {
  const res = await api.get<Site>(`${BASE}sites/${id}/`);
  return res.data;
};

export const createSite = async (data: Partial<Site>): Promise<Site> => {
  const res = await api.post(`${BASE}sites/`, data);
  return res.data;
};

export const updateSite = async (id: number, data: Partial<Site>): Promise<Site> => {
  const res = await api.patch(`${BASE}sites/${id}/`, data);
  return res.data;
};

export const deleteSite = async (id: number): Promise<void> => {
  await api.delete(`${BASE}sites/${id}/`);
};

export const fetchSiteTasks = async (id: number): Promise<Task[]> => {
  const res = await api.get(`${BASE}sites/${id}/tasks/`);
  return unwrap<Task>(res.data).map(normalizeTask);
};

export const fetchProjectSites = async (projectId: number): Promise<ProjectSiteRef[]> => {
  const res = await api.get(`${BASE}projects/${projectId}/sites/`);
  return unwrap<ProjectSiteRef>(res.data);
};

/** Замена набора целиком — сервер ждёт полный список, а не разницу. */
export const setProjectSites = async (
  projectId: number,
  siteIds: number[],
  primarySiteId?: number | null,
): Promise<ProjectSiteRef[]> => {
  const res = await api.put(`${BASE}projects/${projectId}/sites/`, {
    site_ids: siteIds,
    primary_site_id: primarySiteId ?? null,
  });
  return unwrap<ProjectSiteRef>(res.data);
};

/* ---------- Task types (registry) ---------- */
export const fetchTaskTypes = async (): Promise<TaskTypeRef[]> => {
  const res = await api.get(`${BASE}task-types/`);
  return unwrap<TaskTypeRef>(res.data);
};

export const createTaskType = async (data: { name: string; slug?: string; color?: string; icon?: string | null }): Promise<TaskTypeRef> => {
  const res = await api.post(`${BASE}task-types/`, data);
  return res.data;
};

export const updateTaskType = async (id: number, data: Partial<{ name: string; color: string; icon: string | null }>): Promise<TaskTypeRef> => {
  const res = await api.patch(`${BASE}task-types/${id}/`, data);
  return res.data;
};

export const deleteTaskType = async (id: number): Promise<void> => {
  await api.delete(`${BASE}task-types/${id}/`);
};

/* ---------- Tasks ---------- */
export const fetchTasks = async (params?: Record<string, string>): Promise<Task[]> => {
  const query = buildQuery(params, TASK_FIELD_ALIASES);
  const res = await api.get(`${BASE}tasks/${query}`);
  return unwrap<Task>(res.data).map(normalizeTask);
};

export const fetchTask = async (id: number): Promise<Task> => {
  const res = await api.get<Task>(`${BASE}tasks/${id}/`);
  return normalizeTask(res.data);
};

export const fetchTaskTransitions = async (id: number): Promise<TaskStatus[]> => {
  const res = await api.get<TaskStatus[]>(`${BASE}tasks/${id}/transitions/`);
  return res.data;
};

export const createTask = async (data: Partial<Task>): Promise<Task> => {
  const res = await api.post(`${BASE}tasks/`, toBackendRecord(data as Record<string, any>, TASK_FIELD_ALIASES));
  return normalizeTask(res.data);
};

export const updateTask = async (id: number, data: Partial<Task>): Promise<Task> => {
  const res = await api.patch(`${BASE}tasks/${id}/`, toBackendRecord(data as Record<string, any>, TASK_FIELD_ALIASES));
  return normalizeTask(res.data);
};

export const deleteTask = async (id: number): Promise<void> => {
  await api.delete(`${BASE}tasks/${id}/`);
};

export const fetchTaskStats = async (params?: Record<string, string>): Promise<TaskStats> => {
  const query = buildQuery(params, TASK_FIELD_ALIASES);
  const res = await api.get(`${BASE}tasks/stats/${query}`);
  return res.data;
};

/* ---------- Multi-assignee / supervisor / delegates / watchers / progress --- */

/** Replace the task's assignee crew (primary + collaborators). */
export const updateTaskAssignees = async (
  taskId: number,
  assignees: Array<{ user_id: number; role: AssigneeRole }>,
): Promise<Task> => {
  const res = await api.patch(`${BASE}tasks/${taskId}/assignees/`, { assignees });
  return normalizeTask(res.data);
};

/** Set or clear the task supervisor (single user). */
export const updateTaskSupervisor = async (
  taskId: number,
  userId: number | null,
): Promise<Task> => {
  const res = await api.patch(`${BASE}tasks/${taskId}/supervisor/`, { user_id: userId });
  return normalizeTask(res.data);
};

/** Grant a user delegate (deputy) rights — supervisor-only on the backend. */
export const addTaskDelegate = async (taskId: number, userId: number): Promise<Task> => {
  const res = await api.post(`${BASE}tasks/${taskId}/delegates/`, { user_id: userId });
  return normalizeTask(res.data);
};

export const removeTaskDelegate = async (taskId: number, userId: number): Promise<Task> => {
  const res = await api.delete(`${BASE}tasks/${taskId}/delegates/${userId}/`);
  return normalizeTask(res.data);
};

/** Follow/unfollow a task (self-subscribe). */
export const watchTask = async (taskId: number): Promise<Task> => {
  const res = await api.post(`${BASE}tasks/${taskId}/watch/`);
  return normalizeTask(res.data);
};

export const unwatchTask = async (taskId: number): Promise<Task> => {
  const res = await api.delete(`${BASE}tasks/${taskId}/watch/`);
  return normalizeTask(res.data);
};

/** Set the progress percent (0..100). */
export const updateTaskProgress = async (
  taskId: number,
  percent: number,
): Promise<Task> => {
  const res = await api.patch(`${BASE}tasks/${taskId}/progress/`, { percent });
  return normalizeTask(res.data);
};

/* ---------- Resource planning (Gantt) ---------- */
export const fetchResourceGantt = async (params: {
  from: string;
  to: string;
  kinds?: string;
  department_id?: number;
  search?: string;
}): Promise<ResourceGanttResponse> => {
  const res = await api.get(`${BASE}reports/resource-gantt`, { params });
  return res.data;
};

export const fetchEquipment = async (
  activeOnly = true,
  params?: { ownership?: string; contractor_id?: number },
): Promise<Equipment[]> => {
  const res = await api.get(`${BASE}equipment/`, {
    params: { active_only: activeOnly, ...params },
  });
  return unwrap<Equipment>(res.data);
};

export const createEquipment = async (data: Partial<Equipment>): Promise<Equipment> => {
  const res = await api.post(`${BASE}equipment/`, data);
  return res.data;
};

export const updateEquipment = async (id: number, data: Partial<Equipment>): Promise<Equipment> => {
  const res = await api.patch(`${BASE}equipment/${id}/`, data);
  return res.data;
};

export const deleteEquipment = async (id: number): Promise<void> => {
  await api.delete(`${BASE}equipment/${id}/`);
};

/* ---------- Task assignments (resources on a task) ---------- */
export const fetchAssignments = async (taskId: number): Promise<Assignment[]> => {
  const res = await api.get(`${BASE}assignments/`, { params: { task_id: taskId } });
  return unwrap<Assignment>(res.data);
};

export const createAssignment = async (data: {
  task_id: number;
  employee_id?: number;
  equipment_id?: number;
  role?: string;
  allocation?: number;
}): Promise<Assignment> => {
  const res = await api.post(`${BASE}assignments/`, data);
  return res.data;
};

export const deleteAssignment = async (id: number): Promise<void> => {
  await api.delete(`${BASE}assignments/${id}/`);
};

export const addTaskComment = async (taskId: number, body: string): Promise<TaskComment> => {
  const res = await api.post(`${BASE}tasks/${taskId}/comments/`, { body });
  return res.data;
};

export const addTaskAttachment = async (taskId: number, file: File): Promise<TaskAttachment> => {
  const formData = new FormData();
  formData.append('file', file);
  const res = await api.post(`${BASE}tasks/${taskId}/attachments/`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return res.data;
};
/* ---------- Task Links ---------- */
export const createTaskLink = async (data: { source: number; target: number; link_type: string }): Promise<TaskLink> => {
  const res = await api.post(`${BASE}task-links/`, data);
  return res.data;
};

export const deleteTaskLink = async (id: number): Promise<void> => {
  await api.delete(`${BASE}task-links/${id}/`);
};

/* ---------- Notifications ---------- */
export const fetchNotifications = async (): Promise<Notification[]> => {
  const res = await api.get(`${BASE}notifications/`);
  return unwrap<Notification>(res.data);
};

export interface NotificationHistoryParams {
  page?: number;
  limit?: number;
  /** "all" omits the filter; "unread" / "read" narrow the query. */
  status?: 'all' | 'unread' | 'read';
  target_type?: string;
}

export const fetchNotificationHistory = async (
  params: NotificationHistoryParams = {},
): Promise<import('@/types/tasks').NotificationsPage> => {
  const q = new URLSearchParams();
  if (params.page) q.append('page', String(params.page));
  if (params.limit) q.append('limit', String(params.limit));
  if (params.status) q.append('status', params.status);
  if (params.target_type) q.append('target_type', params.target_type);
  const res = await api.get<import('@/types/tasks').NotificationsPage>(
    `${BASE}notifications/history/?${q.toString()}`,
  );
  return res.data;
};

export const markNotificationRead = async (id: number): Promise<void> => {
  await api.post(`${BASE}notifications/${id}/mark_read/`);
};

export const markNotificationUnread = async (id: number): Promise<void> => {
  await api.post(`${BASE}notifications/${id}/mark_unread/`);
};

export const markAllNotificationsRead = async (): Promise<void> => {
  await api.post(`${BASE}notifications/mark-all-read/`);
};

export const deleteNotification = async (id: number): Promise<void> => {
  await api.delete(`${BASE}notifications/${id}/`);
};

/**
 * Build the SPA URL for a notification's target. Returns ``null`` when
 * the row has no clickable destination (e.g. system messages without a
 * concrete entity reference).
 */
export const notificationTargetUrl = (
  n: Pick<Notification, 'target_type' | 'target_id' | 'task' | 'verb'>,
): string | null => {
  if (n.target_type === 'task' && n.target_id) return `/tasks/${n.target_id}`;
  if (n.target_type === 'calendar_event' && n.target_id)
    return `/calendar?event=${n.target_id}`;
  if (n.target_type === 'employee' && n.target_id)
    return `/hr/employees/${n.target_id}`;
  if (n.target_type === 'messenger_room' && n.target_id)
    return `/messenger?room=${n.target_id}`;
  if (n.target_type === 'email_message') return `/email`;
  // Legacy: rows that only set the ``task_id`` FK column.
  if (n.task) return `/tasks/${n.task}`;
  // Legacy verb format: pull the entity id out so old rows are still
  // clickable. Patterns we recognise:
  //   calendar_invited:event:<id>:<title>
  //   calendar_updated:event:<id>:<title>
  const verb = n.verb || '';
  const calMatch = verb.match(/^calendar_(?:invited|updated):event:(\d+):/);
  if (calMatch) return `/calendar?event=${calMatch[1]}`;
  return null;
};

/** Human-readable source label rendered as a chip next to the notification. */
export const notificationSourceLabel = (
  n: Pick<Notification, 'target_type' | 'task' | 'verb'>,
): string | null => {
  if (n.target_type === 'task' || n.task) return i18next.t('notifications.source.task');
  if (n.target_type === 'calendar_event') return i18next.t('notifications.source.calendar');
  if (n.target_type === 'employee') return 'HR';
  if (n.target_type === 'messenger_room') return i18next.t('notifications.source.messenger');
  if (n.target_type === 'email_message') return i18next.t('notifications.source.email');
  // Legacy verb fallback — same patterns as notificationTargetUrl.
  const verb = n.verb || '';
  if (/^calendar_(?:invited|updated):event:/.test(verb)) return i18next.t('notifications.source.calendar');
  if (/^task_(?:due|assigned|commented)/.test(verb)) return i18next.t('notifications.source.task');
  return null;
};

/**
 * Convert a notification's ``verb`` (free-form, may be a legacy
 * machine-encoded string like ``calendar_invited:event:42:Совещание``)
 * into a single human-readable sentence ready to render in the UI.
 *
 * New events emitted by the backend already arrive as natural language,
 * so this function is mostly a safety net for historical rows. Once those
 * have aged out the function still trivially returns the verb as-is.
 */
export const formatNotificationText = (n: Pick<Notification, 'verb'>): string => {
  const verb = (n.verb || '').trim();
  if (!verb) return i18next.t('notifications.source.generic');

  // Legacy calendar invite: ``calendar_invited:event:<id>:<title>``
  const calMatch = verb.match(/^calendar_invited:event:\d+:(.+)$/);
  if (calMatch) return i18next.t('notifications.verb.calendarInvited', { title: calMatch[1] });

  const calUpdMatch = verb.match(/^calendar_updated:event:\d+:(.+)$/);
  if (calUpdMatch) return i18next.t('notifications.verb.calendarUpdated', { title: calUpdMatch[1] });

  // Legacy task-deadline verb: ``task_due_2d`` / ``task_due_0d``
  const dueMatch = verb.match(/^task_due_(-?\d+)d$/);
  if (dueMatch) {
    const days = Number(dueMatch[1]);
    if (days === 0) return i18next.t('notifications.verb.dueToday');
    if (days < 0) return i18next.t('notifications.verb.overdue', { days: Math.abs(days) });
    return i18next.t('notifications.verb.dueIn', { days });
  }

  // Legacy chat-notification verbs that still mention "прислал" — drop the
  // preamble so all UI surfaces read uniformly. New rows already arrive
  // without this prefix.
  const chatLegacy = verb.match(
    /^прислал(?:\s+(?:в чате «[^»]*»|сообщение))?:\s*(.+)$/,
  );
  if (chatLegacy) return chatLegacy[1].trim();

  return verb;
};
