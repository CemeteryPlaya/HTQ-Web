/**
 * api/holding.ts
 * Клиент читателей сводки холдинга (блок H, задача 5) — обе ручки уже
 * готовы, отревьюены и работают (задачи 3 и 4). Пути без завершающего
 * слэша — бэкенд регистрирует оба написания. Слой транспортный, логики
 * (слияния по компании, форматирования) здесь нет — она в `GroupSummary.tsx`.
 */

import api from './client';
import { apiPath } from './endpoints';
import type { HoldingHeadcount, HoldingProjects } from '@/types/holding';

export const holdingApi = {
  /**
   * `GET /api/hr/v1/holding/headcount` — люди, структура и штат по каждой
   * действующей компании группы. 403 — не с поддомена холдинга (или нет
   * доступа к домену); 503 — сводные представления сейчас пересобираются
   * (`migrate_companies`).
   */
  headcount: () => api.get<HoldingHeadcount>(apiPath('hr', 'holding/headcount')),

  /**
   * `GET /api/tasks/v1/holding/projects` — проекты, объекты, задачи и
   * отчётность по каждой действующей компании группы. Те же 403/503, что и
   * у `headcount`, но приходят от ручки `tasks` независимо.
   */
  projects: () => api.get<HoldingProjects>(apiPath('tasks', 'holding/projects')),
};
