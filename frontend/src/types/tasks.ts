/* ------------------------------------------------------------------ */
/*  Tasks module — shared types                                        */
/* ------------------------------------------------------------------ */

/* ---------- Labels ---------- */
export interface Label {
  id: number;
  name: string;
  color: string;
}

/* ---------- Projects (Roadmap) ---------- */
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
  /** Optional roadmap project. null = "standalone" — first-class state. */
  project: number | null;
  project_name?: string | null;
  project_color?: string | null;
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

  created_at: string;
  updated_at: string;
}

/* ---------- Resource planning (Gantt) ---------- */
export type ResourceKind = 'employee' | 'equipment';

export interface Equipment {
  id: number;
  name: string;
  inventory_no: string | null;
  category: string | null;
  is_active: boolean;
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

export interface Assignment {
  id: number;
  task_id: number;
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
