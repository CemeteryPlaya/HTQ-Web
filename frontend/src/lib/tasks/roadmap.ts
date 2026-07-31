import type { TFunction } from 'i18next';

import type {
    BlockProgress, BlockStatus, ResourceComparison, RoadmapStatus,
    ScheduleComparison, WorkVolumeUnit,
} from '@/types/tasks';

/**
 * Словари роудмапа и блока — та же форма и то же обоснование, что у
 * `lib/tasks/project.ts` и `lib/tasks/status.ts`: тип `Record<Union, …>`
 * превращает добавление значения в ошибку компиляции у каждого потребителя,
 * а не в тихий провал к цвету по умолчанию.
 */
export interface RoadmapStatusMeta {
    badgeClass: string;
    hex: string;
    labelKey: string;
    /** Пакет в работе прямо сейчас. */
    isOpen: boolean;
}

/** Палитра повторяет проектную: роудмап — та же ось планирования уровнем ниже. */
export const ROADMAP_STATUS: Record<RoadmapStatus, RoadmapStatusMeta> = {
    active: {
        badgeClass: 'bg-violet-600 text-white',
        hex: '#7c3aed',
        labelKey: 'tasks.roadmaps.status.active',
        isOpen: true,
    },
    completed: {
        badgeClass: 'bg-green-500 text-white',
        hex: '#22c55e',
        labelKey: 'tasks.roadmaps.status.completed',
        isOpen: false,
    },
    archived: {
        badgeClass: 'bg-gray-400 text-white',
        hex: '#9ca3af',
        labelKey: 'tasks.roadmaps.status.archived',
        isOpen: false,
    },
};

export const ROADMAP_STATUS_ORDER: readonly RoadmapStatus[] = [
    'active', 'completed', 'archived',
] as const;

export function normalizeRoadmapStatus(
    raw: string | null | undefined,
): RoadmapStatus {
    // hasOwnProperty, не `in`: `in` ходит по цепочке прототипов, и
    // 'toString' прошёл бы как валидный статус.
    return raw && Object.prototype.hasOwnProperty.call(ROADMAP_STATUS, raw)
        ? (raw as RoadmapStatus)
        : 'active';
}

export const roadmapStatusMeta = (
    raw: string | null | undefined,
): RoadmapStatusMeta => ROADMAP_STATUS[normalizeRoadmapStatus(raw)];

export const roadmapStatusBadgeClass = (
    raw: string | null | undefined,
): string => roadmapStatusMeta(raw).badgeClass;

export const roadmapStatusLabel = (
    raw: string | null | undefined,
    t: TFunction | ((key: string, fallback?: string) => string),
): string => {
    const status = normalizeRoadmapStatus(raw);
    return (t as (key: string, fallback?: string) => string)(
        ROADMAP_STATUS[status].labelKey, status,
    );
};

/* ---------- Блоки объекта ---------- */

export interface BlockStatusMeta {
    badgeClass: string;
    hex: string;
    labelKey: string;
    isOpen: boolean;
}

export const BLOCK_STATUS: Record<BlockStatus, BlockStatusMeta> = {
    planned: {
        badgeClass: 'bg-slate-400 text-white',
        hex: '#94a3b8',
        labelKey: 'tasks.blocks.status.planned',
        isOpen: true,
    },
    active: {
        badgeClass: 'bg-blue-600 text-white',
        hex: '#2563eb',
        labelKey: 'tasks.blocks.status.active',
        isOpen: true,
    },
    suspended: {
        badgeClass: 'bg-amber-500 text-white',
        hex: '#f59e0b',
        labelKey: 'tasks.blocks.status.suspended',
        isOpen: true,
    },
    done: {
        badgeClass: 'bg-green-500 text-white',
        hex: '#22c55e',
        labelKey: 'tasks.blocks.status.done',
        isOpen: false,
    },
};

export const BLOCK_STATUS_ORDER: readonly BlockStatus[] = [
    'planned', 'active', 'suspended', 'done',
] as const;

export function normalizeBlockStatus(
    raw: string | null | undefined,
): BlockStatus {
    return raw && Object.prototype.hasOwnProperty.call(BLOCK_STATUS, raw)
        ? (raw as BlockStatus)
        : 'planned';
}

export const blockStatusMeta = (
    raw: string | null | undefined,
): BlockStatusMeta => BLOCK_STATUS[normalizeBlockStatus(raw)];

export const blockStatusBadgeClass = (
    raw: string | null | undefined,
): string => blockStatusMeta(raw).badgeClass;

export const blockStatusLabel = (
    raw: string | null | undefined,
    t: TFunction | ((key: string, fallback?: string) => string),
): string => {
    const status = normalizeBlockStatus(raw);
    return (t as (key: string, fallback?: string) => string)(
        BLOCK_STATUS[status].labelKey, status,
    );
};

/* ---------- Единицы измерения объёмов ---------- */

export const VOLUME_UNIT_LABEL: Record<WorkVolumeUnit, string> = {
    piece: 'шт',
    meter: 'м',
    sq_meter: 'м²',
    ton: 'т',
};

export const volumeUnitLabel = (raw: string | null | undefined): string =>
    (raw && Object.prototype.hasOwnProperty.call(VOLUME_UNIT_LABEL, raw))
        ? VOLUME_UNIT_LABEL[raw as WorkVolumeUnit]
        : '';

/* ---------- План против факта ---------- */

/**
 * Как показать расхождение план/факт.
 *
 * `neutral` — не «нулевое расхождение», а «сравнивать не с чем»: план не
 * заводили. Рисовать это как «уложились» значило бы врать, поэтому у
 * состояния отдельное имя.
 */
export type VarianceTone = 'neutral' | 'under' | 'onTrack' | 'over';

export const varianceTone = (delta: number | null | undefined): VarianceTone => {
    if (delta === null || delta === undefined) return 'neutral';
    if (delta > 0) return 'over';
    if (delta < 0) return 'under';
    return 'onTrack';
};

export const VARIANCE_CLASS: Record<VarianceTone, string> = {
    neutral: 'text-muted-foreground',
    under: 'text-blue-600 dark:text-blue-400',
    onTrack: 'text-green-600 dark:text-green-400',
    over: 'text-red-600 dark:text-red-400',
};

/** `+3` / `−2` / `—`. Знак нужен: без него «2» не читается как отставание. */
export const formatDelta = (delta: number | null | undefined): string => {
    if (delta === null || delta === undefined) return '—';
    if (delta === 0) return '0';
    // U+2212 minus, не дефис: в таблице чисел дефис визуально теряется.
    return delta > 0 ? `+${delta}` : `−${Math.abs(delta)}`;
};

/** Уложился ли пакет в плановый срок. `null` — плана нет. */
export const isOverSchedule = (schedule: ScheduleComparison): boolean | null =>
    schedule.delta_working_days === null ? null : schedule.delta_working_days > 0;

/** Не хватает ли ресурса против плана. `null` — плана нет. */
export const isUnderResourced = (row: ResourceComparison): boolean | null =>
    row.delta === null ? null : row.delta < 0;

/**
 * Процент выполнения блока к показу. `null` остаётся `null` — «объёмы не
 * заданы» и «не сделано ничего» это разные состояния, и второе рисуется
 * нулевой полосой, а первое прочерком.
 */
export const blockPercent = (progress: BlockProgress | undefined): number | null =>
    progress?.percent ?? null;
