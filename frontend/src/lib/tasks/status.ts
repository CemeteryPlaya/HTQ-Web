import type { TFunction } from 'i18next';

import type { TaskStatus } from '@/types/tasks';

/**
 * The one description of a task status the frontend has.
 *
 * There used to be eight copies. Five agreed with the backend; three —
 * HRReports, GanttChart and ResourceGantt — described a vocabulary that has
 * never existed in this Django backend at all (`open` / `closed`, with no
 * `backlog`, `todo`, `blocked` or `cancelled`). The consequences were not
 * cosmetic: the "In progress" tile silently omitted `todo`/`backlog`/
 * `blocked`, "Completed" omitted `cancelled`, the status pie labelled four
 * real statuses with their raw keys in a fallback colour, and the status
 * filter on the Gantt tab offered two values that match nothing, so it
 * always came back empty.
 *
 * Typing the table as `Record<TaskStatus, …>` is the point: adding a status
 * to `TaskStatus` now fails compilation in every consumer instead of
 * quietly falling through to a default somewhere.
 */
export interface TaskStatusMeta {
    /** Solid badge — task lists, detail headers, roadmap rows. */
    badgeClass: string;
    /** Tinted Kanban column background. */
    columnClass: string;
    /** Fill for SVG and recharts — Gantt bars, pie slices, legends. */
    hex: string;
    /** i18next key; both ru and en already carry all seven. */
    labelKey: string;
    /** Work has stopped for good: done or cancelled. */
    isTerminal: boolean;
    /** Work is under way: in progress, in review, or blocked. */
    isActive: boolean;
}

export const TASK_STATUS: Record<TaskStatus, TaskStatusMeta> = {
    backlog: {
        badgeClass: 'bg-slate-400 text-white',
        columnClass: 'bg-slate-100 dark:bg-slate-900/40 border-slate-300/40',
        hex: '#94a3b8',
        labelKey: 'tasks.pages.list.status.backlog',
        isTerminal: false,
        isActive: false,
    },
    todo: {
        badgeClass: 'bg-slate-600 text-white',
        columnClass: 'bg-slate-100 dark:bg-slate-900/40 border-slate-300/40',
        // Inherited from the retired `open`, so existing charts keep their colour.
        hex: '#64748b',
        labelKey: 'tasks.pages.list.status.todo',
        isTerminal: false,
        isActive: false,
    },
    in_progress: {
        badgeClass: 'bg-blue-600 text-white',
        columnClass: 'bg-blue-50 dark:bg-blue-950/30 border-blue-300/40',
        hex: '#3b82f6',
        labelKey: 'tasks.pages.list.status.in_progress',
        isTerminal: false,
        isActive: true,
    },
    in_review: {
        badgeClass: 'bg-purple-500 text-white',
        columnClass: 'bg-purple-50 dark:bg-purple-950/30 border-purple-300/40',
        hex: '#a855f7',
        labelKey: 'tasks.pages.list.status.in_review',
        isTerminal: false,
        isActive: true,
    },
    blocked: {
        badgeClass: 'bg-red-500 text-white',
        columnClass: 'bg-red-50 dark:bg-red-950/30 border-red-300/40',
        hex: '#ef4444',
        labelKey: 'tasks.pages.list.status.blocked',
        isTerminal: false,
        isActive: true,
    },
    done: {
        badgeClass: 'bg-green-500 text-white',
        columnClass: 'bg-green-50 dark:bg-green-950/30 border-green-300/40',
        hex: '#22c55e',
        labelKey: 'tasks.pages.list.status.done',
        isTerminal: true,
        isActive: false,
    },
    cancelled: {
        badgeClass: 'bg-gray-600 text-white',
        columnClass: 'bg-gray-100 dark:bg-gray-900/40 border-gray-300/40',
        // Inherited from the retired `closed`.
        hex: '#6b7280',
        labelKey: 'tasks.pages.list.status.cancelled',
        isTerminal: true,
        isActive: false,
    },
};

/** Board order, left to right. Also the order every status selector uses. */
export const TASK_STATUS_ORDER: readonly TaskStatus[] = [
    'backlog', 'todo', 'in_progress', 'in_review', 'blocked', 'done', 'cancelled',
] as const;

const byFlag = (pick: (m: TaskStatusMeta) => boolean): readonly TaskStatus[] =>
    TASK_STATUS_ORDER.filter((s) => pick(TASK_STATUS[s]));

/** done, cancelled */
export const TERMINAL_STATUSES = byFlag((m) => m.isTerminal);
/** in_progress, in_review, blocked */
export const ACTIVE_STATUSES = byFlag((m) => m.isActive);
/** backlog, todo — queued, not started */
export const OPEN_STATUSES = byFlag((m) => !m.isTerminal && !m.isActive);

/**
 * Legacy rows written before the status vocabulary changed still exist in
 * this database — KanbanBoard has been coercing them at render time ever
 * since. Anything unrecognised falls back to `todo` rather than throwing:
 * a card in the wrong column is recoverable, a blank board is not.
 */
export function normalizeTaskStatus(raw: string | null | undefined): TaskStatus {
    // hasOwnProperty, not `in`: `in` walks the prototype chain, so `'toString'`
    // and `'constructor'` would pass as valid statuses and then index the
    // table to a function whose `.badgeClass` is undefined.
    if (raw && Object.prototype.hasOwnProperty.call(TASK_STATUS, raw)) {
        return raw as TaskStatus;
    }
    if (raw === 'open') return 'todo';
    if (raw === 'closed') return 'cancelled';
    return 'todo';
}

export const statusMeta = (raw: string | null | undefined): TaskStatusMeta =>
    TASK_STATUS[normalizeTaskStatus(raw)];

export const statusHex = (raw: string | null | undefined): string =>
    statusMeta(raw).hex;

export const statusBadgeClass = (raw: string | null | undefined): string =>
    statusMeta(raw).badgeClass;

export const statusLabel = (
    raw: string | null | undefined,
    t: TFunction | ((key: string, fallback?: string) => string),
): string => {
    const status = normalizeTaskStatus(raw);
    return (t as (key: string, fallback?: string) => string)(
        TASK_STATUS[status].labelKey, status,
    );
};

/** Sum a `{status: count}` map over a group of statuses. */
export const countStatuses = (
    counts: Record<string, number> | undefined,
    statuses: readonly TaskStatus[],
): number =>
    statuses.reduce((total, status) => total + (counts?.[status] ?? 0), 0);
