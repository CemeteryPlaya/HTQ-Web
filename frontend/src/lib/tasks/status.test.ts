import { describe, expect, it } from 'vitest';

import {
    ACTIVE_STATUSES,
    OPEN_STATUSES,
    TASK_STATUS,
    TASK_STATUS_ORDER,
    TERMINAL_STATUSES,
    countStatuses,
    normalizeTaskStatus,
    statusBadgeClass,
    statusHex,
    statusLabel,
} from './status';

/**
 * The bug this module exists to prevent: three files described statuses
 * (`open` / `closed`) that the backend has never emitted, and knew nothing
 * of `backlog`, `todo`, `blocked` or `cancelled`. Nothing failed — the
 * charts just quietly reported wrong numbers. These tests pin the parts
 * that were wrong.
 */
describe('TASK_STATUS', () => {
    it('покрывает ровно те семь статусов, что есть в бэкенде', () => {
        expect([...TASK_STATUS_ORDER]).toEqual([
            'backlog', 'todo', 'in_progress', 'in_review', 'blocked',
            'done', 'cancelled',
        ]);
        expect(Object.keys(TASK_STATUS).sort())
            .toEqual([...TASK_STATUS_ORDER].sort());
    });

    it('не содержит несуществующих open/closed', () => {
        expect(TASK_STATUS).not.toHaveProperty('open');
        expect(TASK_STATUS).not.toHaveProperty('closed');
    });

    it('у каждого статуса заполнены цвет, класс и ключ перевода', () => {
        for (const status of TASK_STATUS_ORDER) {
            const meta = TASK_STATUS[status];
            expect(meta.hex).toMatch(/^#[0-9a-f]{6}$/i);
            expect(meta.badgeClass).not.toBe('');
            expect(meta.columnClass).not.toBe('');
            expect(meta.labelKey).toBe(`tasks.pages.list.status.${status}`);
        }
    });

    it('цвета статусов различимы между собой', () => {
        const hexes = TASK_STATUS_ORDER.map((s) => TASK_STATUS[s].hex);
        expect(new Set(hexes).size).toBe(hexes.length);
    });
});

describe('группы статусов', () => {
    it('разбивают все семь статусов без пересечений', () => {
        const all = [...OPEN_STATUSES, ...ACTIVE_STATUSES, ...TERMINAL_STATUSES];
        expect(all.sort()).toEqual([...TASK_STATUS_ORDER].sort());
    });

    it('терминальные — только done и cancelled', () => {
        expect([...TERMINAL_STATUSES]).toEqual(['done', 'cancelled']);
    });

    it('активные включают blocked (его теряла карточка «В работе»)', () => {
        expect([...ACTIVE_STATUSES]).toEqual(['in_progress', 'in_review', 'blocked']);
    });

    it('очередь — backlog и todo (их тоже теряла карточка)', () => {
        expect([...OPEN_STATUSES]).toEqual(['backlog', 'todo']);
    });
});

describe('countStatuses', () => {
    const counts = {
        backlog: 1, todo: 2, in_progress: 3, in_review: 4,
        blocked: 5, done: 6, cancelled: 7,
    };

    it('«В работе» и «Завершено» в сумме дают все задачи', () => {
        const open = countStatuses(counts, OPEN_STATUSES)
            + countStatuses(counts, ACTIVE_STATUSES);
        const done = countStatuses(counts, TERMINAL_STATUSES);
        const total = Object.values(counts).reduce((a, b) => a + b, 0);
        expect(open + done).toBe(total);
        // Старая арифметика: open+in_progress+in_review = 7 из 28.
        expect(open).toBe(15);
        expect(done).toBe(13);
    });

    it('переживает отсутствующие ключи и undefined', () => {
        expect(countStatuses({ done: 2 }, TERMINAL_STATUSES)).toBe(2);
        expect(countStatuses(undefined, TERMINAL_STATUSES)).toBe(0);
    });
});

describe('normalizeTaskStatus', () => {
    it('переносит легаси-статусы в актуальные', () => {
        expect(normalizeTaskStatus('open')).toBe('todo');
        expect(normalizeTaskStatus('closed')).toBe('cancelled');
    });

    it('не трогает актуальные', () => {
        for (const status of TASK_STATUS_ORDER) {
            expect(normalizeTaskStatus(status)).toBe(status);
        }
    });

    it('никогда не бросает — карточка в чужой колонке лучше пустой доски', () => {
        expect(normalizeTaskStatus('невнятица')).toBe('todo');
        expect(normalizeTaskStatus('')).toBe('todo');
        expect(normalizeTaskStatus(null)).toBe('todo');
        expect(normalizeTaskStatus(undefined)).toBe('todo');
    });

    it('не принимает свойства прототипа за статус', () => {
        // Проверка через `in` вместо hasOwnProperty пропускала эти имена, и
        // TASK_STATUS['toString'] отдавал функцию, у которой badgeClass
        // undefined — бейдж молча оставался без класса.
        expect(normalizeTaskStatus('toString')).toBe('todo');
        expect(normalizeTaskStatus('constructor')).toBe('todo');
        expect(normalizeTaskStatus('hasOwnProperty')).toBe('todo');
        expect(statusBadgeClass('toString')).toBe(TASK_STATUS.todo.badgeClass);
    });
});

describe('statusHex / statusLabel', () => {
    it('всегда дают цвет, а не запасной #8884d8', () => {
        for (const status of TASK_STATUS_ORDER) {
            expect(statusHex(status)).toBe(TASK_STATUS[status].hex);
        }
        expect(statusHex('open')).toBe(TASK_STATUS.todo.hex);
    });

    it('никогда не показывают сырой ключ, если перевод есть', () => {
        const t = (key: string) => `[${key}]`;
        expect(statusLabel('blocked', t)).toBe('[tasks.pages.list.status.blocked]');
        expect(statusLabel('closed', t)).toBe('[tasks.pages.list.status.cancelled]');
    });
});
