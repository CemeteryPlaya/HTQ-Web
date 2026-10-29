/**
 * Адреса досок (мастер-план §7.3): `/tasks/board` — личная,
 * `/tasks/board/department/:id`, `/tasks/board/project/:id`.
 */
import type { BoardKey } from './types';

/** Адрес страницы доски. */
export function boardUrl(key: BoardKey): string {
  if (key.kind === 'personal') return '/tasks/board';
  return key.kind === 'department'
    ? `/tasks/board/department/${key.id}` : `/tasks/board/project/${key.id}`;
}

/** Доска из адреса; `null` — адрес не про доску (кривой id). */
export function boardKeyFromPath(pathname: string, id: string | undefined): BoardKey | null {
  const kind = pathname.startsWith('/tasks/board/department/') ? 'department'
    : pathname.startsWith('/tasks/board/project/') ? 'project' : 'personal';
  if (kind === 'personal') return { kind };
  const number = Number(id);
  return Number.isInteger(number) && number > 0 ? { kind, id: number } : null;
}

/** Последняя открытая доска человека (этап S6a, решение R-03): `/tasks` ведёт
 * на неё. Хранится в браузере; хранилище недоступно (приватный режим) —
 * личная доска. */
const LAST_BOARD_KEY = 'tasks.board.last';
const BOARD_URL = /^\/tasks\/board(\/(department|project)\/\d+)?$/;

export function rememberBoard(key: BoardKey): void {
  try { window.localStorage.setItem(LAST_BOARD_KEY, boardUrl(key)); } catch { /* приватный режим */ }
}

export function lastBoardUrl(): string {
  try {
    const url = window.localStorage.getItem(LAST_BOARD_KEY);
    if (url && BOARD_URL.test(url)) return url;
  } catch { /* приватный режим */ }
  return '/tasks/board';
}
