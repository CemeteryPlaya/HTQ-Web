import type { TaskStatus } from '@/types/tasks';

/**
 * Схема переходов статусов задачи — копия `TRANSITIONS` из
 * `backend/apps/tasks/models.py`. Только подсказка интерфейсу: доска не даёт
 * бросить карточку в колонку, куда сервер её не пустит. Решает всё равно
 * сервер (`POST tasks/<id>/move` отвечает 400 `task_transition_invalid` со
 * списком допустимых), поэтому расхождение копии ведёт к лишнему отказу, а не
 * к обходу правила. Меняется вместе с моделью.
 */
export const TASK_TRANSITIONS: Record<TaskStatus, readonly TaskStatus[]> = {
  backlog: ['todo', 'in_progress', 'cancelled'],
  todo: ['in_progress', 'blocked', 'backlog', 'cancelled'],
  in_progress: ['in_review', 'blocked', 'done', 'todo', 'cancelled'],
  in_review: ['done', 'in_progress', 'blocked', 'cancelled'],
  blocked: ['in_progress', 'todo', 'cancelled'],
  done: ['in_progress', 'cancelled'],
  cancelled: ['backlog', 'todo'],
};

export function canTransition(from: TaskStatus, to: TaskStatus): boolean {
  return from === to || TASK_TRANSITIONS[from].includes(to);
}
