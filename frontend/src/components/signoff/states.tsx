/**
 * Плашки состояний согласования.
 *
 * Цвет с бэкенда не приходит и приходить не должен — это решение
 * интерфейса. Подписи, наоборот, идут с бэкенда (`GET /enums`) и
 * передаются пропом `label`; словарь в `labels.ts` работает запасным, пока
 * enums не загрузились.
 */

import type { BadgeProps } from '@/components/ui/badge';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import type {
  ApprovalState,
  ProcessState,
  StageState,
  TaskState,
} from '@/types/signoff';

import {
  APPROVAL_STATE_LABELS,
  PROCESS_STATE_LABELS,
  STAGE_STATE_LABELS,
  TASK_STATE_LABELS,
} from './labels';

type Tone = {
  variant: BadgeProps['variant'];
  /** Ровно те состояния, где смысл не передаётся вариантом shadcn'а:
   *  «согласовано» должно читаться как успех, а не как нейтральный outline. */
  className?: string;
};

const APPROVED_TONE: Tone = {
  variant: 'outline',
  className:
    'border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400',
};
const PENDING_TONE: Tone = {
  variant: 'outline',
  className: 'border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-500',
};
const REJECTED_TONE: Tone = { variant: 'destructive' };
/** Возврат на доработку — не отказ: это работа, которая вернулась к автору,
 *  и красный здесь читался бы как «всё пропало». Синий отличает его и от
 *  «ждём решения» (янтарный), с которым его иначе путали бы в списке. */
const REWORK_TONE: Tone = {
  variant: 'outline',
  className: 'border-sky-500/40 bg-sky-500/10 text-sky-700 dark:text-sky-400',
};
const MUTED_TONE: Tone = { variant: 'outline', className: 'text-muted-foreground' };

const PROCESS_STATE_TONES: Record<ProcessState, Tone> = {
  pending: PENDING_TONE,
  approved: APPROVED_TONE,
  rejected: REJECTED_TONE,
  rework: REWORK_TONE,
  cancelled: MUTED_TONE,
};

const STAGE_STATE_TONES: Record<StageState, Tone> = {
  waiting: MUTED_TONE,
  active: PENDING_TONE,
  approved: APPROVED_TONE,
  rejected: REJECTED_TONE,
  rework: REWORK_TONE,
  skipped: MUTED_TONE,
};

const TASK_STATE_TONES: Record<TaskState, Tone> = {
  pending: PENDING_TONE,
  approved: APPROVED_TONE,
  rejected: REJECTED_TONE,
  rework: REWORK_TONE,
  skipped: MUTED_TONE,
};

const APPROVAL_STATE_TONES: Record<ApprovalState, Tone> = {
  draft: MUTED_TONE,
  pending: PENDING_TONE,
  approved: APPROVED_TONE,
  rejected: REJECTED_TONE,
  rework: REWORK_TONE,
};

function StateBadge({
  tone,
  label,
  className,
}: {
  tone: Tone;
  label: string;
  className?: string;
}) {
  return (
    <Badge variant={tone.variant} className={cn(tone.className, className)}>
      {label}
    </Badge>
  );
}

export function ProcessStateBadge({
  state,
  label,
  className,
}: {
  state: ProcessState;
  /** Подпись с `/enums`, если она уже загружена. */
  label?: string;
  className?: string;
}) {
  return (
    <StateBadge
      tone={PROCESS_STATE_TONES[state] ?? MUTED_TONE}
      label={label ?? PROCESS_STATE_LABELS[state] ?? state}
      className={className}
    />
  );
}

export function StageStateBadge({
  state,
  label,
  className,
}: {
  state: StageState;
  label?: string;
  className?: string;
}) {
  return (
    <StateBadge
      tone={STAGE_STATE_TONES[state] ?? MUTED_TONE}
      label={label ?? STAGE_STATE_LABELS[state] ?? state}
      className={className}
    />
  );
}

export function TaskStateBadge({
  state,
  label,
  className,
}: {
  state: TaskState;
  label?: string;
  className?: string;
}) {
  return (
    <StateBadge
      tone={TASK_STATE_TONES[state] ?? MUTED_TONE}
      label={label ?? TASK_STATE_LABELS[state] ?? state}
      className={className}
    />
  );
}

export function ApprovalStateBadge({
  state,
  className,
}: {
  state: ApprovalState;
  className?: string;
}) {
  return (
    <StateBadge
      tone={APPROVAL_STATE_TONES[state] ?? MUTED_TONE}
      label={APPROVAL_STATE_LABELS[state] ?? state}
      className={className}
    />
  );
}
