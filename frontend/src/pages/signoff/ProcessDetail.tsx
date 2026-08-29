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
 * Три кнопки решения появляются здесь только тогда, когда у текущего
 * пользователя на АКТИВНОМ этапе есть свой запрос в состоянии «ожидает».
 * Право решать проверяет бэкенд по самой задаче — админский токен на чужой
 * получит 409, — но показывать кнопку, которая заведомо вернёт ошибку,
 * незачем, поэтому те же условия воспроизведены и здесь.
 *
 * **Четыре действия, и все разные.** Их легко перепутать, поэтому:
 *
 * - «Согласовать» — этап пройден, процесс идёт дальше.
 * - «На доработку» — решение согласующего: круг закрывается, объект
 *   ОТКРЫВАЕТСЯ автору для правки, доработанный отправляется заново.
 * - «Отклонить» — тоже решение согласующего, круг закрывается так же, но
 *   объект остаётся ЗАПЕРТЫМ: это «документ не годится», а не «поправьте».
 * - «Отозвать» — не решение: инициатор (или администратор) забирает СВОЮ
 *   заявку, пока её не рассмотрели, объект возвращается в черновик.
 *
 * Отдельно — «Вернуть на доработку» на УЖЕ ЗАКРЫТОМ круге: единственный
 * способ отпереть согласованный или отклонённый объект, доступен
 * администратору и согласующим этого процесса.
 */

import { Suspense, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ArrowLeft,
  Check,
  ChevronDown,
  ExternalLink,
  Loader2,
  Undo2,
  User,
  X,
} from 'lucide-react';
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
import { reportApiError } from '@/lib/apiError';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { Textarea } from '@/components/ui/textarea';
import { signoffApi } from '@/api/signoff';
import { useActiveProfile } from '@/hooks/useActiveProfile';
import { usePermissions } from '@/hooks/usePermissions';
import { useTranslation } from 'react-i18next';

const ProcessDetail = () => {
  const { t } = useTranslation();
  const { id } = useParams<{ id: string }>();
  const processId = Number(id);
  const queryClient = useQueryClient();

  const { activeProfile } = useActiveProfile();
  const permissions = usePermissions();
  const myId = activeProfile?.id ? Number(activeProfile.id) : null;
  // Уровень модуля вместо платформенных флагов — см. пояснение в
  // components/signoff/SignoffShell.tsx: до навешивания модульного гейта на
  // ручки согласования интерфейс строже сервера, и это лечится выдачей роли.
  const isAdmin = permissions.atLeast('signoff', 'admin');

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
      toast.success(t('signoff.detail.withdrawn'));
      queryClient.invalidateQueries({ queryKey: ['signoff'] });
      queryClient.invalidateQueries({ queryKey: ['contracts'] });
    },
    // 403 — «отозвать может только инициатор или администратор»;
    // 409 — согласование уже завершено.
    onError: (err) => reportApiError(err, t('signoff.detail.withdrawError')),
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

  /** Кто вправе отпереть уже решённый объект — те же условия, что на
   *  бэкенде (`views.ProcessReworkView`): администратор или согласующий
   *  ЭТОГО процесса. Любая его задача, в любом состоянии: тот, чей запрос
   *  погас как «не потребовалось» при кворуме «достаточно одного», — такой
   *  же участник круга.
   *
   *  Инициатора здесь намеренно нет, в отличие от отзыва: отзывают свою
   *  заявку, пока её не рассмотрели, а отпереть решённое по собственному
   *  желанию значило бы обойти чужое решение. */
  const iAmApprover =
    myId !== null
    && (process?.stages ?? []).some((stage) =>
      stage.tasks.some((task) => task.user_id === myId));

  const canRework =
    (process?.state === 'approved' || process?.state === 'rejected')
    && (isAdmin || iAmApprover);

  const [reworkOpen, setReworkOpen] = useState(false);
  const [reworkComment, setReworkComment] = useState('');
  // Диалоги отзыва и возврата открываются из общего меню «Действия», поэтому
  // их состояние управляется здесь, а не через `AlertDialogTrigger`.
  const [cancelOpen, setCancelOpen] = useState(false);

  const rework = useMutation({
    mutationFn: () =>
      signoffApi
        .reworkProcess(processId, { comment: reworkComment })
        .then((r) => r.data),
    onSuccess: () => {
      toast.success(t('signoff.detail.reworked'));
      setReworkOpen(false);
      setReworkComment('');
      queryClient.invalidateQueries({ queryKey: ['signoff'] });
      queryClient.invalidateQueries({ queryKey: ['contracts'] });
    },
    // 403 — «может согласующий этого процесса или администратор»;
    // 409 — согласование ещё идёт либо объект и так открыт.
    onError: (err) => reportApiError(err, t('signoff.detail.reworkError')),
  });

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
        {t('signoff.detail.backToList')}
      </Link>

      {isLoading ? (
        <div className="space-y-3">
          <Skeleton className="h-10 w-72" />
          <Skeleton className="h-40 w-full" />
        </div>
      ) : isError || !process ? (
        <p className="text-sm text-destructive">
          {t('signoff.detail.notFound')}
        </p>
      ) : (
        <>
          <div className="mb-6 min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-3xl font-bold">{t('signoff.history.processNumber', { id: process.id })}</h1>
              <ProcessStateBadge
                state={process.state}
                label={labelMap(enums?.process_state)[process.state]}
              />
            </div>
            <p className="text-sm text-muted-foreground mt-1">
              {t('signoff.detail.startedAt', { stamp: formatMoment(process.created_at) })}
              {process.finished_at
                && t('signoff.history.finishedAt', { stamp: formatMoment(process.finished_at) })}
            </p>
            {/* Кто отправил объект на согласование. Имя разворачивает бэкенд;
                если пользователь удалён или неизвестен — остаётся id. */}
            {process.initiator_id !== null && (
              <p className="mt-1 inline-flex items-center gap-1.5 text-sm text-muted-foreground">
                <User className="h-3.5 w-3.5 shrink-0 opacity-70" />
                {t('signoff.detail.initiator')}{' '}
                <span className="font-medium text-foreground">
                  {process.initiator_name
                    ?? t('signoff.userNumber', { id: process.initiator_id })}
                </span>
              </p>
            )}
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
              {(myPending || canCancel || canRework) && (
                <div className="flex flex-wrap gap-2">
                  {/* Все действия над согласованием собраны в одно меню
                      «Действия»: у согласующего-администратора их набирается
                      до четырёх, и ряд одинаковых кнопок читается хуже, чем
                      список с явными подписями. */}
                  {/* modal={false}: модальное меню держит на body scroll-lock
                      с `pointer-events: none`; открытый из его пункта диалог
                      добавляет свой, и при закрытии диалога блокировка body
                      остаётся — страница перестаёт кликаться. */}
                  <DropdownMenu modal={false}>
                    <DropdownMenuTrigger asChild>
                      <Button
                        className="w-full justify-between"
                        disabled={cancel.isPending || rework.isPending}
                      >
                        {cancel.isPending || rework.isPending ? (
                          <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                        ) : null}
                        {t('common.actions')}
                        <ChevronDown className="ml-1.5 h-4 w-4 opacity-70" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="start" className="w-56">
                      {myPending && (
                        <>
                          <DropdownMenuItem
                            onClick={() =>
                              setTarget({
                                taskId: myPending.task.id,
                                kind: 'approve',
                                subjectLabel,
                                requiresAttachment:
                                  myPending.stage.requires_attachment,
                                requiresComment:
                                  myPending.stage.requires_comment,
                                attachedFileId: myPending.task.file_id,
                              })
                            }
                          >
                            <Check className="mr-2 h-4 w-4" />
                            {t('signoff.decision.approve.action')}
                          </DropdownMenuItem>
                          {/* Отклонить и вернуть на доработку — РАЗНЫЕ решения:
                              отклонённый объект остаётся запертым, возвращённый
                              открывается автору для правки. */}
                          <DropdownMenuItem
                            onClick={() =>
                              setTarget({
                                taskId: myPending.task.id,
                                kind: 'rework',
                                subjectLabel,
                              })
                            }
                          >
                            <Undo2 className="mr-2 h-4 w-4" />
                            {t('signoff.decision.rework.action')}
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            className="text-destructive focus:text-destructive"
                            onClick={() =>
                              setTarget({
                                taskId: myPending.task.id,
                                kind: 'reject',
                                subjectLabel,
                              })
                            }
                          >
                            <X className="mr-2 h-4 w-4" />
                            {t('signoff.decision.reject.action')}
                          </DropdownMenuItem>
                        </>
                      )}

                      {myPending && (canRework || canCancel) && (
                        <DropdownMenuSeparator />
                      )}

                      {canRework && (
                        <DropdownMenuItem onClick={() => setReworkOpen(true)}>
                          <Undo2 className="mr-2 h-4 w-4" />
                          {t('signoff.decision.rework.title')}
                        </DropdownMenuItem>
                      )}

                      {canCancel && (
                        <DropdownMenuItem onClick={() => setCancelOpen(true)}>
                          <Undo2 className="mr-2 h-4 w-4" />
                          {t('signoff.detail.withdraw')}
                        </DropdownMenuItem>
                      )}
                    </DropdownMenuContent>
                  </DropdownMenu>

                  {canRework && (
                    <AlertDialog
                      open={reworkOpen}
                      onOpenChange={(open) => {
                        setReworkOpen(open);
                        if (!open) setReworkComment('');
                      }}
                    >
                      <AlertDialogContent>
                        <AlertDialogHeader>
                          <AlertDialogTitle>{t('signoff.detail.reworkConfirmTitle')}</AlertDialogTitle>
                          <AlertDialogDescription>
                            {process.state === 'approved'
                              ? t('signoff.detail.reworkFromApproved')
                              : t('signoff.detail.reworkFromRejected')}
                          </AlertDialogDescription>
                        </AlertDialogHeader>
                        <div className="space-y-2">
                          <Label htmlFor="signoff-rework-comment">
                            {t('signoff.detail.whatToFix')}
                          </Label>
                          <Textarea
                            id="signoff-rework-comment"
                            value={reworkComment}
                            onChange={(event) => setReworkComment(event.target.value)}
                            maxLength={2000}
                            rows={4}
                            placeholder={t('signoff.detail.reworkPlaceholder')}
                          />
                        </div>
                        <AlertDialogFooter>
                          <AlertDialogCancel>{t('signoff.detail.reworkCancel')}</AlertDialogCancel>
                          {/* Не `AlertDialogAction`: тот закрывает диалог сам,
                              и пустой комментарий закрыл бы его вместе с
                              подсказкой, ради которой всё и затевалось. */}
                          <Button
                            disabled={!reworkComment.trim() || rework.isPending}
                            onClick={() => rework.mutate()}
                          >
                            {t('signoff.detail.reworkConfirm')}
                          </Button>
                        </AlertDialogFooter>
                      </AlertDialogContent>
                    </AlertDialog>
                  )}

                  {canCancel && (
                    <AlertDialog open={cancelOpen} onOpenChange={setCancelOpen}>
                      <AlertDialogContent>
                        <AlertDialogHeader>
                          <AlertDialogTitle>{t('signoff.detail.withdrawConfirmTitle')}</AlertDialogTitle>
                          <AlertDialogDescription>
                            {t('signoff.detail.withdrawConfirmBody')}
                          </AlertDialogDescription>
                        </AlertDialogHeader>
                        <AlertDialogFooter>
                          <AlertDialogCancel>{t('signoff.detail.withdrawCancel')}</AlertDialogCancel>
                          <AlertDialogAction onClick={() => cancel.mutate()}>
                            {t('signoff.detail.withdraw')}
                          </AlertDialogAction>
                        </AlertDialogFooter>
                      </AlertDialogContent>
                    </AlertDialog>
                  )}
                </div>
              )}

              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-base">{t('signoff.detail.whatIsApproved')}</CardTitle>
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
                      && t('signoff.detail.submittedBy', {
                        name: process.initiator_name
                          ?? t('signoff.userNumberLower', { id: process.initiator_id }),
                      })}
                  </p>
                  {!process.subject_title && (
                    <p className="text-xs text-muted-foreground">
                      {t('signoff.detail.titleUnavailable')}
                    </p>
                  )}

                  {readableFacts.length > 0 && (
                    <div className="pt-2">
                      <p className="text-xs text-muted-foreground mb-1.5">
                        {t('signoff.detail.snapshotHint')}
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
                <h2 className="text-lg font-semibold mb-3">{t('signoff.detail.progress')}</h2>
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
                <h2 className="text-lg font-semibold">{t('signoff.detail.document')}</h2>
                {isRoutableUrl(process.subject_url) && (
                  <Link
                    to={process.subject_url as string}
                    className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground hover:underline underline-offset-2"
                  >
                    {t('signoff.openSubjectCard')}
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
                  {t('signoff.detail.previewUnsupported')}
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
