/**
 * Подписи состояний согласования.
 *
 * Всё, что здесь, — ЗАПАСНОЕ. Источник правды — `GET /api/signoff/v1/enums`,
 * который отдаёт пары `value`/`label` прямо из TextChoices модели; словарь
 * ниже нужен, пока запрос не вернулся, и там, где тянуть enums ради одной
 * плашки дороже, чем показать её.
 *
 * Отдельно от `states.tsx` намеренно: это данные, а не компоненты, и в
 * одном файле с ними они ломали бы fast refresh.
 */

import type {
  ApprovalState,
  ApproverKind,
  ProcessState,
  Quorum,
  StageState,
  TaskState,
} from '@/types/signoff';

export const PROCESS_STATE_LABELS: Record<ProcessState, string> = {
  pending: 'На согласовании',
  approved: 'Согласовано',
  rejected: 'Отклонено',
  rework: 'Возвращено на доработку',
  cancelled: 'Отозвано',
};

export const STAGE_STATE_LABELS: Record<StageState, string> = {
  waiting: 'Ожидает очереди',
  active: 'На рассмотрении',
  approved: 'Согласован',
  rejected: 'Отклонён',
  rework: 'Возвращён на доработку',
  skipped: 'Не потребовался',
};

export const TASK_STATE_LABELS: Record<TaskState, string> = {
  pending: 'Ожидает решения',
  approved: 'Согласовано',
  rejected: 'Отклонено',
  rework: 'Возвращено на доработку',
  skipped: 'Не потребовалось',
};

/** Состояние согласования предметного объекта (колонка `approval_state`). */
export const APPROVAL_STATE_LABELS: Record<ApprovalState, string> = {
  draft: 'Черновик',
  pending: 'На согласовании',
  approved: 'Согласовано',
  rejected: 'Отклонено',
  rework: 'На доработке',
};

export const QUORUM_LABELS: Record<Quorum, string> = {
  any: 'Достаточно одного',
  all: 'Нужны все',
};

/** Откуда берётся список согласующих этапа. `initiator` вместе с
 *  «требуется документ» и есть этап подписи автора. */
export const APPROVER_KIND_LABELS: Record<ApproverKind, string> = {
  named: 'Названные в маршруте',
  initiator: 'Инициатор согласования',
};

/** `[{value, label}]` → `{value: label}`. Enums приходят списком пар, а
 *  показывать плашку удобнее по ключу. */
export function labelMap(options?: { value: string; label: string }[]) {
  return Object.fromEntries((options ?? []).map((option) => [option.value, option.label]));
}
