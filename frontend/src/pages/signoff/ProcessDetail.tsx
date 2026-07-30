/**
 * Карточка согласования: сам документ, ход по этапам, решения, отзыв.
 *
 * Документ показывается ЗДЕСЬ, а не по ссылке в чужой раздел: уходя на
 * страницу бюджета, согласующий терял и боковое меню согласований, и кнопки
 * решения — а именно за решением он и пришёл. Тело карточки предметной
 * аппки берётся из `app/signoffSubjectViews` (там же объяснено, почему карта
 * лежит в слое сборки приложения).
 *
 * Раскладка — как в системах документооборота: документ занимает основную
 * колонку, а всё про процесс (кнопки, реквизиты отправки, этапы) собрано в
 * липкой панели справа. Порядок отражает, чем человек занят: читает он
 * документ, а маршрут подсматривает. На узком экране панель встаёт первой —
 * кнопка решения важнее реквизитов.
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

import { Suspense, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Check, ExternalLink, Loader2, Undo2, X } from 'lucide-react';
import { toast } from 'sonner';

import { SIGNOFF_SUBJECT_VIEWS } from '@/app/signoffSubjectViews';
import { SignoffShell } from '@/components/signoff/SignoffShell';
import { SubjectLink } from '@/components/signoff/SubjectLink';
import { isRoutableUrl } from '@/components/signoff/routable';
import {
  DecisionDialog,
  type DecisionTarget,
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

  const [target, setTarget] = useState<DecisionTarget | null>(null);

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

  // Нужны только ради подписей в условиях веток и в снимке фактов: сами
  // факты — это `{admin_country_id: 3}`, а человеку надо «Страна
  // администратора бюджета — Казахстан».
  const { data: subjects = [] } = useQuery({
    queryKey: ['signoff', 'subjects'],
    queryFn: () => signoffApi.listSubjects().then((r) => r.data),
  });

  const fields = useMemo(
    () =>
      subjects.find((item) => item.subject_type === process?.subject_type)?.fields
      ?? [],
    [subjects, process],
  );

  /** Факты объекта человеческими словами. Показываются только те, что тип
   *  объявил ветвимыми: остальные ключи в снимке — служебные, и толковать их
   *  в интерфейсе нечем. */
  const readableFacts = useMemo(
    () =>
      fields
        .filter((field) => field.key in (process?.subject_facts ?? {}))
        .map((field) => {
          const raw = process?.subject_facts[field.key];
          const option = field.options.find((item) => item.value === raw);
          return {
            key: field.key,
            label: field.label || field.key,
            value: option ? option.label : String(raw ?? '—'),
          };
        }),
    [fields, process],
  );

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

  /** Мой запрос на активном этапе — если он есть, решение за мной.
   *
   *  Вместе с задачей нужен и её ЭТАП: требование документа объявлено на
   *  этапе (`requires_attachment`), а спрашивать файл будет диалог решения. */
  const myPending = useMemo(() => {
    if (!process || myId === null) return null;
    for (const stage of process.stages) {
      if (stage.state !== 'active') continue;
      const task = stage.tasks.find(
        (row) => row.user_id === myId && row.state === 'pending',
      );
      if (task) return { task, stage };
    }
    return null;
  }, [process, myId]);

  const canCancel =
    process?.state === 'pending'
    && (isAdmin || (myId !== null && process.initiator_id === myId));

  const subjectLabel = process
    ? process.subject_title ?? `${process.subject_type} #${process.subject_id}`
    : '';

  /** Чем показать сам документ. Тип, не заявивший представления, обходится
   *  заголовком и ссылкой — карточка от этого не ломается. */
  const SubjectView = process
    ? SIGNOFF_SUBJECT_VIEWS[process.subject_type]
    : undefined;

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
          <div className="mb-6 min-w-0">
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

          {/* Документ — основное содержимое, ход согласования — панель рядом.
              Так это устроено в системах документооборота, и по делу: читают
              документ, а маршрут подсматривают. Панель липкая — решение
              должно быть под рукой на любой прокрутке длинного документа, —
              и на узком экране встаёт ПЕРВОЙ: кнопки важнее реквизитов. */}
          <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem] lg:items-start">
            {/* `top-20` — под шапкой приложения: она `sticky top-0` и в
                неприжатом состоянии занимает 5rem. Меньший отступ загнал бы
                панель под неё. */}
            <aside className="min-w-0 space-y-4 lg:order-2 lg:sticky lg:top-20 lg:max-h-[calc(100vh-6rem)] lg:overflow-y-auto lg:pb-2">
              {(myPending || canCancel) && (
                <div className="flex flex-wrap gap-2">
                  {myPending && (
                    <>
                      <Button
                        onClick={() =>
                          setTarget({
                            taskId: myPending.task.id,
                            kind: 'approve',
                            subjectLabel,
                            requiresAttachment: myPending.stage.requires_attachment,
                            attachedFileId: myPending.task.file_id,
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
                            taskId: myPending.task.id,
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
              )}

              <Card>
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

                  {readableFacts.length > 0 && (
                    <div className="pt-2">
                      <p className="text-xs text-muted-foreground mb-1.5">
                        Каким объект был на момент отправки — по этим значениям
                        выбирались этапы. Позднейшие правки объекта состав
                        согласующих уже не меняют.
                      </p>
                      <dl className="flex flex-wrap gap-x-4 gap-y-1">
                        {readableFacts.map((fact) => (
                          <div key={fact.key} className="flex items-baseline gap-1.5">
                            <dt className="text-xs text-muted-foreground">
                              {fact.label}:
                            </dt>
                            <dd className="text-xs font-medium">{fact.value}</dd>
                          </div>
                        ))}
                      </dl>
                    </div>
                  )}
                </CardContent>
              </Card>

              <div>
                <h2 className="text-lg font-semibold mb-3">Ход согласования</h2>
                <ProcessTimeline
                  process={process}
                  stageStateLabels={labelMap(enums?.stage_state)}
                  taskStateLabels={labelMap(enums?.task_state)}
                  fields={fields}
                  compact
                />
              </div>
            </aside>

            <section className="min-w-0 lg:order-1">
              <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
                <h2 className="text-lg font-semibold">Документ</h2>
                {isRoutableUrl(process.subject_url) && (
                  <Link
                    to={process.subject_url as string}
                    className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground hover:underline underline-offset-2"
                  >
                    открыть карточку в своём разделе
                    <ExternalLink className="h-3 w-3 shrink-0 opacity-60" />
                  </Link>
                )}
              </div>
              {SubjectView ? (
                // Тело карточки предметной аппки. Свои ошибки (404 объекта,
                // 503 выключенного домена) оно показывает само — страница
                // согласования от этого не разваливается.
                <Suspense fallback={<Skeleton className="h-64 w-full" />}>
                  <SubjectView id={process.subject_id} embedded />
                </Suspense>
              ) : (
                // Тип есть в реестре бэкенда, но своего представления во
                // фронтенде не заявил. Согласовать всё равно можно — по
                // заголовку, фактам и ссылке в панели.
                <p className="rounded-lg border border-dashed p-6 text-sm text-muted-foreground">
                  Показать документ этого типа интерфейс пока не умеет —
                  откройте его карточку по ссылке выше.
                </p>
              )}
            </section>
          </div>

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
