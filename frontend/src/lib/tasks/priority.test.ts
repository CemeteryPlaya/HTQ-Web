import { describe, expect, it } from 'vitest';

import {
    TASK_PRIORITY,
    TASK_PRIORITY_ORDER,
    normalizeTaskPriority,
    priorityHex,
    priorityLabel,
    priorityMeta,
} from './priority';

/**
 * Компаньон `status.test.ts`. Приоритеты, в отличие от статусов, во всех
 * шести копиях совпадали с бэкендом — так что это защита от расхождения,
 * а не фиксация починенного бага. Держим ровно те инварианты, поломка
 * которых прошла бы молча: полнота таблицы, порядок и отсутствие падений
 * на неизвестном значении.
 */
describe('TASK_PRIORITY', () => {
    it('покрывает ровно те пять приоритетов, что есть в бэкенде', () => {
        expect([...TASK_PRIORITY_ORDER]).toEqual([
            'critical', 'high', 'medium', 'low', 'trivial',
        ]);
        expect(Object.keys(TASK_PRIORITY).sort())
            .toEqual([...TASK_PRIORITY_ORDER].sort());
    });

    it('порядок — от самого срочного к самому мелкому', () => {
        expect(TASK_PRIORITY_ORDER[0]).toBe('critical');
        expect(TASK_PRIORITY_ORDER[TASK_PRIORITY_ORDER.length - 1]).toBe('trivial');
    });

    it('у каждого приоритета заполнены класс, значок, цвет и ключ', () => {
        for (const priority of TASK_PRIORITY_ORDER) {
            const meta = TASK_PRIORITY[priority];
            expect(meta.badgeClass).not.toBe('');
            expect(meta.icon).not.toBe('');
            expect(meta.hex).toMatch(/^#[0-9a-f]{6}$/i);
            expect(meta.labelKey).toBe(`tasks.pages.list.priority.${priority}`);
        }
    });

    it('значки различимы между собой', () => {
        const icons = TASK_PRIORITY_ORDER.map((p) => TASK_PRIORITY[p].icon);
        expect(new Set(icons).size).toBe(icons.length);
    });
});

describe('normalizeTaskPriority', () => {
    it('не трогает известные значения', () => {
        for (const priority of TASK_PRIORITY_ORDER) {
            expect(normalizeTaskPriority(priority)).toBe(priority);
        }
    });

    it('неизвестное значение уводит в medium, а не роняет рендер', () => {
        expect(normalizeTaskPriority('urgent')).toBe('medium');
        expect(normalizeTaskPriority('')).toBe('medium');
        expect(normalizeTaskPriority(null)).toBe('medium');
        expect(normalizeTaskPriority(undefined)).toBe('medium');
    });

    it('не принимает свойства прототипа за приоритет', () => {
        // Проверка через `in` вместо hasOwnProperty пропускала эти имена, и
        // TASK_PRIORITY['toString'] отдавал функцию без .hex.
        expect(normalizeTaskPriority('toString')).toBe('medium');
        expect(normalizeTaskPriority('constructor')).toBe('medium');
        expect(priorityHex('toString')).toBe(TASK_PRIORITY.medium.hex);
    });
});

describe('priorityMeta / priorityHex / priorityLabel', () => {
    it('всегда возвращают что-то осмысленное', () => {
        expect(priorityMeta('critical').icon).toBe(TASK_PRIORITY.critical.icon);
        expect(priorityHex('high')).toBe(TASK_PRIORITY.high.hex);
        expect(priorityHex('чепуха')).toBe(TASK_PRIORITY.medium.hex);
    });

    it('подпись идёт через ключ перевода, а не сырым значением', () => {
        const t = (key: string) => `[${key}]`;
        expect(priorityLabel('low', t)).toBe('[tasks.pages.list.priority.low]');
        expect(priorityLabel('чепуха', t))
            .toBe('[tasks.pages.list.priority.medium]');
    });
});
