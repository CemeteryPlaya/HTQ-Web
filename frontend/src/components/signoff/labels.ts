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

import { translatedMap } from '@/lib/i18n/translatedMap';

// Значения словарей ниже — КЛЮЧИ перевода, а не готовые подписи; см.
// `translatedMap` о том, почему на уровне модуля иначе нельзя.


export const PROCESS_STATE_LABELS: Record<ProcessState, string> = translatedMap({
  pending: 'signoff.processState.pending',
  approved: 'signoff.processState.approved',
  rejected: 'signoff.processState.rejected',
  rework: 'signoff.processState.rework',
  cancelled: 'signoff.processState.cancelled',
});

export const STAGE_STATE_LABELS: Record<StageState, string> = translatedMap({
  waiting: 'signoff.stageState.waiting',
  active: 'signoff.stageState.active',
  approved: 'signoff.stageState.approved',
  rejected: 'signoff.stageState.rejected',
  rework: 'signoff.stageState.rework',
  skipped: 'signoff.stageState.skipped',
});

export const TASK_STATE_LABELS: Record<TaskState, string> = translatedMap({
  pending: 'signoff.taskState.pending',
  approved: 'signoff.taskState.approved',
  rejected: 'signoff.taskState.rejected',
  rework: 'signoff.taskState.rework',
  skipped: 'signoff.taskState.skipped',
});

/** Состояние согласования предметного объекта (колонка `approval_state`). */
export const APPROVAL_STATE_LABELS: Record<ApprovalState, string> = translatedMap({
  draft: 'signoff.approvalState.draft',
  pending: 'signoff.approvalState.pending',
  approved: 'signoff.approvalState.approved',
  rejected: 'signoff.approvalState.rejected',
  rework: 'signoff.approvalState.rework',
});

export const QUORUM_LABELS: Record<Quorum, string> = translatedMap({
  any: 'signoff.quorum.any',
  all: 'signoff.quorum.all',
});

/** Откуда берётся список согласующих этапа. `initiator` вместе с
 *  «требуется документ» и есть этап подписи автора. */
export const APPROVER_KIND_LABELS: Record<ApproverKind, string> = translatedMap({
  named: 'signoff.approverKind.named',
  initiator: 'signoff.approverKind.initiator',
});

/** `[{value, label}]` → `{value: label}`. Enums приходят списком пар, а
 *  показывать плашку удобнее по ключу. */
export function labelMap(options?: { value: string; label: string }[]) {
  return Object.fromEntries((options ?? []).map((option) => [option.value, option.label]));
}
