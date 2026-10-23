/**
 * Клиент канбан-досок (`/api/tasks/v1/boards/*`, мастер-план §6.1–6.2).
 * Права решает сервер: невидимая доска — 404, кнопки показываются по `can`.
 */
import api from '@/api/client';
import { apiPath } from '@/api/endpoints';
import type { TaskStatus } from '@/types/tasks';

import type { Board, BoardCard, BoardFilters, BoardKey, BoardsList, ColumnsSettings } from './types';

const path = (suffix: string) => apiPath('tasks', suffix);

/** Адрес доски: у личной нет id в пути — владелец берётся из токена. */
export function boardPath(key: BoardKey): string {
  if (key.kind === 'personal') return 'boards/personal';
  return key.kind === 'department' ? `boards/departments/${key.id}` : `boards/projects/${key.id}`;
}

/** Тело `board` для переноса и быстрого добавления. */
export function boardRef(key: BoardKey): { kind: BoardKey['kind']; id?: number } {
  return key.kind === 'personal' ? { kind: 'personal' } : { kind: key.kind, id: key.id };
}

/** Параметры запроса доски. «Скрывать пустые колонки» — вид, его здесь нет:
 * переключатель не перезапрашивает доску. */
export function filterParams(filters: BoardFilters): Record<string, string> {
  const params: Record<string, string> = {};
  if (filters.q.trim()) params.q = filters.q.trim();
  for (const name of ['label', 'member', 'due', 'completion', 'activity'] as const) {
    if (filters[name].length) params[name] = filters[name].join(',');
  }
  if (filters.new) params.new = '1';
  return params;
}

export interface CardMoveBody {
  status: TaskStatus;
  before_id?: number | null;
  after_id?: number | null;
}

export const boardsApi = {
  list: async (): Promise<BoardsList> => (await api.get<BoardsList>(path('boards'))).data,

  board: async (key: BoardKey, filters: BoardFilters): Promise<Board> =>
    (await api.get<Board>(path(boardPath(key)), { params: filterParams(filters) })).data,

  /** Дозагрузка одной колонки после первых 200 карточек. */
  column: async (key: BoardKey, filters: BoardFilters, status: TaskStatus, offset: number): Promise<Board> =>
    (await api.get<Board>(path(boardPath(key)), {
      params: { ...filterParams(filters), status, offset: String(offset) },
    })).data,

  move: async (key: BoardKey, taskId: number, body: CardMoveBody): Promise<BoardCard> =>
    (await api.post<BoardCard>(path(`tasks/${taskId}/move`), { board: boardRef(key), ...body })).data,

  /** Быстрое добавление: задача встаёт в конец колонки на этой доске. */
  quickAdd: async (key: BoardKey, body: {
    summary: string;
    status: TaskStatus;
    department_id?: number;
    project_id?: number;
  }): Promise<{ id: number }> =>
    (await api.post<{ id: number }>(path('tasks/'), { ...body, board: boardRef(key) })).data,

  /** Быстрая правка названия прямо на доске (Trello «карандаш»). */
  rename: async (taskId: number, summary: string): Promise<void> => {
    await api.patch(path(`tasks/${taskId}/`), { summary });
  },

  seen: async (taskId: number): Promise<void> => {
    await api.post(path(`tasks/${taskId}/seen`));
  },

  saveSettings: async (key: BoardKey, columns: Partial<ColumnsSettings>): Promise<{ columns: ColumnsSettings }> =>
    (await api.put<{ columns: ColumnsSettings }>(path(`${boardPath(key)}/settings`), { columns })).data,
};

/** Ключи запросов (мастер-план §7.2). */
export const boardKeys = {
  all: ['tasks', 'boards'] as const,
  list: () => ['tasks', 'boards'] as const,
  board: (key: BoardKey, filters: BoardFilters) =>
    ['tasks', 'board', key.kind, key.kind === 'personal' ? null : key.id,
      filterParams(filters)] as const,
  boardPrefix: (key: BoardKey) =>
    ['tasks', 'board', key.kind, key.kind === 'personal' ? null : key.id] as const,
};
