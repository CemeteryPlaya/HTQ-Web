import { describe, expect, it } from 'vitest';

import { protectedRoutes, publicRoutes } from './routeDefinitions';

/**
 * Guards the failure mode this table actually had: `/admin/*` and `/hr/*`
 * were each declared twice — once without a role gate, once with it.
 * `<Routes>` scores identical path strings equally and renders whichever
 * came first, so the ungated copies won and the gate did nothing at
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

    it('управленческие страницы задач закрыты гейтом модуля', () => {
        const byPath = new Map(protectedRoutes.map((r) => [r.path, r]));
        expect(byPath.get('/tasks/roadmap')?.requires).toEqual({ module: 'hr', level: 'read' });
        expect(byPath.get('/tasks/reports')?.requires).toEqual({ module: 'hr', level: 'read' });
        expect(byPath.get('/tasks/resources')?.requires).toEqual({ module: 'hr', level: 'read' });
        expect(byPath.get('/tasks/equipment')?.requires).toEqual({ module: 'tasks', level: 'admin' });
        // Численность персонала — управленческие данные по объекту целиком,
        // в отличие от соседней ежедневки, куда отчитываются о своей смене.
        expect(byPath.get('/tasks/project-daily')?.requires).toEqual({ module: 'hr', level: 'read' });
        // ...а сами задачи — нет: рядовой сотрудник ведёт там свою работу.
        expect(byPath.get('/tasks')?.requires).toBeUndefined();
        expect(byPath.get('/tasks/:id')?.requires).toBeUndefined();
        expect(byPath.get('/tasks/daily')?.requires).toBeUndefined();
    });

    it('страница проектов закрыта гейтом задачного контура, а не редакторского', () => {
        const projects = protectedRoutes.find((r) => r.path === '/manage/projects');
        // Путь исторический (/manage/), но это страница домена задач, а не
        // CMS. С гейтом cms админ без редакторских прав туда не попадал бы,
        // а контент-редактор попадал бы и получал 403 на каждое действие.
        expect(projects?.requires).toEqual({ module: 'hr', level: 'read' });
        expect(projects?.requiresAuth).toBe(true);
    });

    it('каждый /admin/* и /hr/* маршрут закрыт гейтом модуля', () => {
        const ungated = protectedRoutes.filter(
            (r) => /^\/(admin|hr)\//.test(r.path) && !r.requires,
        );
        expect(ungated.map((r) => r.path)).toEqual([]);
    });

    it('редакторские страницы CMS требуют записи в cms', () => {
        const byPath = new Map(protectedRoutes.map((r) => [r.path, r]));
        for (const path of ['/manage/home', '/manage/news', '/manage/contacts']) {
            expect(byPath.get(path)?.requires).toEqual({ module: 'cms', level: 'write' });
        }
    });

    /**
     * Сторож на имена модулей.
     *
     * Модуль, которого нет в реестре бэкенда (`apps/core/models.py::KNOWN_SERVICES`),
     * никогда не попадёт в карту прав `/access/v1/me`, а значит уровень его
     * всегда будет `none` — страница закроется навсегда и молча, без единой
     * ошибки в консоли. Опечатка здесь неотличима от «прав не выдали».
     *
     * Список ниже — намеренная копия реестра для проверки, а не второй
     * справочник: он не участвует в работе приложения и существует только
     * затем, чтобы новый модуль в маршрутах стал осознанным решением.
     */
    it('использует только модули из реестра бэкенда', () => {
        const KNOWN = new Set([
            'users', 'hr', 'tasks', 'approvals', 'cms', 'media',
            'mail', 'messenger', 'conference', 'contracts', 'signoff',
            'companies',
        ]);
        const unknown = protectedRoutes
            .filter((r) => r.requires && !KNOWN.has(r.requires.module))
            .map((r) => `${r.path} → ${r.requires?.module}`);
        expect(unknown).toEqual([]);
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
