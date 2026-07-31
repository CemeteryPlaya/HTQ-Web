import type { TFunction } from 'i18next';

import type { Project, ProjectStatus } from '@/types/tasks';

/**
 * The one description of a project status the frontend has.
 *
 * Same shape and reasoning as `lib/tasks/status.ts`: typing the table as
 * `Record<ProjectStatus, …>` makes adding a status a compile error in every
 * consumer instead of a silent fallthrough to a default colour. The palette
 * is lifted verbatim from the copy that used to live inside HRRoadmap, so
 * nothing changes visually on the roadmap.
 */
export interface ProjectStatusMeta {
    /** Solid badge — project cards, roadmap rows, detail header. */
    badgeClass: string;
    /** Fill for SVG and recharts, should a project ever reach a chart. */
    hex: string;
    /** i18next key; both ru and en already carry all three. */
    labelKey: string;
    /** The project is being worked on right now. */
    isOpen: boolean;
}

export const PROJECT_STATUS: Record<ProjectStatus, ProjectStatusMeta> = {
    active: {
        badgeClass: 'bg-blue-600 text-white',
        hex: '#2563eb',
        labelKey: 'tasks.projects.status.active',
        isOpen: true,
    },
    completed: {
        badgeClass: 'bg-green-500 text-white',
        hex: '#22c55e',
        labelKey: 'tasks.projects.status.completed',
        isOpen: false,
    },
    archived: {
        badgeClass: 'bg-gray-400 text-white',
        hex: '#9ca3af',
        labelKey: 'tasks.projects.status.archived',
        isOpen: false,
    },
};

/** Declaration order for selectors and filters. */
export const PROJECT_STATUS_ORDER: readonly ProjectStatus[] = [
    'active', 'completed', 'archived',
] as const;

/**
 * Unknown values fall back to `active` rather than throwing — a project in
 * the wrong bucket is recoverable, a blank list is not. Mirrors
 * `normalizeTaskStatus`.
 */
export function normalizeProjectStatus(
    raw: string | null | undefined,
): ProjectStatus {
    // hasOwnProperty, not `in`: `in` walks the prototype chain, so `'toString'`
    // and `'constructor'` would pass as valid statuses and then index the
    // table to a function whose `.badgeClass` is undefined.
    return raw && Object.prototype.hasOwnProperty.call(PROJECT_STATUS, raw)
        ? (raw as ProjectStatus)
        : 'active';
}

export const projectStatusMeta = (
    raw: string | null | undefined,
): ProjectStatusMeta => PROJECT_STATUS[normalizeProjectStatus(raw)];

export const projectStatusBadgeClass = (
    raw: string | null | undefined,
): string => projectStatusMeta(raw).badgeClass;

export const projectStatusLabel = (
    raw: string | null | undefined,
    t: TFunction | ((key: string, fallback?: string) => string),
): string => {
    const status = normalizeProjectStatus(raw);
    return (t as (key: string, fallback?: string) => string)(
        PROJECT_STATUS[status].labelKey, status,
    );
};

/**
 * A project with no objects cannot hand one down to its tasks.
 *
 * `site_service.resolve_task_site` treats "project has no sites" as "any
 * site goes", so such a project silently opts out of the whole
 * project→object→task axis: the task form falls back to the full object
 * directory and nobody is told why. The UI surfaces this as a hint rather
 * than a block — see the customer decision in the plan.
 */
export const projectNeedsSites = (project: Pick<Project, 'sites'>): boolean =>
    (project.sites?.length ?? 0) === 0;

/** The object a task should inherit when the project leaves it unset. */
export const primarySite = (project: Pick<Project, 'sites'>) =>
    project.sites?.find((site) => site.is_primary) ?? project.sites?.[0] ?? null;
