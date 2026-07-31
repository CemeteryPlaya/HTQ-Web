import { describe, expect, it } from 'vitest';

import { protectedRoutes, publicRoutes } from './routeDefinitions';

/**
 * Guards the failure mode this table actually had: `/admin/*` and `/hr/*`
 * were each declared twice — once without `requiresRole`, once with it.
 * `<Routes>` scores identical path strings equally and renders whichever
 * came first, so the ungated copies won and the role gate did nothing at
 * all. Worse, the two `/admin/levels` entries pointed at different
 * components, so one whole screen was unreachable.
 *
 * A duplicate is never intentional here, and it fails silently in the
 * browser, so it fails loudly in CI instead.
 */
describe('routeDefinitions', () => {
    it('не содержит дублирующихся защищённых путей', () => {
        const paths = protectedRoutes.map((r) => r.path);
        const duplicates = paths.filter((p, i) => paths.indexOf(p) !== i);
        expect(duplicates).toEqual([]);
    });

    it('не содержит дублирующихся публичных путей', () => {
        const paths = publicRoutes.map((r) => r.path);
        const duplicates = paths.filter((p, i) => paths.indexOf(p) !== i);
        expect(duplicates).toEqual([]);
    });

    it('публичные и защищённые маршруты не пересекаются', () => {
        const publicPaths = new Set(publicRoutes.map((r) => r.path));
        const overlap = protectedRoutes
            .map((r) => r.path)
            .filter((p) => publicPaths.has(p));
        expect(overlap).toEqual([]);
    });

    it('управленческие страницы задач закрыты ролью', () => {
        const byPath = new Map(protectedRoutes.map((r) => [r.path, r]));
        expect(byPath.get('/tasks/roadmap')?.requiresRole).toBe('hr');
        expect(byPath.get('/tasks/reports')?.requiresRole).toBe('hr');
        expect(byPath.get('/tasks/resources')?.requiresRole).toBe('hr');
        expect(byPath.get('/tasks/equipment')?.requiresRole).toBe('admin');
        // ...а сами задачи — нет: рядовой сотрудник ведёт там свою работу.
        expect(byPath.get('/tasks')?.requiresRole).toBeUndefined();
        expect(byPath.get('/tasks/:id')?.requiresRole).toBeUndefined();
    });

    it('страница проектов закрыта ролью задач, а не редакторской', () => {
        const projects = protectedRoutes.find((r) => r.path === '/manage/projects');
        // Путь исторический (/manage/), но это страница домена задач, а не
        // CMS. С ролью 'editor' админ без роли редактора туда не попадал бы,
        // а контент-редактор попадал бы и получал 403 на каждое действие.
        expect(projects?.requiresRole).toBe('hr');
        expect(projects?.requiresAuth).toBe(true);
    });

    it('каждый /admin/* и /hr/* маршрут закрыт ролью', () => {
        const ungated = protectedRoutes.filter(
            (r) => /^\/(admin|hr)\//.test(r.path) && !r.requiresRole,
        );
        expect(ungated.map((r) => r.path)).toEqual([]);
    });

    it('статические пути объявлены раньше параметрических в той же ветке', () => {
        const paths = protectedRoutes.map((r) => r.path);
        const idParam = paths.indexOf('/tasks/:id');
        for (const staticPath of ['/tasks/roadmap', '/tasks/reports',
            '/tasks/resources', '/tasks/equipment']) {
            expect(paths.indexOf(staticPath)).toBeLessThan(idParam);
        }
    });
});
