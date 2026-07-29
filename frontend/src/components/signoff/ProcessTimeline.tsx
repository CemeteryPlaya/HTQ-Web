/**
 * Карточка хода согласования: этапы процесса и решения по ним.
 *
 * **Главное, что должна показать эта раскладка — параллельность.** В модели
 * она выражена одним числом: этапы с ОДИНАКОВЫМ `order` идут одновременно,
 * с разным — друг за другом. Отдельной модели графа нет, поэтому и рисовать
 * граф не из чего; вместо этого этапы сгруппированы по `order`, группы идут
 * сверху вниз (последовательность), а этапы внутри группы — рядом
 * (параллельность). Плоский список этапов эту разницу потерял бы, и
 * «согласуют одновременно» стало бы неотличимо от «сначала он, потом она».
 *
 * Этапы приходят снимком маршрута на момент запуска — правка маршрута уже
 * идущее согласование не трогает, так что здесь показывается то, что было
 * на старте, а не то, что в маршруте сейчас.
 */

import { CheckCircle2, Circle, CircleDot, MinusCircle, XCircle } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import type { ApprovalProcess, TaskState } from '@/types/signoff';

import { formatMoment, groupStages } from './format';
import { QUORUM_LABELS, TASK_STATE_LABELS } from './labels';
import { StageStateBadge } from './states';

const TASK_ICONS: Record<TaskState, { icon: typeof Circle; className: string }> = {
  pending: { icon: CircleDot, className: 'text-amber-600 dark:text-amber-500' },
  approved: { icon: CheckCircle2, className: 'text-emerald-600 dark:text-emerald-500' },
  rejected: { icon: XCircle, className: 'text-destructive' },
  skipped: { icon: MinusCircle, className: 'text-muted-foreground' },
};

function TaskRow({
  task,
  stateLabels,
}: {
  task: ApprovalProcess['stages'][number]['tasks'][number];
  stateLabels: Record<string, string>;
}) {
  const { icon: Icon, className } = TASK_ICONS[task.state] ?? TASK_ICONS.pending;
  return (
    <li className="flex items-start gap-2 py-1.5">
      <Icon className={cn('h-4 w-4 mt-0.5 shrink-0', className)} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2">
          <span className="text-sm font-medium">
            {task.full_name || `Пользователь #${task.user_id}`}
          </span>
          <span className="text-xs text-muted-foreground">
            {stateLabels[task.state] ?? TASK_STATE_LABELS[task.state] ?? task.state}
            {task.acted_at && ` · ${formatMoment(task.acted_at)}`}
          </span>
        </div>
        {task.comment && (
          <p className="text-sm text-muted-foreground mt-0.5 whitespace-pre-wrap break-words">
            {task.comment}
          </p>
        )}
      </div>
    </li>
  );
}

interface Props {
  process: ApprovalProcess;
  /** Подписи с `GET /enums`; при их отсутствии берутся запасные. */
  stageStateLabels?: Record<string, string>;
  taskStateLabels?: Record<string, string>;
}

export function ProcessTimeline({
  process,
  stageStateLabels = {},
  taskStateLabels = {},
}: Props) {
  const groups = groupStages(process.stages);

  if (groups.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        В снимке процесса нет ни одного этапа.
      </p>
    );
  }

  return (
    <ol className="space-y-4">
      {groups.map((group, index) => {
        const order = group[0].order;
        const isCurrent = process.current_order === order;
        return (
          <li key={order}>
            <div className="mb-2 flex items-center gap-2">
              <span
                className={cn(
                  'flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold',
                  isCurrent
                    ? 'bg-amber-500/15 text-amber-700 dark:text-amber-500 ring-1 ring-amber-500/40'
                    : 'bg-muted text-muted-foreground',
                )}
              >
                {index + 1}
              </span>
              {group.length > 1 && (
                <Badge variant="outline" className="text-muted-foreground">
                  параллельно · {group.length}
                </Badge>
              )}
            </div>

            <div
              className={cn(
                'grid gap-3',
                group.length > 1 && 'md:grid-cols-2',
              )}
            >
              {group.map((stage) => (
                <div
                  key={stage.id}
                  className={cn(
                    'rounded-lg border p-3',
                    stage.state === 'active' && 'border-amber-500/40 bg-amber-500/5',
                    stage.state === 'rejected' && 'border-destructive/40',
                    stage.state === 'skipped' && 'opacity-60',
                  )}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-medium">{stage.name}</span>
                    <StageStateBadge
                      state={stage.state}
                      label={stageStateLabels[stage.state]}
                    />
                  </div>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    {QUORUM_LABELS[stage.quorum] ?? stage.quorum}
                    {stage.decided_at && ` · ${formatMoment(stage.decided_at)}`}
                  </p>
                  <ul className="mt-2 divide-y">
                    {stage.tasks.map((task) => (
                      <TaskRow
                        key={task.id}
                        task={task}
                        stateLabels={taskStateLabels}
                      />
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
