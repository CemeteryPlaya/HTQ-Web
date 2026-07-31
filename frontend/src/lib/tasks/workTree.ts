/**
 * Раскладка работ проекта по трём ключам: площадка → блок → пакет.
 *
 * Чистые функции, отдельно от рисующего их `components/tasks/SiteWorkTree`:
 * здесь единственное место, где решается, куда попадёт задача без площадки
 * и откуда берётся список объектов, — и это стоит проверять тестом, а не
 * глазами по скриншоту.
 */
import type { TFunction } from 'i18next';

import type { Project, Roadmap, Task } from '@/types/tasks';

/**
 * Тот же союз, что у `lib/tasks/status.ts` и соседей: сюда приходит и
 * `useTranslation().t`, и упрощённая функция из тестов.
 */
export type Translate = TFunction | ((key: string, fallback?: string) => string);

export interface TaskNode {
  task: Task;
  children: TaskNode[];
}

/**
 * Задачи деревом по `parent`.
 *
 * Задача, чей родитель не попал в переданный список, становится корнем, а
 * не пропадает: список всегда чем-то ограничен (проектом, пакетом), и
 * родитель законно оказывается за его пределами.
 */
export function buildTaskTree(tasks: Task[]): TaskNode[] {
  const byId = new Map<number, TaskNode>();
  tasks.forEach((task) => byId.set(task.id, { task, children: [] }));

  const roots: TaskNode[] = [];
  byId.forEach((node) => {
    const pid = node.task.parent;
    if (pid && byId.has(pid)) {
      byId.get(pid)!.children.push(node);
    } else {
      roots.push(node);
    }
  });
  return roots;
}

export interface SiteRow {
  key: number | null;
  name: string;
  color: string;
}

export interface WorkTree {
  /** Задачи: площадка → блок → пакет. Все три ключа допускают `null`. */
  tasksBySite: Map<number | null, Map<number | null, Map<number | null, Task[]>>>;
  /** Пакеты: площадка → блок. */
  roadmapsBySite: Map<number, Map<number, Roadmap[]>>;
  blockNames: Map<number, string>;
  siteRows: SiteRow[];
}

/**
 * Разложить задачи и пакеты по площадкам, блокам и роудмапам.
 *
 * Все ключи допускают `null`, и это не защита от кривых данных, а настоящие
 * состояния: у исторических задач нет ни площадки, ни блока, ни пакета, и
 * терять их из дерева нельзя.
 *
 * Список площадок — объекты проекта ПЛЮС встретившиеся только в задачах или
 * пакетах. Второе слагаемое не перестраховка: `resolve_task_site` разрешает
 * любой объект, пока у проекта их нет, так что задача законно ссылается на
 * объект, которого в `project.sites` не окажется.
 */
export function buildWorkTree(
  project: Pick<Project, 'sites'>,
  tasks: Task[],
  roadmaps: Roadmap[],
  t: Translate,
): WorkTree {
  const tasksBySite: WorkTree['tasksBySite'] = new Map();
  tasks.forEach((task) => {
    const siteKey = task.site ?? null;
    if (!tasksBySite.has(siteKey)) tasksBySite.set(siteKey, new Map());
    const byBlock = tasksBySite.get(siteKey)!;
    const blockKey = task.site_block ?? null;
    if (!byBlock.has(blockKey)) byBlock.set(blockKey, new Map());
    const byRoadmap = byBlock.get(blockKey)!;
    const roadmapKey = task.roadmap ?? null;
    if (!byRoadmap.has(roadmapKey)) byRoadmap.set(roadmapKey, []);
    byRoadmap.get(roadmapKey)!.push(task);
  });

  const roadmapsBySite: WorkTree['roadmapsBySite'] = new Map();
  roadmaps.forEach((roadmap) => {
    if (!roadmapsBySite.has(roadmap.site_id)) {
      roadmapsBySite.set(roadmap.site_id, new Map());
    }
    const byBlock = roadmapsBySite.get(roadmap.site_id)!;
    if (!byBlock.has(roadmap.site_block_id)) {
      byBlock.set(roadmap.site_block_id, []);
    }
    byBlock.get(roadmap.site_block_id)!.push(roadmap);
  });

  // Имена блоков — из пакетов и задач: отдельного запроса за ними не шлём.
  const blockNames = new Map<number, string>();
  roadmaps.forEach((r) => blockNames.set(r.site_block_id, r.site_block_name));
  tasks.forEach((task) => {
    if (task.site_block && task.site_block_name) {
      blockNames.set(task.site_block, task.site_block_name);
    }
  });

  const siteRows: SiteRow[] = (project.sites ?? []).map((site) => ({
    key: site.id as number | null,
    name: site.name,
    color: site.color,
  }));
  const known = new Set((project.sites ?? []).map((site) => site.id));
  tasks.forEach((task) => {
    if (task.site && !known.has(task.site)) {
      known.add(task.site);
      siteRows.push({
        key: task.site,
        name: task.site_name ?? `#${task.site}`,
        color: task.site_color ?? '#0ea5e9',
      });
    }
  });
  roadmaps.forEach((roadmap) => {
    if (!known.has(roadmap.site_id)) {
      known.add(roadmap.site_id);
      siteRows.push({
        key: roadmap.site_id,
        name: roadmap.site_name,
        color: roadmap.site_color,
      });
    }
  });
  if (tasksBySite.has(null)) {
    siteRows.push({
      key: null,
      name: t('tasks.pages.sites.withoutSite', 'Без объекта'),
      color: '#9ca3af',
    });
  }

  return { tasksBySite, roadmapsBySite, blockNames, siteRows };
}
