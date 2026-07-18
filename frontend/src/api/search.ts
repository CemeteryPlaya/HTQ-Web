/* ------------------------------------------------------------------ */
/*  Global search — frontend fan-out aggregator                         */
/*                                                                      */
/*  The platform has no shared backend library and each microservice    */
/*  owns its own schema, so global search is assembled here: we query   */
/*  every domain's list endpoint in parallel (each exposes a free-text  */
/*  `search`/`q` param) and merge the normalized results. A failing     */
/*  source (e.g. 403 for a user without HR access) is swallowed so the  */
/*  rest still return.                                                  */
/* ------------------------------------------------------------------ */
import { fetchTasks } from '@/api/tasks';
import { fetchEmployees } from '@/api/hr';
import { searchFiles } from '@/api/fileManager';
import { cmsApi } from '@/api/cms';

export type SearchCategory = 'task' | 'employee' | 'news' | 'file';

export interface GlobalSearchItem {
  /** Stable unique key for React lists / cmdk values. */
  id: string;
  category: SearchCategory;
  title: string;
  subtitle?: string;
  /** In-app route to navigate to on select. */
  href: string;
}

/** Max results surfaced per category in the palette. */
const PER_CATEGORY = 5;

function settled<T>(label: string, p: Promise<T[]>): Promise<T[]> {
  return p.catch((err) => {
    // One source failing (auth, network) must not break the whole search.
    if (import.meta.env.DEV) console.warn(`[globalSearch] ${label} failed`, err);
    return [] as T[];
  });
}

export async function globalSearch(query: string): Promise<GlobalSearchItem[]> {
  const q = query.trim();
  if (q.length < 2) return [];

  const [tasks, employees, files, newsRes] = await Promise.all([
    settled('tasks', fetchTasks({ search: q })),
    settled('employees', fetchEmployees({ search: q, limit: String(PER_CATEGORY) })),
    settled('files', searchFiles(q, PER_CATEGORY)),
    settled('news', cmsApi.getNews({ search: q, limit: PER_CATEGORY }).then((r) => r.data ?? [])),
  ]);

  const items: GlobalSearchItem[] = [];

  for (const t of tasks.slice(0, PER_CATEGORY)) {
    items.push({
      id: `task-${t.id}`,
      category: 'task',
      title: t.summary,
      subtitle: t.key,
      href: `/tasks/${t.id}`,
    });
  }

  for (const e of employees.slice(0, PER_CATEGORY)) {
    const name =
      e.full_name ||
      [e.first_name, e.last_name].filter(Boolean).join(' ') ||
      e.email;
    items.push({
      id: `employee-${e.id}`,
      category: 'employee',
      title: name,
      subtitle: e.position_title || e.department_name || e.email,
      href: `/hr/employees/${e.id}`,
    });
  }

  for (const n of newsRes.slice(0, PER_CATEGORY)) {
    items.push({
      id: `news-${n.id}`,
      category: 'news',
      title: n.title,
      subtitle: n.category || undefined,
      href: `/news/${n.slug}`,
    });
  }

  for (const f of files.slice(0, PER_CATEGORY)) {
    items.push({
      id: `file-${f.id}`,
      category: 'file',
      title: f.name,
      subtitle: f.description || undefined,
      href: '/files',
    });
  }

  return items;
}
