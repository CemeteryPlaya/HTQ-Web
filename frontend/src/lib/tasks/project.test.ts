import { describe, expect, it } from 'vitest';

import {
    PROJECT_STATUS,
    PROJECT_STATUS_ORDER,
    normalizeProjectStatus,
    primarySite,
    projectNeedsSites,
    projectStatusBadgeClass,
    projectStatusLabel,
} from './project';
import type { Project, ProjectSiteRef } from '@/types/tasks';

const site = (id: number, is_primary = false): ProjectSiteRef => ({
    id,
    name: `Объект ${id}`,
    color: '#0ea5e9',
    status: 'active',
    is_primary,
    start_date: null,
    end_date: null,
});

/** Only the fields the helpers read. */
const project = (sites: ProjectSiteRef[]): Pick<Project, 'sites'> => ({ sites });

describe('PROJECT_STATUS', () => {
    it('покрывает ровно те три статуса, что есть в бэкенде', () => {
        expect([...PROJECT_STATUS_ORDER]).toEqual(['active', 'completed', 'archived']);
        expect(Object.keys(PROJECT_STATUS).sort())
            .toEqual([...PROJECT_STATUS_ORDER].sort());
    });

    it('сохраняет палитру, которая была на дорожной карте', () => {
        // Значения перенесены дословно: если бы они разъехались, бейджи
        // проектов сменили бы цвет молча, без единой упавшей проверки.
        expect(PROJECT_STATUS.active.badgeClass).toBe('bg-blue-600 text-white');
        expect(PROJECT_STATUS.completed.badgeClass).toBe('bg-green-500 text-white');
        expect(PROJECT_STATUS.archived.badgeClass).toBe('bg-gray-400 text-white');
    });

    it('только active считается открытым', () => {
        expect(PROJECT_STATUS_ORDER.filter((s) => PROJECT_STATUS[s].isOpen))
            .toEqual(['active']);
    });
});

describe('normalizeProjectStatus', () => {
    it('пропускает известные значения', () => {
        for (const status of PROJECT_STATUS_ORDER) {
            expect(normalizeProjectStatus(status)).toBe(status);
        }
    });

    it('не бросает на мусоре и пустоте, а падает в active', () => {
        // Пустой список проектов хуже проекта в неверной корзине.
        expect(normalizeProjectStatus(undefined)).toBe('active');
        expect(normalizeProjectStatus(null)).toBe('active');
        expect(normalizeProjectStatus('')).toBe('active');
        expect(normalizeProjectStatus('deleted')).toBe('active');
    });

    it('не принимает служебные свойства объекта за статус', () => {
        // `raw in PROJECT_STATUS` без этой проверки пропустил бы
        // `toString`/`constructor` из прототипа.
        expect(normalizeProjectStatus('toString')).toBe('active');
        expect(normalizeProjectStatus('constructor')).toBe('active');
    });
});

describe('projectStatusLabel / projectStatusBadgeClass', () => {
    const t = (key: string, fallback?: string) => `${key}|${fallback ?? ''}`;

    it('переводит по ключу статуса', () => {
        expect(projectStatusLabel('completed', t))
            .toBe('tasks.projects.status.completed|completed');
    });

    it('неизвестный статус получает подпись active, а не сырой ключ', () => {
        expect(projectStatusLabel('nonsense', t))
            .toBe('tasks.projects.status.active|active');
        expect(projectStatusBadgeClass('nonsense')).toBe('bg-blue-600 text-white');
    });
});

describe('projectNeedsSites', () => {
    /**
     * Смысл подсказки: проект без объектов молча выпадает из оси
     * проект→объект→задача — `resolve_task_site` трактует «у проекта нет
     * объектов» как «подойдёт любой», и форма задачи показывает весь
     * справочник, не объясняя почему.
     */
    it('пустой список объектов требует внимания', () => {
        expect(projectNeedsSites(project([]))).toBe(true);
    });

    it('хотя бы один объект снимает предупреждение', () => {
        expect(projectNeedsSites(project([site(1)]))).toBe(false);
    });

    it('переживает отсутствие поля sites целиком', () => {
        expect(projectNeedsSites({ sites: undefined as never })).toBe(true);
    });
});

describe('primarySite', () => {
    it('возвращает помеченный основным, а не первый по порядку', () => {
        expect(primarySite(project([site(1), site(2, true)]))?.id).toBe(2);
    });

    it('без явной пометки берёт первый', () => {
        expect(primarySite(project([site(7), site(8)]))?.id).toBe(7);
    });

    it('на пустом списке даёт null, а не падает', () => {
        expect(primarySite(project([]))).toBeNull();
    });
});
