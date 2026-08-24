/* ------------------------------------------------------------------ */
/*  Tasks module — shared types                                        */
/* ------------------------------------------------------------------ */

/* ---------- Labels ---------- */
export interface Label {
  id: number;
  name: string;
  color: string;
}

/* ---------- Contractors (партнёры) ---------- */
export type ContractorStatus = 'active' | 'suspended' | 'blacklisted' | 'archived';

/**
 * Уровень допуска представителя партнёра. Пока только хранится и
 * показывается: правами он начнёт управлять вместе с учётными записями,
 * которых у партнёров на этом этапе нет.
 */
export type ContractorLevel = 'junior' | 'middle' | 'senior';

export interface Contractor {
  id: number;
  name: string;
  short_name: string | null;
  bin_iin: string | null;
  contact_person: string | null;
  phone: string | null;
  email: string | null;
  address: string | null;
  notes: string;
  status: ContractorStatus;
  /** См. API: количество активных работников и привлечений. */
  workers_count?: number;
  engagements_count?: number;
  created_at: string;
  updated_at: string;
}

export interface ContractorWorker {
  id: number;
  contractor_id: number;
  contractor_name: string;
  last_name: string;
  first_name: string;
  middle_name: string | null;
  full_name: string;
  phone: string | null;
  email: string | null;
  position_title: string | null;
  level: ContractorLevel;
  /** Заготовка под будущий вход — API его не выставляет. */
  user_id: number | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface ContractorEngagement {
  id: number;
  contractor_id: number;
  contractor_name: string;
  project_id: number | null;
  project_name: string | null;
  site_id: number | null;
  site_name: string | null;
  /** Привлечение на один пакет работ: «развозку отдали партнёру». */
  roadmap_id: number | null;
  roadmap_name: string | null;
  contract_no: string | null;
  scope: string;
  start_date: string | null;
  end_date: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

/* ---------- Sites (объекты/площадки) ---------- */
export type SiteStatus = 'active' | 'suspended' | 'closed';

/** Объект работ — «Алга», «Сазаган». */
export interface Site {
  id: number;
  name: string;
  code: string | null;
  description: string;
  address: string | null;
  region: string | null;
  latitude: number | null;
  longitude: number | null;
  status: SiteStatus;
  color: string;
  department_id: number | null;
  manager_id: number | null;
  created_at: string;
  updated_at: string;
}

/** Объект в карточке проекта — только то, что нужно для чипа. */
export interface ProjectSiteRef {
  id: number;
  name: string;
  color: string;
  status: SiteStatus;
  is_primary: boolean;
  start_date: string | null;
  end_date: string | null;
}

/* ---------- Блоки объекта и объёмы работ ---------- */

/** Единица измерения объёма — принадлежит ВИДУ работ, не строке объёма. */
export type WorkVolumeUnit = 'piece' | 'meter' | 'sq_meter' | 'ton';

/** Строка плоского справочника: типы техники, роли, виды объёмов. */
export interface ReferenceRow {
  id: number;
  slug: string;
  name: string;
  is_active: boolean;
}

export interface WorkVolumeType extends ReferenceRow {
  unit: WorkVolumeUnit;
}

export type BlockStatus = 'planned' | 'active' | 'suspended' | 'done';

/** Плановый объём: 250 валов на блок. Факт живёт на задачах. */
export interface BlockVolume {
  id: number;
  volume_type_id: number;
  volume_type_name: string;
  unit: WorkVolumeUnit;
  planned_quantity: number;
}

/** Блок (участок) объекта: у Сазагана это блок 1, блок 2, … */
export interface SiteBlock {
  id: number;
  site_id: number;
  name: string;
  code: string | null;
  order: number;
  status: BlockStatus;
  start_date: string | null;
  end_date: string | null;
  volumes: BlockVolume[];
  created_at: string;
  updated_at: string;
}

/** Объём задачи: сколько запланировано и сколько уже сделано. */
export interface TaskVolume extends BlockVolume {
  task_id: number;
  completed_quantity: number;
}

export interface BlockProgressItem {
  volume_type_id: number;
  volume_type_name: string;
  unit: WorkVolumeUnit;
  planned_quantity: number;
  completed_quantity: number;
  /** null — план нулевой: делить не на что, и 0% читалось бы как «не начинали». */
  percent: number | null;
}

export interface BlockProgress {
  block_id: number;
  items: BlockProgressItem[];
  percent: number | null;
}

/* ---------- Роудмап: пакет работ на объекте ---------- */
export type RoadmapStatus = 'active' | 'completed' | 'archived';

/**
 * Уровень между блоком и задачей: «развозка валов трекерных конструкций».
 * ``planned_*`` — план, введённый руками; факт считает `/roadmaps/:id/metrics`
 * свёрткой задач и нигде не хранится.
 */
export interface Roadmap {
  id: number;
  project_id: number;
  project_name: string;
  /** Блок, на котором идёт пакет работ. Уровень между площадкой и задачей. */
  site_block_id: number;
  site_block_name: string;
  /** Площадка — производная от блока; своей колонки у роудмапа нет. */
  site_id: number;
  site_name: string;
  site_color: string;
  name: string;
  description: string;
  status: RoadmapStatus;
  color: string;
  order: number;
  planned_start_date: string | null;
  planned_end_date: string | null;
  planned_working_days: number | null;
  owner_id: number | null;
  owner_name?: string | null;
  department_id: number | null;
  department_name?: string | null;
  task_count: number;
  done_count: number;
  /** Дешёвый прогресс по статусам — для карточки в списке. */
  progress: number;
  created_at: string;
  updated_at: string;
}

export interface ScheduleComparison {
  planned_start_date: string | null;
  planned_end_date: string | null;
  planned_working_days: number | null;
  actual_start_date: string | null;
  actual_end_date: string | null;
  actual_working_days: number | null;
  /** > 0 — не уложились. null — сравнивать не с чем. */
  delta_working_days: number | null;
}

export interface ResourceComparison {
  /** null — потребность не заводили. Это не «запланировали ноль». */
  planned: number | null;
  actual: number;
  delta: number | null;
}

export interface RoadmapMetrics {
  roadmap_id: number;
  task_count: number;
  done_count: number;
  /** Считается по объёмам, если они есть; иначе по статусам. */
  progress: number | null;
  schedule: ScheduleComparison;
  human: ResourceComparison;
  equipment: ResourceComparison;
}

/* ---------- Ежедневные отчёты ---------- */

/**
 * Отчёт о выполненном за смену.
 *
 * `work_date` — дата ВЫПОЛНЕНИЯ работ, её ставит человек. `created_at` —
 * дата заполнения, её ставит система. Отчёт за пятницу заполняют в
 * понедельник, и всё, что строится по дням, обязано класть его на пятницу.
 */
export interface DailyReport {
  id: number;
  task_id: number;
  task_key: string;
  volume_type_id: number;
  volume_type_name: string;
  unit: WorkVolumeUnit;
  author_id: number | null;
  author_name: string | null;
  work_date: string;
  quantity: number;
  headcount: number | null;
  comment: string;
  current_revision: number;
  created_at: string;
  updated_at: string;
}

/** Плановый объём строки сводки вместе с фактом НА выбранную дату. */
export interface DailyReportBoardVolume {
  volume_type_id: number;
  volume_type_name: string;
  unit: WorkVolumeUnit;
  planned_quantity: number;
  /** Нарастающим итогом к выбранной дате, а не «всего». */
  completed_quantity: number;
}

/** Строка страницы «Ежедневка»: задача, куда вписывать сегодняшнюю выработку. */
export interface DailyReportBoardRow {
  task_id: number;
  key: string;
  summary: string;
  status: TaskStatus;
  project_name: string | null;
  site_name: string | null;
  site_block_name: string | null;
  roadmap_id: number | null;
  roadmap_name: string | null;
  due_date: string | null;
  volumes: DailyReportBoardVolume[];
  /** Отчёты за выбранный день — их может быть несколько (смены). */
  reports: DailyReport[];
}

/** Снимок отчёта на момент версии — «аналог Git». */
export interface DailyReportRevision {
  id: number;
  report_id: number;
  revision_no: number;
  work_date: string;
  quantity: number;
  headcount: number | null;
  comment: string;
  edited_by_id: number | null;
  edited_by_name: string | null;
  edited_at: string;
}

/* ---------- Отчёты по персоналу проекта ---------- */

/** Строка отчёта: сколько людей одной роли вышло на блок. */
export interface ProjectStaffLine {
  work_role_id: number;
  work_role_name: string;
  headcount: number;
}

/**
 * Отчёт по персоналу: сколько людей и каких ролей стояло на блоке в день.
 *
 * Вторая ось факта рядом с `DailyReport`. Та отвечает «сколько сделано»,
 * эта — «сколькими людьми». `work_date` — дата ВЫХОДА людей, `created_at` —
 * дата заполнения формы.
 */
export interface ProjectStaffReport {
  id: number;
  project_id: number;
  project_name: string;
  site_id: number;
  site_name: string;
  site_block_id: number;
  site_block_name: string;
  work_date: string;
  author_id: number | null;
  author_name: string | null;
  comment: string;
  total_headcount: number;
  lines: ProjectStaffLine[];
  current_revision: number;
  created_at: string;
  updated_at: string;
}

/**
 * Роль в строке блока. `work_role_id === null` — плановая потребность без
 * указанной роли; `planned === null` — плана по роли нет, сравнивать не с чем.
 */
export interface ProjectStaffRoleRow {
  work_role_id: number | null;
  work_role_name: string;
  planned: number | null;
  actual: number;
}

/**
 * Блок проекта на выбранную дату. Строка есть у каждого блока, даже без
 * отчёта (`report_id === null`) — страница отвечает и на «где не отчитались».
 *
 * `daily_headcount` — сумма `DailyReport.headcount` по задачам блока за ту же
 * дату. Это сверка, а не источник: в ежедневке headcount необязателен.
 */
export interface ProjectStaffBoardBlock {
  site_id: number;
  site_name: string;
  site_block_id: number;
  site_block_name: string;
  report_id: number | null;
  total_headcount: number;
  planned_headcount: number | null;
  delta: number | null;
  daily_headcount: number;
  comment: string;
  roles: ProjectStaffRoleRow[];
}

export interface ProjectStaffBoard {
  project_id: number;
  project_name: string;
  date: string;
  total_actual: number;
  total_planned: number | null;
  total_daily: number;
  blocks: ProjectStaffBoardBlock[];
}

/** Снимок отчёта по персоналу — со строками внутри. */
export interface ProjectStaffRevision {
  id: number;
  report_id: number;
  revision_no: number;
  work_date: string;
  comment: string;
  total_headcount: number;
  lines: ProjectStaffLine[];
  edited_by_id: number | null;
  edited_by_name: string | null;
  edited_at: string;
}

/* ---------- План/факт с прогнозом ---------- */

/**
 * Точка S-кривой. Оба поля nullable и значат разное: `plan_cum === null` —
 * плана или объёмов нет; `fact_cum === null` — точка после отчётной даты,
 * где факта физически нет.
 */
export interface SCurvePoint {
  date: string;
  plan_cum: number | null;
  fact_cum: number | null;
}

export type PlanFactKind = 'project' | 'site' | 'block' | 'roadmap' | 'task';

/**
 * Узел дерева план/факт — одна форма на все уровни иерархии.
 *
 * `null` в числах означает «сравнивать не с чем», а не ноль: плана нет,
 * темпа нет, задач нет. Рисовать это нулём значило бы объявить работу
 * просроченной там, где её просто не планировали.
 */
export interface PlanFactNode {
  kind: PlanFactKind;
  id: number;
  name: string;

  plan_start_date: string | null;
  plan_end_date: string | null;
  plan_pct: number | null;
  fact_pct: number | null;
  /** Факт / план. < 0.95 — warning, < 0.90 — critical. */
  spi: number | null;
  /** Прогноз по фактическому темпу и по плановому; разница — цена бездействия. */
  forecast_end: string | null;
  forecast_end_plan_rate: string | null;
  lag_days: number | null;
  lag_pct: number | null;
  flags: string[];

  weighting: string | null;
  children: PlanFactNode[];
  series: SCurvePoint[];

  /** Уровень задачи. */
  key?: string | null;
  status?: TaskStatus | null;
  planned_quantity?: number | null;
  fact_quantity?: number | null;
  rate_per_day?: number | null;
  rate_window_days?: number | null;
  required_rate_ratio?: number | null;
  /** Уровень роудмапа/проекта. */
  task_count?: number | null;
  use_production_calendar?: boolean | null;
}

/* ---------- Учёт задействования техники ---------- */

/** Категория техники на дату D: сколько нужно и сколько выделено. */
export interface EquipmentEngagedRow {
  category_id: number | null;
  category_name: string | null;
  planned: number;
  assigned: number;
}

/** Интервал занятости конкретной машины — строка истории. */
export interface EquipmentUsageRow {
  allocation_id: number;
  equipment_id: number;
  equipment_name: string;
  inventory_no: string | null;
  category_id: number | null;
  category_name: string | null;
  task_id: number | null;
  task_key: string | null;
  task_summary: string | null;
  roadmap_id: number | null;
  date_from: string;
  date_to: string;
  days: number;
}

export interface EquipmentUsage {
  engaged_on: string;
  engaged: EquipmentEngagedRow[];
  history: EquipmentUsageRow[];
}

/* ---------- Ресурсы: план количеством + факт именами ---------- */

/**
 * Вид ресурса в ПОТРЕБНОСТИ. Не `ResourceKind` ниже: у строки ресурсного
 * Ганта это `'employee' | 'equipment'` (там речь о конкретном человеке), а
 * здесь `'human'` — про количество людей, безымянное. Значения разные,
 * поэтому и типы разные, а не один на двоих.
 */
export type RequirementKind = 'human' | 'equipment';

/** Потребность количеством: «2 человека», «2 кары». */
export interface ResourceRequirement {
  id: number;
  task_id: number | null;
  roadmap_id: number | null;
  kind: RequirementKind;
  work_role_id: number | null;
  work_role_name: string | null;
  equipment_category_id: number | null;
  equipment_category_name: string | null;
  quantity: number;
  /** Сколько мест закрыто именными назначениями: «2 кары, назначена 1». */
  filled: number;
  start_date: string | null;
  end_date: string | null;
  note: string | null;
}

/* ---------- Projects ---------- */
export type ProjectStatus = 'active' | 'completed' | 'archived';

export interface Project {
  id: number;
  name: string;
  description: string;
  status: ProjectStatus;
  color: string;
  start_date: string | null;
  end_date: string | null;
  owner_id: number | null;
  owner_name?: string | null;
  department_id: number | null;
  department_name?: string | null;
  sites: ProjectSiteRef[];
  site_ids: number[];
  /**
   * Чем меряются длительности плана и факта. `false` (по умолчанию) —
   * календарные дни: стройка идёт 7/7. `true` — рабочие по
   * производственному календарю, режим для офисных проектов.
   */
  use_production_calendar: boolean;
  task_count: number;
  done_count: number;
  progress: number;
  created_at: string;
  updated_at: string;
}

/* ---------- Task types (DB-backed) ---------- */
export interface TaskTypeRef {
  id: number;
  slug: string;
  name: string;
  color: string;
  icon?: string | null;
  is_system: boolean;
  created_at: string;
  updated_at: string;
}

/* ---------- Tasks ---------- */
export type TaskPriority = 'critical' | 'high' | 'medium' | 'low' | 'trivial';

/**
 * Type slug. Was a closed union when the column was a PG enum; is now
 * an open ``string`` because the ``task_types`` table is user-extensible
 * (custom types like ``maintenance``, ``onboarding`` are first-class).
 */
export type TaskTypeSlug = string;

/**
 * Workflow statuses — Jira-flavoured 7-step workflow. See
 * services/task/app/models/task.py for the FSM (TRANSITIONS).
 *
 * Legacy 'open' / 'closed' values are auto-migrated to 'todo' /
 * 'cancelled' by migration 012, but the union here intentionally
 * excludes them so the type system catches any UI code that still
 * tries to render the legacy states.
 */
export type TaskStatus =
  | 'backlog'
  | 'todo'
  | 'in_progress'
  | 'in_review'
  | 'blocked'
  | 'done'
  | 'cancelled';
/** Historical closed enum kept ONLY to type-check the seeded five system
 * rows (TYPE_ICONS lookup in the UI). Use ``TaskTypeSlug`` (open string)
 * everywhere else. */
export type TaskType = 'task' | 'bug' | 'story' | 'epic' | 'subtask';

/** Role of a user on a task — see task_assignees table. */
export type AssigneeRole = 'primary' | 'collaborator';

export interface TaskAssigneeRef {
  user_id: number;
  role: AssigneeRole;
  name?: string | null;
  avatar_url?: string | null;
}

export interface TaskDelegateRef {
  user_id: number;
  name?: string | null;
  avatar_url?: string | null;
  granted_by_id?: number | null;
  granted_by_name?: string | null;
  granted_at?: string | null;
}

export interface TaskWatcherRef {
  user_id: number;
  name?: string | null;
  avatar_url?: string | null;
}

export interface TaskComment {
  id: number;
  task: number;
  author: number | null;
  author_name: string | null;
  body: string;
  created_at: string;
  updated_at: string;
}

export interface TaskAttachment {
  id: number;
  task: number;
  file: string;
  filename: string;
  uploaded_by: number | null;
  uploaded_by_name: string | null;
  created_at: string;
}

export interface TaskActivity {
  id: number;
  task: number;
  actor: number | null;
  actor_name: string | null;
  field_name: string;
  old_value: string | null;
  new_value: string | null;
  created_at: string;
}

export type TaskLinkType = 'blocks' | 'is_blocked_by' | 'relates_to' | 'duplicates';

export interface TaskLink {
  id: number;
  source: number;
  target: number;
  link_type: TaskLinkType;
  source_key: string;
  source_summary: string;
  target_key: string;
  target_summary: string;
  created_by: number | null;
  created_at: string;
}

export type NotificationTargetType =
  | 'task'
  | 'calendar_event'
  | 'employee'
  | string
  | null;

export interface Notification {
  id: number;
  recipient: number;
  actor: number | null;
  actor_name: string | null;
  actor_avatar_url?: string | null;
  verb: string;
  task: number | null;
  task_key: string | null;
  target_type: NotificationTargetType;
  target_id: number | null;
  is_read: boolean;
  read_at: string | null;
  created_at: string;
}

export interface NotificationsPage {
  items: Notification[];
  total: number;
  page: number;
  pages: number;
  limit: number;
  unread_total: number;
}

export interface Task {
  id: number;
  key: string;
  summary: string;
  description: string;
  /** Slug from task_types table — open string so user-defined types work. */
  task_type: TaskTypeSlug;
  task_type_id?: number | null;
  task_type_name?: string | null;
  task_type_color?: string | null;
  priority: TaskPriority;
  status: TaskStatus;
  progress_percent: number;
  reporter: number;
  reporter_name?: string;
  /** Primary assignee — denormalized; source of truth is `assignees[]`. */
  assignee: number | null;
  assignee_name?: string;
  /** Supervisor (single user). May be null while task is unowned. */
  supervisor: number | null;
  supervisor_name?: string;
  department: number | null;
  department_name?: string;
  /** Full department set (multi-department tasks). `department` is the primary. */
  department_ids?: number[];
  departments?: Array<{ id: number; name: string }>;
  /** Проект — верхний уровень. null = "standalone", first-class state. */
  project: number | null;
  project_name?: string | null;
  project_color?: string | null;
  /**
   * Пакет работ. Задаёт проект и объект задачи: выбрал роудмап — они
   * следуют из него, а не проверяются против него. null законен для
   * исторических и офисных задач.
   */
  roadmap: number | null;
  roadmap_name?: string | null;
  roadmap_color?: string | null;
  /** Объект работ. null законен: у исторических задач его нет и не будет. */
  site: number | null;
  site_name?: string | null;
  site_color?: string | null;
  /** Блок объекта — «на блок I». Только у задачи; у роудмапа блока нет. */
  site_block: number | null;
  site_block_name?: string | null;
  /** Кто выполняет. Оба null = своя команда. */
  contractor: number | null;
  contractor_name?: string | null;
  /**
   * Кто РЕАЛЬНО выполняет: своё значение или унаследованное с роудмапа /
   * площадки / проекта. null = своя команда. Рядом с `contractor`
   * намеренно — «назначен лично» и «унаследован» это разные факты.
   */
  effective_contractor?: { id: number; name: string } | null;
  contractor_worker: number | null;
  contractor_worker_name?: string | null;
  parent: number | null;
  parent_key?: string;
  labels: Label[];
  label_ids?: number[];
  /** Full assignee crew (primary + collaborators). */
  assignees: TaskAssigneeRef[];
  /** Supervisor's deputies — can edit on supervisor's behalf. */
  delegates?: TaskDelegateRef[];
  /** Followers / watchers. */
  watchers?: TaskWatcherRef[];
  due_date: string | null;
  start_date: string | null;
  effective_start_date?: string | null;
  effective_due_date?: string | null;
  date_warnings?: Array<{ code: string; message: string }>;
  completed_at: string | null;

  comments?: TaskComment[];
  attachments?: TaskAttachment[];
  subtasks?: Partial<Task>[];
  activities?: TaskActivity[];
  outgoing_links?: TaskLink[];
  incoming_links?: TaskLink[];
  /** Объёмы работ: «развезти 250 валов», из них сделано 180. */
  volumes?: TaskVolume[];

  created_at: string;
  updated_at: string;
}

/* ---------- Resource planning (Gantt) ---------- */
export type ResourceKind = 'employee' | 'equipment';

export type EquipmentOwnership = 'own' | 'contractor' | 'rented';

export interface Equipment {
  id: number;
  name: string;
  inventory_no: string | null;
  /**
   * Название категории строкой — форма контракта не менялась, но за ней
   * теперь справочник. Для выпадающего списка бери `category_id`.
   */
  category: string | null;
  category_id: number | null;
  is_active: boolean;
  ownership: EquipmentOwnership;
  contractor_id: number | null;
  contractor_name: string | null;
}

export interface AllocatedTask {
  task_id: string;
  key: string;
  title: string;
  start_date: string | null;
  end_date: string | null;
  progress: number;
  status: TaskStatus;
  allocation: number;
}

export interface ResourceRow {
  resource_id: string;
  resource_kind: ResourceKind;
  resource_name: string;
  meta: Record<string, unknown>;
  allocated_tasks: AllocatedTask[];
}

export interface ResourceGanttResponse {
  range: { from: string; to: string };
  resources: ResourceRow[];
}

/** Именное назначение: конкретный человек или машина на задачу ИЛИ пакет. */
export interface Assignment {
  id: number;
  /** null у назначения на роудмап — у него задачи нет. */
  task_id: number | null;
  roadmap_id: number | null;
  /** Плановая потребность, которую закрывает это назначение. */
  requirement_id: number | null;
  employee_id: number | null;
  equipment_id: number | null;
  role: string | null;
  allocation: number;
}

/* ---------- Task Stats (Reports) ---------- */
export interface TaskStats {
  total: number;
  by_status: Record<string, number>;
  by_priority: Record<string, number>;
  by_type: Record<string, number>;
  by_department: Array<{ department__id: number; department__name: string; count: number }>;
  by_project: Array<{ project__id: number | null; project__name: string; count: number }>;
  by_site: Array<{
    site__id: number | null;
    site__name: string;
    site__color: string | null;
    count: number;
  }>;
  by_assignee: Array<{
    assignee__id: number;
    assignee__first_name: string;
    assignee__last_name: string;
    assignee__username: string;
    count: number;
  }>;
  created_per_day: Array<{ day: string; count: number }>;
  resolved_per_day: Array<{ day: string; count: number }>;
}
