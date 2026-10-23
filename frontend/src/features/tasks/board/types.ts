/**
 * Канбан-доски — типы ответа `/api/tasks/v1/boards/*` (мастер-план §6.1,
 * этап S1). Колонка — статус задачи (K-02); доска лишь называет и красит
 * колонки по-своему (K-34).
 */
import type { TaskPriority, TaskStatus } from '@/types/tasks';

export type BoardKind = 'personal' | 'department' | 'project';

/** Ключ доски. У личной `id` нет: владелец — всегда тот, кто спрашивает. */
export type BoardKey =
  | { kind: 'personal' }
  | { kind: 'department'; id: number }
  | { kind: 'project'; id: number };

/** Палитра цветов колонок (решение K-34) — токены `--board-color-*`. */
export const BOARD_COLORS = [
  'green', 'yellow', 'orange', 'red', 'purple', 'blue', 'sky', 'lime', 'pink', 'gray',
] as const;
export type BoardColor = (typeof BOARD_COLORS)[number];

export interface ColumnSetting {
  title: string | null;
  color: BoardColor | null;
  hidden: boolean;
}

export type ColumnsSettings = Record<TaskStatus, ColumnSetting>;

export interface CardMember {
  user_id: number;
  role: 'primary' | 'collaborator';
  name: string | null;
  avatar_url: string | null;
}

export interface CardLabel {
  id: number;
  name: string;
  color: string;
}

export interface BoardCard {
  id: number;
  key: string;
  summary: string;
  status: TaskStatus;
  priority: TaskPriority;
  labels: CardLabel[];
  due_date: string | null;
  start_date: string | null;
  completed_at: string | null;
  progress_percent: number;
  has_description: boolean;
  counts: { comments: number; attachments: number; checklist_done: number; checklist_total: number };
  members: CardMember[];
  project: { id: number; name: string; color: string } | null;
  department: { id: number; name: string | null } | null;
  /** Связь с доской отдела: основной отдел, участник, только отправитель. */
  relation: 'own' | 'linked' | 'sent' | null;
  rank: string | null;
  /** «Новая» — только на своей личной доске (K-28). */
  is_new: boolean;
  my_role: 'assignee' | 'supervisor' | 'reporter' | 'delegate' | 'watcher' | null;
  /** Может ли смотрящий двигать карточку между колонками. */
  can_move: boolean;
  /** Полная правка: метки, участники, даты в быстрой правке. */
  can_edit?: boolean;
}

export interface BoardColumn extends ColumnSetting {
  status: TaskStatus;
  count: number;
  cards: BoardCard[];
  has_more: boolean;
}

export interface Board {
  board: {
    kind: BoardKind;
    id: number | null;
    title: string | null;
    color: string | null;
    settings: { columns: ColumnsSettings };
    /** Уведомления о своих задачах доски (K-30); у личной — `null`. */
    notifications_enabled?: boolean | null;
  };
  columns: BoardColumn[];
  can: { admin: boolean; reorder: boolean; create: boolean };
}

export interface BoardsList {
  personal: boolean;
  departments: Array<{
    id: number;
    name: string;
    path: string;
    depth: number;
    source: 'own' | 'managed' | 'all';
    is_active: boolean;
  }>;
  projects: Array<{ id: number; name: string; color: string; project_ref: string | null }>;
}

/** Фильтры доски, как фильтр Trello: внутри группы — «или», между — «и». */
export interface BoardFilters {
  q: string;
  label: string[];        // id меток и 'none'
  member: string[];       // id людей, 'me', 'none'
  due: string[];          // overdue, day, week, month, none
  completion: string[];   // complete, incomplete
  activity: string[];     // 1w, 2w, 4w, stale4w
  new: boolean;
  /** «Скрывать колонки без подходящих карточек» — только вид, на сервер не уходит. */
  hideEmpty: boolean;
}

export const EMPTY_FILTERS: BoardFilters = {
  q: '', label: [], member: [], due: [], completion: [], activity: [], new: false, hideEmpty: false,
};
