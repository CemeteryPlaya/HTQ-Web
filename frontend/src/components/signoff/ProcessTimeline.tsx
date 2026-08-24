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
 * В узкой колонке (`compact` — карточка процесса рядом с документом) рядом
 * этапы не встанут, и тогда параллельность держат два других признака:
 * плашка «параллельно · N» над группой и пунктирная скобка слева, которая
 * показывает, что карточки под ней — один шаг, а не несколько подряд.
 *
 * Этапы приходят снимком маршрута на момент запуска — правка маршрута уже
 * идущее согласование не трогает, так что здесь показывается то, что было
 * на старте, а не то, что в маршруте сейчас.
 *
 * По той же причине здесь показывается и УСЛОВИЕ этапа: в снимке остались
 * только сошедшиеся ветки, и без подписи «этап здесь, потому что страна —
 * Казахстан» непонятно, почему согласуют именно эти люди, а соседняя ветка
 * маршрута в карточке вообще отсутствует.
 */

import {
  CheckCircle2,
  Circle,
  CircleDot,
  FileText,
  MessageSquare,
  MinusCircle,
  PenLine,
  Split,
  Undo2,
  XCircle,
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import type { ApprovalProcess, SubjectField, TaskState } from '@/types/signoff';

import { conditionText, formatMoment, groupStages } from './format';
import { QUORUM_LABELS, TASK_STATE_LABELS } from './labels';
import { StageStateBadge } from './states';
import { useTranslation } from 'react-i18next';

const TASK_ICONS: Record<TaskState, { icon: typeof Circle; className: string }> = {
  pending: { icon: CircleDot, className: 'text-amber-600 dark:text-amber-500' },
  approved: { icon: CheckCircle2, className: 'text-emerald-600 dark:text-emerald-500' },
  rejected: { icon: XCircle, className: 'text-destructive' },
  // Возврат на доработку — не отказ: работа вернулась к автору, а не
  // пропала, поэтому стрелка назад и синий, а не красный крест.
  rework: { icon: Undo2, className: 'text-sky-600 dark:text-sky-400' },
  skipped: { icon: MinusCircle, className: 'text-muted-foreground' },
};

function TaskRow({
  task,
  stateLabels,
}: {
  task: ApprovalProcess['stages'][number]['tasks'][number];
  stateLabels: Record<string, string>;
}) {
  const { t } = useTranslation();
  const { icon: Icon, className } = TASK_ICONS[task.state] ?? TASK_ICONS.pending;
  return (
    <li className="flex items-start gap-2 py-1.5">
      <Icon className={cn('h-4 w-4 mt-0.5 shrink-0', className)} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2">
          <span className="text-sm font-medium">
            {task.full_name || t('signoff.userNumber', { id: task.user_id })}
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
        {/* Подписанный документ — то, ЧТО именно согласовано, и добираться до
            него из карточки должно быть можно. Ссылка подписанная и
            короткоживущая: без неё (media недоступен) остаётся сам факт
            приложенного файла, и это лучше пустоты. */}
        {task.file_id && (
          <p className="mt-0.5 flex items-center gap-1.5 text-sm">
            <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
            {task.file_url ? (
              <a
                href={task.file_url}
                target="_blank"
                rel="noreferrer"
                className="text-primary hover:underline break-all"
              >
                {t('signoff.timeline.attachedDocument')}
              </a>
            ) : (
              <span className="text-muted-foreground">
                {t('signoff.timeline.attachedNoLink')}
              </span>
            )}
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
  /** Поля типа из `GET /subjects` — чтобы условие читалось словами
   *  («Страна — Казахстан»), а не ключами. Без них условие покажется по
   *  сырым ключам: хуже, но всё же читаемо. */
  fields?: SubjectField[];
  /** Раскладка для узкой колонки: рядом этапы не поместятся, поэтому
   *  параллельность показывается иначе — см. докстринг модуля. */
  compact?: boolean;
}

export function ProcessTimeline({
  process,
  stageStateLabels = {},
  taskStateLabels = {},
  fields = [],
  compact = false,
}: Props) {
  const { t } = useTranslation();
  const groups = groupStages(process.stages);

  if (groups.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        {t('signoff.timeline.noStages')}
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
                  {t('signoff.timeline.parallel', { count: group.length })}
                </Badge>
              )}
            </div>

            <div
              className={cn(
                'grid gap-3',
                // Рядом — только в широкой колонке. В узкой этапы всё равно
                // встанут друг под друга, и «одновременно» подменилось бы
                // «сначала он, потом она»; там параллельность держат скобка
                // слева и плашка «параллельно · N».
                group.length > 1
                  && (compact ? 'border-l-2 border-dashed pl-3' : 'md:grid-cols-2'),
              )}
            >
              {group.map((stage) => (
                <div
                  key={stage.id}
                  className={cn(
                    'rounded-lg border p-3',
                    stage.state === 'active' && 'border-amber-500/40 bg-amber-500/5',
                    stage.state === 'rejected' && 'border-destructive/40',
                    stage.state === 'rework' && 'border-sky-500/40 bg-sky-500/5',
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
                    {/* У этапа подписи кворум не значит ничего: согласующий
                        там ровно один, и «нужны все» из одного человека
                        только путало бы. */}
                    {stage.approver_kind === 'initiator'
                      ? t('signoff.timeline.initiatorSigns')
                      : QUORUM_LABELS[stage.quorum] ?? stage.quorum}
                    {stage.decided_at && ` · ${formatMoment(stage.decided_at)}`}
                  </p>
                  {stage.requires_attachment && (
                    <p className="mt-1 flex items-center gap-1.5 text-xs text-muted-foreground">
                      <PenLine className="h-3.5 w-3.5 shrink-0" />
                      {t('signoff.timeline.pdfRequired')}
                    </p>
                  )}
                  {stage.requires_comment && (
                    <p className="mt-1 flex items-center gap-1.5 text-xs text-muted-foreground">
                      <MessageSquare className="h-3.5 w-3.5 shrink-0" />
                      согласование только с пояснением
                    </p>
                  )}
                  {stage.matched_by !== 'always' && (
                    <p className="mt-1 flex items-start gap-1.5 text-xs text-muted-foreground">
                      <Split className="h-3.5 w-3.5 shrink-0 mt-px" />
                      <span className="break-words">
                        {stage.matched_by === 'fallback'
                          ? t('signoff.timeline.otherwiseBranch')
                          : conditionText(stage.condition, fields)}
                      </span>
                    </p>
                  )}
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
