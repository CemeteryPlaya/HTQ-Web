/**
 * Карточка согласования: ход по этапам, решения, отзыв.
 *
 * Две кнопки решения появляются здесь только тогда, когда у текущего
 * пользователя на АКТИВНОМ этапе есть свой запрос в состоянии «ожидает».
 * Право решать проверяет бэкенд по самой задаче — админский токен на чужой
 * получит 409, — но показывать кнопку, которая заведомо вернёт ошибку,
 * незачем, поэтому те же условия воспроизведены и здесь.
 *
 * **Отзыв ≠ отказ.** Отозвать может инициатор или администратор, и объект
 * при этом возвращается в «черновик»: его можно доработать и отправить
 * снова. Отказ — решение согласующего, и он отклоняет весь процесс сразу.
 */

import { useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Check, Loader2, Undo2, X } from 'lucide-react';
import { toast } from 'sonner';

import { SignoffShell } from '@/components/signoff/SignoffShell';
import { SubjectLink } from '@/components/signoff/SubjectLink';
import {
  DecisionDialog,
  type DecisionKind,
} from '@/components/signoff/DecisionDialog';
import { ProcessTimeline } from '@/components/signoff/ProcessTimeline';
import { formatMoment } from '@/components/signoff/format';
import { ProcessStateBadge } from '@/components/signoff/states';
import { labelMap } from '@/components/signoff/labels';
import { reportApiError } from '@/components/signoff/apiError';
import { Button } from '@/components/ui/button';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { signoffApi } from '@/api/signoff';
import { useActiveProfile } from '@/hooks/useActiveProfile';
import { hasAnyRole } from '@/lib/auth/roles';

const ADMIN_ROLES = ['admin', 'superuser', 'staff'] as const;

const ProcessDetail = () => {
  const { id } = useParams<{ id: string }>();
  const processId = Number(id);
  const queryClient = useQueryClient();

  const { activeProfile } = useActiveProfile();
  const myId = activeProfile?.id ? Number(activeProfile.id) : null;
  const isAdmin = hasAnyRole(activeProfile?.roles ?? [], ADMIN_ROLES);

  const [target, setTarget] = useState<
    { taskId: number; kind: DecisionKind; subjectLabel: string } | null
  >(null);

  const {
    data: process,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ['signoff', 'process', processId],
    queryFn: () => signoffApi.getProcess(processId).then((r) => r.data),
    enabled: Number.isFinite(processId),
  });

  const { data: enums } = useQuery({
    queryKey: ['signoff', 'enums'],
    queryFn: () => signoffApi.getEnums().then((r) => r.data),
  });

  const cancel = useMutation({
    mutationFn: () => signoffApi.cancelProcess(processId).then((r) => r.data),
    onSuccess: () => {
      toast.success('Согласование отозвано — объект вернулся в черновик');
      queryClient.invalidateQueries({ queryKey: ['signoff'] });
      queryClient.invalidateQueries({ queryKey: ['contracts'] });
    },
    // 403 — «отозвать может только инициатор или администратор»;
    // 409 — согласование уже завершено.
    onError: (err) => reportApiError(err, 'Не удалось отозвать согласование'),
  });

  /** Мой запрос на активном этапе — если он есть, решение за мной. */
  const myPendingTask = useMemo(() => {
    if (!process || myId === null) return null;
    for (const stage of process.stages) {
      if (stage.state !== 'active') continue;
      const task = stage.tasks.find(
        (row) => row.user_id === myId && row.state === 'pending',
      );
      if (task) return task;
    }
    return null;
  }, [process, myId]);

  const canCancel =
    process?.state === 'pending'
    && (isAdmin || (myId !== null && process.initiator_id === myId));

  const subjectLabel = process
    ? process.subject_title ?? `${process.subject_type} #${process.subject_id}`
    : '';

  return (
    <SignoffShell>
      <Link
        to="/signoff/processes"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors mb-4"
      >
        <ArrowLeft className="h-4 w-4" />
        Ко всем согласованиям
      </Link>

      {isLoading ? (
        <div className="space-y-3">
          <Skeleton className="h-10 w-72" />
          <Skeleton className="h-40 w-full" />
        </div>
      ) : isError || !process ? (
        <p className="text-sm text-destructive">
          Согласование не найдено или недоступно.
        </p>
      ) : (
        <>
          <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="text-3xl font-bold">Согласование #{process.id}</h1>
                <ProcessStateBadge
                  state={process.state}
                  label={labelMap(enums?.process_state)[process.state]}
                />
              </div>
              <p className="text-sm text-muted-foreground mt-1">
                Запущено {formatMoment(process.created_at)}
                {process.finished_at
                  && ` · завершено ${formatMoment(process.finished_at)}`}
              </p>
            </div>

            <div className="flex flex-wrap gap-2">
              {myPendingTask && (
                <>
                  <Button
                    onClick={() =>
                      setTarget({
                        taskId: myPendingTask.id,
                        kind: 'approve',
                        subjectLabel,
                      })
                    }
                  >
                    <Check className="mr-1.5 h-4 w-4" />
                    Согласовать
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() =>
                      setTarget({
                        taskId: myPendingTask.id,
                        kind: 'reject',
                        subjectLabel,
                      })
                    }
                  >
                    <X className="mr-1.5 h-4 w-4" />
                    Отклонить
                  </Button>
                </>
              )}

              {canCancel && (
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <Button variant="ghost" disabled={cancel.isPending}>
                      {cancel.isPending ? (
                        <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                      ) : (
                        <Undo2 className="mr-1.5 h-4 w-4" />
                      )}
                      Отозвать
                    </Button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>Отозвать согласование?</AlertDialogTitle>
                      <AlertDialogDescription>
                        Уже принятые решения погаснут, а объект вернётся в
                        черновик — его можно будет доработать и отправить
                        заново. Это не отказ: причину указывать не нужно.
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>Не отзывать</AlertDialogCancel>
                      <AlertDialogAction onClick={() => cancel.mutate()}>
                        Отозвать
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              )}
            </div>
          </div>

          <Card className="mb-6">
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Что согласуется</CardTitle>
            </CardHeader>
            <CardContent className="space-y-1">
              <SubjectLink
                title={process.subject_title}
                url={process.subject_url}
                subjectType={process.subject_type}
                subjectId={process.subject_id}
                className="text-base"
              />
              <p className="text-xs text-muted-foreground">
                {process.subject_type} · id {process.subject_id}
                {process.initiator_id !== null
                  && ` · отправил пользователь #${process.initiator_id}`}
              </p>
              {!process.subject_title && (
                <p className="text-xs text-muted-foreground">
                  Заголовок объекта недоступен — его аппка не смогла его
                  построить (тип не зарегистрирован или строка удалена).
                </p>
              )}
            </CardContent>
          </Card>

          <h2 className="text-lg font-semibold mb-3">Ход согласования</h2>
          <ProcessTimeline
            process={process}
            stageStateLabels={labelMap(enums?.stage_state)}
            taskStateLabels={labelMap(enums?.task_state)}
          />

          <DecisionDialog
            target={target}
            onOpenChange={(open) => !open && setTarget(null)}
            onDecided={() => {
              queryClient.invalidateQueries({ queryKey: ['signoff'] });
              queryClient.invalidateQueries({ queryKey: ['contracts'] });
            }}
          />
        </>
      )}
    </SignoffShell>
  );
};

export default ProcessDetail;
