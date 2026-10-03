/**
 * Карточка процесса ДОЧЕРНЕЙ компании, открытая из холдинга (мастер-план
 * БЗО, B8.1).
 *
 * Директора — в штате холдинга, а документы дочерних согласуются в их
 * схемах. Маршрут дочерней может разрешить решение прямо из очереди холдинга
 * — тогда задача открывается здесь, на адресе холдинга: шапка документа, его
 * поля и позиции (сводка `summary` — её собирает модуль документа, решение
 * Руслана 02.10) и ход согласования. Тела документа и его файлов здесь нет —
 * их таблицы живут в схеме дочерней; для них кнопка «Открыть в компании»,
 * если у человека есть туда доступ.
 *
 * Решение отправляется через холдинг (`decideForeign`), без документа к
 * решению: этап, требующий его или выбора варианта, отсюда не решается —
 * вместо кнопок карточка объясняет почему (`direct_blocker`).
 */
import { useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Building2, Check, Undo2, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { signoffApi } from '@/api/signoff';
import { DecisionDialog, type DecisionTarget } from '@/components/signoff/DecisionDialog';
import { ProcessTimeline } from '@/components/signoff/ProcessTimeline';
import { SignoffShell } from '@/components/signoff/SignoffShell';
import { formatMoment } from '@/components/signoff/format';
import { labelMap } from '@/components/signoff/labels';
import { ProcessStateBadge } from '@/components/signoff/states';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { switchCompany } from '@/lib/auth/companySwitch';
import type { ApprovalProcess, DecisionInput, SubjectSummary } from '@/types/signoff';

const ForeignProcessDetail = () => {
  const { t } = useTranslation();
  const { company = '', id } = useParams<{ company: string; id: string }>();
  const processId = Number(id);
  const queryClient = useQueryClient();
  const [target, setTarget] = useState<DecisionTarget | null>(null);
  const key = ['signoff', 'foreign-process', company, processId];

  const { data: process, isLoading, isError } = useQuery({
    queryKey: key,
    queryFn: () => signoffApi.foreignProcess(company, processId).then((r) => r.data),
    enabled: Boolean(company) && Number.isFinite(processId),
  });
  const { data: enums } = useQuery({
    queryKey: ['signoff', 'enums'],
    queryFn: () => signoffApi.getEnums().then((r) => r.data),
  });
  const { data: subjects = [] } = useQuery({
    queryKey: ['signoff', 'subjects'],
    queryFn: () => signoffApi.listSubjects().then((r) => r.data),
  });
  const fields = useMemo(
    () => subjects.find((row) => row.subject_type === process?.subject_type)?.fields ?? [],
    [subjects, process],
  );

  /** Этап своей задачи — у него берутся требования для диалога решения. */
  const myStage = useMemo(
    () => process?.stages.find((stage) =>
      stage.tasks.some((task) => task.id === process.my_task_id)) ?? null,
    [process],
  );
  const canDecide = Boolean(process?.state === 'pending' && process.my_task_id
    && process.direct_allowed);
  const subjectLabel = process
    ? process.subject_title ?? `${process.subject_type} #${process.subject_id}`
    : '';

  const decideForeign = (taskId: number, input: DecisionInput): Promise<ApprovalProcess> =>
    signoffApi.decideForeign(company, taskId, input).then((r) => r.data);

  const openTarget = (kind: DecisionTarget['kind']) => {
    if (!process?.my_task_id) return;
    setTarget({
      taskId: process.my_task_id,
      kind,
      subjectLabel,
      requiresComment: kind === 'approve' ? myStage?.requires_comment : undefined,
      stageName: myStage?.name,
      requirementLabel: kind === 'approve' ? myStage?.requirement_label : undefined,
    });
  };

  return (
    <SignoffShell>
      <Link
        to="/signoff"
        className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" />
        {t('signoff.foreign.back', 'К очереди «Ждёт меня»')}
      </Link>

      {isLoading ? (
        <div className="space-y-3">
          <Skeleton className="h-10 w-72" />
          <Skeleton className="h-40 w-full" />
        </div>
      ) : isError || !process ? (
        <p className="text-sm text-destructive">
          {t('signoff.foreign.notFound', 'Согласование не найдено или оно не ваше.')}
        </p>
      ) : (
        <>
          <div className="mb-6 min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="break-words text-3xl font-bold">{subjectLabel}</h1>
              <ProcessStateBadge
                state={process.state}
                label={labelMap(enums?.process_state)[process.state]}
              />
              <Badge variant="outline" className="gap-1">
                <Building2 className="h-3.5 w-3.5" />
                {process.company.name}
              </Badge>
            </div>
            <p className="mt-1 text-sm text-muted-foreground">
              {t('signoff.detail.startedAt', { stamp: formatMoment(process.created_at) })}
              {process.initiator_name && ` · ${process.initiator_name}`}
            </p>
          </div>

          <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem] lg:items-start">
            <aside className="min-w-0 space-y-4 lg:order-2 lg:sticky lg:top-20">
              {canDecide && (
                <div className="flex flex-col gap-2">
                  <Button onClick={() => openTarget('approve')}>
                    <Check className="mr-2 h-4 w-4" />
                    {t('signoff.decision.approve.action')}
                  </Button>
                  <Button variant="outline" onClick={() => openTarget('rework')}>
                    <Undo2 className="mr-2 h-4 w-4" />
                    {t('signoff.decision.rework.action')}
                  </Button>
                  <Button variant="outline" className="text-destructive"
                    onClick={() => openTarget('reject')}>
                    <X className="mr-2 h-4 w-4" />
                    {t('signoff.decision.reject.action')}
                  </Button>
                </div>
              )}
              {process.my_task_id && !process.direct_allowed && process.direct_blocker && (
                <p className="rounded-lg border border-amber-500/50 bg-amber-500/10 p-3 text-sm">
                  {process.direct_blocker}
                </p>
              )}
              {process.can_enter && (
                <Button variant="outline" className="w-full"
                  onClick={() => switchCompany(process.company,
                    process.subject_url ?? `/signoff/processes/${process.id}`)}>
                  <Building2 className="mr-2 h-4 w-4" />
                  {t('signoff.foreign.openInCompany', 'Открыть документ в {{company}}',
                    { company: process.company.name })}
                </Button>
              )}
              <p className="text-xs text-muted-foreground">
                {t('signoff.foreign.note',
                  'Документ компании «{{company}}». Его файлы и полную карточку видно на адресе компании.',
                  { company: process.company.name })}
              </p>
            </aside>

            <section className="min-w-0 space-y-6 lg:order-1">
              <SummaryCard summary={process.summary} />
              <div>
                <h2 className="mb-3 text-lg font-semibold">{t('signoff.detail.progress')}</h2>
                <ProcessTimeline
                  process={process}
                  stageStateLabels={labelMap(enums?.stage_state)}
                  taskStateLabels={labelMap(enums?.task_state)}
                  fields={fields}
                  compact
                />
              </div>
            </section>
          </div>

          <DecisionDialog
            target={target}
            decide={decideForeign}
            onOpenChange={(open) => !open && setTarget(null)}
            onDecided={(updated) => {
              queryClient.setQueryData(key, updated);
              queryClient.invalidateQueries({ queryKey: ['signoff'] });
            }}
          />
        </>
      )}
    </SignoffShell>
  );
};

/** Поля и позиции документа — готовыми строками от его модуля. */
function SummaryCard({ summary }: { summary: SubjectSummary | null }) {
  const { t } = useTranslation();
  if (!summary) {
    return (
      <p className="rounded-lg border border-dashed p-6 text-sm text-muted-foreground">
        {t('signoff.foreign.noSummary',
          'Сводки документа нет — откройте его на адресе компании.')}
      </p>
    );
  }
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">{t('signoff.detail.document')}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <dl className="grid gap-x-6 gap-y-2 sm:grid-cols-2">
          {summary.fields.map((field) => (
            <div key={field.label} className="min-w-0">
              <dt className="text-xs text-muted-foreground">{field.label}</dt>
              <dd className="break-words text-sm font-medium">{field.value}</dd>
            </div>
          ))}
        </dl>
        {summary.lines && summary.lines.rows.length > 0 && (
          <div className="overflow-x-auto rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  {summary.lines.columns.map((column) => (
                    <TableHead key={column.key}
                      className={column.align === 'right' ? 'text-right' : undefined}>
                      {column.label}
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {summary.lines.rows.map((row, index) => (
                  <TableRow key={index}>
                    {summary.lines!.columns.map((column) => (
                      <TableCell key={column.key}
                        className={column.align === 'right' ? 'whitespace-nowrap text-right' : undefined}>
                        {row[column.key] ?? '—'}
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
                {summary.lines.total && (
                  <TableRow>
                    <TableCell colSpan={summary.lines.columns.length - 1} className="font-medium">
                      {summary.lines.total.label}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-right font-medium">
                      {summary.lines.total.value}
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default ForeignProcessDetail;
