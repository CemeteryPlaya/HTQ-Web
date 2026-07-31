import { describe, expect, it } from 'vitest';

import {
    BLOCK_STATUS,
    BLOCK_STATUS_ORDER,
    ROADMAP_STATUS,
    ROADMAP_STATUS_ORDER,
    VARIANCE_CLASS,
    blockPercent,
    blockStatusBadgeClass,
    blockStatusLabel,
    formatDelta,
    isOverSchedule,
    isUnderResourced,
    normalizeBlockStatus,
    normalizeRoadmapStatus,
    roadmapStatusBadgeClass,
    roadmapStatusLabel,
    varianceTone,
    volumeUnitLabel,
} from './roadmap';
import type { ScheduleComparison } from '@/types/tasks';

const t = (key: string, fallback?: string) => `${key}|${fallback ?? ''}`;

const schedule = (delta: number | null): ScheduleComparison => ({
    planned_start_date: null,
    planned_end_date: null,
    planned_working_days: null,
    actual_start_date: null,
    actual_end_date: null,
    actual_working_days: null,
    delta_working_days: delta,
});

describe('ROADMAP_STATUS', () => {
    it('покрывает ровно те три статуса, что есть в бэкенде', () => {
        expect([...ROADMAP_STATUS_ORDER]).toEqual(['active', 'completed', 'archived']);
        expect(Object.keys(ROADMAP_STATUS).sort())
            .toEqual([...ROADMAP_STATUS_ORDER].sort());
    });

    it('неизвестный статус не роняет таблицу, а падает в active', () => {
        expect(normalizeRoadmapStatus('нет такого')).toBe('active');
        expect(normalizeRoadmapStatus(null)).toBe('active');
        expect(roadmapStatusBadgeClass('мусор')).toBe(ROADMAP_STATUS.active.badgeClass);
    });

    it('не принимает свойства прототипа за статус', () => {
        // `in` пропустил бы 'toString' и проиндексировал таблицу функцией,
        // у которой .badgeClass это undefined.
        expect(normalizeRoadmapStatus('toString')).toBe('active');
        expect(normalizeRoadmapStatus('constructor')).toBe('active');
    });

    it('подписывает статус через i18n-ключ', () => {
        expect(roadmapStatusLabel('completed', t))
            .toBe('tasks.roadmaps.status.completed|completed');
    });
});

describe('BLOCK_STATUS', () => {
    it('покрывает ровно те четыре статуса, что есть в бэкенде', () => {
        expect([...BLOCK_STATUS_ORDER])
            .toEqual(['planned', 'active', 'suspended', 'done']);
        expect(Object.keys(BLOCK_STATUS).sort())
            .toEqual([...BLOCK_STATUS_ORDER].sort());
    });

    it('новый блок по умолчанию planned, как и в модели', () => {
        expect(normalizeBlockStatus(undefined)).toBe('planned');
        expect(blockStatusBadgeClass('мусор')).toBe(BLOCK_STATUS.planned.badgeClass);
    });

    it('сданным считается только done', () => {
        const open = BLOCK_STATUS_ORDER.filter((s) => BLOCK_STATUS[s].isOpen);
        expect([...open]).toEqual(['planned', 'active', 'suspended']);
    });

    it('подписывает статус через i18n-ключ', () => {
        expect(blockStatusLabel('done', t)).toBe('tasks.blocks.status.done|done');
    });
});

describe('volumeUnitLabel', () => {
    it('переводит единицы измерения', () => {
        expect(volumeUnitLabel('piece')).toBe('шт');
        expect(volumeUnitLabel('ton')).toBe('т');
        expect(volumeUnitLabel('sq_meter')).toBe('м²');
    });

    it('неизвестная единица — пустая строка, а не «undefined» в вёрстке', () => {
        expect(volumeUnitLabel('parsec')).toBe('');
        expect(volumeUnitLabel(null)).toBe('');
    });
});

describe('varianceTone', () => {
    it('различает «плана нет» и «расхождения нет»', () => {
        // Ровно та ошибка, ради которой заведён отдельный тон: без него
        // ненаписанный план рисовался бы как «уложились».
        expect(varianceTone(null)).toBe('neutral');
        expect(varianceTone(0)).toBe('onTrack');
        expect(VARIANCE_CLASS.neutral).not.toBe(VARIANCE_CLASS.onTrack);
    });

    it('перерасход и недобор — разные тона', () => {
        expect(varianceTone(3)).toBe('over');
        expect(varianceTone(-3)).toBe('under');
    });

    it('на каждый тон есть класс', () => {
        (['neutral', 'under', 'onTrack', 'over'] as const).forEach((tone) => {
            expect(VARIANCE_CLASS[tone]).toBeTruthy();
        });
    });
});

describe('formatDelta', () => {
    it('всегда со знаком — иначе «2» не читается как отставание', () => {
        expect(formatDelta(2)).toBe('+2');
        expect(formatDelta(-2)).toBe('−2');
        expect(formatDelta(0)).toBe('0');
    });

    it('отсутствие плана показывает прочерком, а не нулём', () => {
        expect(formatDelta(null)).toBe('—');
        expect(formatDelta(undefined)).toBe('—');
    });
});

describe('сравнение плана и факта', () => {
    it('срок: положительная дельта это выход за план', () => {
        expect(isOverSchedule(schedule(4))).toBe(true);
        expect(isOverSchedule(schedule(-4))).toBe(false);
        expect(isOverSchedule(schedule(0))).toBe(false);
    });

    it('срок без плана — null, а не false', () => {
        expect(isOverSchedule(schedule(null))).toBeNull();
    });

    it('ресурсы: отрицательная дельта это нехватка', () => {
        expect(isUnderResourced({ planned: 2, actual: 1, delta: -1 })).toBe(true);
        expect(isUnderResourced({ planned: 2, actual: 2, delta: 0 })).toBe(false);
        expect(isUnderResourced({ planned: null, actual: 1, delta: null })).toBeNull();
    });
});

describe('blockPercent', () => {
    it('пробрасывает null: «объёмы не заданы» это не «сделано 0»', () => {
        expect(blockPercent({ block_id: 1, items: [], percent: null })).toBeNull();
        expect(blockPercent(undefined)).toBeNull();
        expect(blockPercent({ block_id: 1, items: [], percent: 0 })).toBe(0);
    });
});
