import type { TFunction } from 'i18next';

import type { TaskPriority } from '@/types/tasks';

/**
 * Companion to `status.ts` — same reasoning, smaller blast radius. Six
 * files carried identical `PRIORITY_CONFIG` copies; unlike the status
 * copies they all agreed with the backend, so this is a de-duplication,
 * not a bug fix. Typed as `Record<TaskPriority, …>` so a new priority
 * cannot be added without every consumer being told.
 */
export interface TaskPriorityMeta {
    badgeClass: string;
    /** Dot used in selects and table cells. */
    icon: string;
    hex: string;
    labelKey: string;
}

export const TASK_PRIORITY: Record<TaskPriority, TaskPriorityMeta> = {
    critical: {
        badgeClass: 'bg-red-500 text-white',
        icon: '🔴',
        hex: '#ef4444',
        labelKey: 'tasks.pages.list.priority.critical',
    },
    high: {
        badgeClass: 'bg-orange-500 text-white',
        icon: '🟠',
        hex: '#f97316',
        labelKey: 'tasks.pages.list.priority.high',
    },
    medium: {
        badgeClass: 'bg-yellow-500 text-black',
        icon: '🟡',
        hex: '#eab308',
        labelKey: 'tasks.pages.list.priority.medium',
    },
    low: {
        badgeClass: 'bg-blue-500 text-white',
        icon: '🔵',
        hex: '#3b82f6',
        labelKey: 'tasks.pages.list.priority.low',
    },
    trivial: {
        badgeClass: 'bg-gray-400 text-white',
        icon: '⚪',
        hex: '#9ca3af',
        labelKey: 'tasks.pages.list.priority.trivial',
    },
};

/** Most urgent first — the order every priority selector uses. */
export const TASK_PRIORITY_ORDER: readonly TaskPriority[] = [
    'critical', 'high', 'medium', 'low', 'trivial',
] as const;

const FALLBACK: TaskPriority = 'medium';

export function normalizeTaskPriority(
    raw: string | null | undefined,
): TaskPriority {
    // hasOwnProperty, not `in`: `in` walks the prototype chain, so `'toString'`
    // and `'constructor'` would pass as valid priorities and then index the
    // table to a function whose `.hex` is undefined.
    return raw && Object.prototype.hasOwnProperty.call(TASK_PRIORITY, raw)
        ? (raw as TaskPriority)
        : FALLBACK;
}

export const priorityMeta = (raw: string | null | undefined): TaskPriorityMeta =>
    TASK_PRIORITY[normalizeTaskPriority(raw)];

export const priorityHex = (raw: string | null | undefined): string =>
    priorityMeta(raw).hex;

export const priorityLabel = (
    raw: string | null | undefined,
    t: TFunction | ((key: string, fallback?: string) => string),
): string => {
    const priority = normalizeTaskPriority(raw);
    return (t as (key: string, fallback?: string) => string)(
        TASK_PRIORITY[priority].labelKey, priority,
    );
};
