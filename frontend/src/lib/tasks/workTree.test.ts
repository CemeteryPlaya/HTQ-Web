/**
 * Раскладка работ по площадкам, блокам и пакетам.
 *
 * Проверяется не форма Map ради формы, а три решения, из-за которых работа
 * может пропасть с экрана: задача без площадки, задача на площадке, которой
 * нет в проекте, и задача, чей родитель за пределами списка.
 */
import { describe, expect, it } from 'vitest';

import { buildTaskTree, buildWorkTree } from './workTree';
import type { Project, ProjectSiteRef, Roadmap, Task } from '@/types/tasks';

const t = (_key: string, fallback?: string) => fallback ?? _key;

const task = (over: Partial<Task> & { id: number }): Task => ({
  key: `TASK-${over.id}`,
  summary: `Задача ${over.id}`,
  status: 'todo',
  priority: 'medium',
  task_type: 'task',
  progress_percent: 0,
  parent: null,
  project: 1,
  roadmap: null,
  site: null,
  site_block: null,
  ...over,
} as Task);

const roadmap = (over: Partial<Roadmap> & { id: number }): Roadmap => ({
  name: `Пакет ${over.id}`,
  status: 'active',
  color: '#8b5cf6',
  project_id: 1,
  site_id: 1,
  site_name: 'Сазаган',
  site_color: '#22c55e',
  site_block_id: 10,
  site_block_name: 'Блок I',
  planned_working_days: null,
  task_count: 0,
  done_count: 0,
  progress: 0,
  ...over,
} as Roadmap);

const project = (sites: Project['sites']) => ({ sites }) as Pick<Project, 'sites'>;

const SAZAGAN: ProjectSiteRef = {
  id: 1,
  name: 'Сазаган',
  color: '#22c55e',
  status: 'active',
  is_primary: true,
  start_date: null,
  end_date: null,
};

describe('buildTaskTree', () => {
  it('вкладывает подзадачи в родителя', () => {
    const roots = buildTaskTree([
      task({ id: 1 }),
      task({ id: 2, parent: 1 }),
      task({ id: 3, parent: 1 }),
    ]);
    expect(roots).toHaveLength(1);
    expect(roots[0].children.map((c) => c.task.id)).toEqual([2, 3]);
  });

  it('не теряет задачу, чей родитель вне списка', () => {
    // Список всегда чем-то ограничен — проектом, пакетом, — и родитель
    // законно оказывается за его пределами. Такая задача обязана стать
    // корнем, а не исчезнуть.
    const roots = buildTaskTree([task({ id: 5, parent: 999 })]);
    expect(roots.map((r) => r.task.id)).toEqual([5]);
  });
});

describe('buildWorkTree', () => {
  it('раскладывает задачу по площадке, блоку и пакету', () => {
    const tree = buildWorkTree(
      project([SAZAGAN]),
      [task({ id: 1, site: 1, site_block: 10, roadmap: 100 })],
      [roadmap({ id: 100 })],
      t,
    );

    const byBlock = tree.tasksBySite.get(1)!;
    const byRoadmap = byBlock.get(10)!;
    expect(byRoadmap.get(100)!.map((x) => x.id)).toEqual([1]);
    expect(tree.roadmapsBySite.get(1)!.get(10)!.map((r) => r.id)).toEqual([100]);
    expect(tree.blockNames.get(10)).toBe('Блок I');
  });

  it('добавляет корзину «Без объекта» только когда такие задачи есть', () => {
    const withoutSite = buildWorkTree(
      project([SAZAGAN]), [task({ id: 1 })], [], t);
    expect(withoutSite.siteRows.map((r) => r.key)).toEqual([1, null]);

    const allPlaced = buildWorkTree(
      project([SAZAGAN]), [task({ id: 1, site: 1 })], [], t);
    expect(allPlaced.siteRows.map((r) => r.key)).toEqual([1]);
  });

  it('показывает площадку, которой нет в проекте, но есть в задачах', () => {
    // `resolve_task_site` разрешает любой объект, пока у проекта их нет, —
    // значит задача законно ссылается на объект вне project.sites, и
    // выкинуть её из дерева было бы потерей данных, а не аккуратностью.
    const tree = buildWorkTree(
      project([]),
      [task({ id: 1, site: 7, site_name: 'Алга', site_color: '#0ea5e9' })],
      [],
      t,
    );
    expect(tree.siteRows).toEqual([
      { key: 7, name: 'Алга', color: '#0ea5e9' },
    ]);
  });

  it('показывает площадку, которая есть только в пакетах', () => {
    const tree = buildWorkTree(
      project([]), [], [roadmap({ id: 100, site_id: 3, site_name: 'Блок-объект' })], t);
    expect(tree.siteRows.map((r) => r.name)).toEqual(['Блок-объект']);
  });

  it('не дублирует площадку, встретившуюся и в проекте, и в задачах', () => {
    const tree = buildWorkTree(
      project([SAZAGAN]),
      [task({ id: 1, site: 1 }), task({ id: 2, site: 1 })],
      [roadmap({ id: 100, site_id: 1 })],
      t,
    );
    expect(tree.siteRows).toHaveLength(1);
  });

  it('кладёт задачу без блока в отдельную корзину той же площадки', () => {
    const tree = buildWorkTree(
      project([SAZAGAN]),
      [task({ id: 1, site: 1, site_block: 10 }), task({ id: 2, site: 1 })],
      [],
      t,
    );
    const byBlock = tree.tasksBySite.get(1)!;
    // Порядок ключей задаёт компонент при отрисовке, здесь важен состав.
    expect(new Set(byBlock.keys())).toEqual(new Set([10, null]));
    expect(byBlock.get(null)!.get(null)!.map((x) => x.id)).toEqual([2]);
  });
});
