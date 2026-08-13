/**
 * Конструктор маршрута: этапы, их порядок и согласующие.
 *
 * **Вся параллельность здесь — одно число.** Этапы с ОДИНАКОВЫМ `order`
 * идут одновременно, с разным — друг за другом. Отдельной модели графа нет
 * намеренно: заказчику нужны «2, 3 или 5 этапов, параллельно или друг за
 * другом», и целочисленный порядок выражает ровно это. Поэтому редактор
 * группирует этапы по `order` и подписывает группы «шаг N», а не
 * притворяется схемой процесса.
 *
 * **Группа по `order` — она же и ветвление.** У этапа может быть условие, и
 * тогда в процесс он попадёт только если условие сошлось на фактах объекта
 * («страна администратора бюджета — Казахстан»). Отдельной модели ветки нет:
 * ветка — это и есть этап группы со своим условием. Поля, по которым можно
 * ветвить, приходят из `GET /subjects` — их объявляет предметная аппка,
 * захардкодить их здесь невозможно.
 *
 * **Правка маршрута не трогает идущие согласования** — этапы копируются на
 * процесс снимком при запуске. Менять маршрут можно в любой момент, но
 * применится он только к следующим отправкам; об этом сказано на странице,
 * иначе легко ждать, что правка догонит уже начатое.
 *
 * Ограничения бэкенда воспроизведены в интерфейсе, чтобы не ловить их
 * ошибкой: у этапа должен быть хотя бы один согласующий, последний этап
 * маршрута удалить нельзя (маршрут без этапов неисполним), а этап «иначе» не
 * может иметь собственного условия.
 */

import { useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle,
  ArrowLeft,
  GitBranch,
  Loader2,
  MessageSquare,
  Paperclip,
  Pencil,
  PenLine,
  Plus,
  Split,
  Trash2,
} from 'lucide-react';
import { toast } from 'sonner';

import { SignoffShell } from '@/components/signoff/SignoffShell';
import { ApproverPicker } from '@/components/signoff/ApproverPicker';
import { ConditionEditor } from '@/components/signoff/ConditionEditor';
import { conditionText } from '@/components/signoff/format';
import { APPROVER_KIND_LABELS, QUORUM_LABELS } from '@/components/signoff/labels';
import { reportApiError } from '@/lib/apiError';
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
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { Switch } from '@/components/ui/switch';
import { signoffApi } from '@/api/signoff';
import type {
  ApproverKind,
  Condition,
  Quorum,
  RouteStage,
} from '@/types/signoff';

/** Черновик этапа в диалоге. `id === null` — этап ещё не создан. */
interface StageDraft {
  id: number | null;
  order: number;
  name: string;
  quorum: Quorum;
  approverIds: number[];
  condition: Condition;
  isFallback: boolean;
  approverKind: ApproverKind;
  requiresAttachment: boolean;
  requiresComment: boolean;
}

const emptyDraft = (order: number): StageDraft => ({
  id: null,
  order,
  name: '',
  quorum: 'all',
  approverIds: [],
  condition: [],
  isFallback: false,
  approverKind: 'named',
  requiresAttachment: false,
  requiresComment: false,
});

/** Этапы по группам `order`, группы — по возрастанию. */
function groupByOrder(stages: RouteStage[]): [number, RouteStage[]][] {
  const map = new Map<number, RouteStage[]>();
  for (const stage of stages) {
    const bucket = map.get(stage.order);
    if (bucket) bucket.push(stage);
    else map.set(stage.order, [stage]);
  }
  return [...map.entries()].sort(([a], [b]) => a - b);
}

const RouteEditor = () => {
  const { id } = useParams<{ id: string }>();
  const routeId = Number(id);
  const queryClient = useQueryClient();

  const [draft, setDraft] = useState<StageDraft | null>(null);
  const [draftError, setDraftError] = useState('');

  const {
    data: route,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ['signoff', 'route', routeId],
    queryFn: () => signoffApi.getRoute(routeId).then((r) => r.data),
    enabled: Number.isFinite(routeId),
  });

  const { data: subjects = [] } = useQuery({
    queryKey: ['signoff', 'subjects'],
    queryFn: () => signoffApi.listSubjects().then((r) => r.data),
  });

  const subject = useMemo(
    () => subjects.find((s) => s.subject_type === route?.subject_type),
    [subjects, route],
  );
  const subjectLabel = subject?.label ?? route?.subject_type ?? '';
  /** Поля для условий объявляет предметная аппка; пусто — тип не ветвится. */
  const fields = subject?.fields ?? [];

  const groups = useMemo(() => groupByOrder(route?.stages ?? []), [route]);
  const nextOrder = groups.length === 0 ? 1 : groups[groups.length - 1][0] + 1;

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['signoff'] });

  const toggleActive = useMutation({
    mutationFn: (isActive: boolean) =>
      signoffApi.updateRoute(routeId, { is_active: isActive }).then((r) => r.data),
    onSuccess: (updated) => {
      toast.success(updated.is_active ? 'Маршрут включён' : 'Маршрут выключен');
      refresh();
    },
    onError: (err) =>
      reportApiError(err, 'Не удалось изменить состояние маршрута'),
  });

  const renameRoute = useMutation({
    mutationFn: (name: string) =>
      signoffApi.updateRoute(routeId, { name }).then((r) => r.data),
    onSuccess: () => {
      toast.success('Название сохранено');
      refresh();
    },
    onError: (err) => reportApiError(err, 'Не удалось переименовать маршрут'),
  });

  const saveStage = useMutation({
    mutationFn: (stage: StageDraft) => {
      const payload = {
        order: stage.order,
        name: stage.name.trim(),
        quorum: stage.quorum,
        // У этапа подписи список обязан быть пустым: непустой бэкенд
        // отвергнет как противоречие, а не «поймёт, что имелось в виду».
        approver_ids: stage.approverKind === 'named' ? stage.approverIds : [],
        // Условие шлём всегда, в том числе пустым: для PATCH пустой массив —
        // это «снять ветку», и не прислать его значило бы не уметь её снять.
        condition: stage.isFallback ? [] : stage.condition,
        is_fallback: stage.isFallback,
        approver_kind: stage.approverKind,
        requires_attachment: stage.requiresAttachment,
        requires_comment: stage.requiresComment,
      };
      return stage.id === null
        ? signoffApi.addStage(routeId, payload).then((r) => r.data)
        : signoffApi.updateStage(stage.id, payload).then((r) => r.data);
    },
    onSuccess: () => {
      toast.success('Этап сохранён');
      setDraft(null);
      refresh();
    },
    onError: (err) => reportApiError(err, 'Не удалось сохранить этап'),
  });

  const deleteStage = useMutation({
    mutationFn: (stageId: number) => signoffApi.deleteStage(stageId),
    onSuccess: () => {
      toast.success('Этап удалён');
      refresh();
    },
    onError: (err) => reportApiError(err, 'Не удалось удалить этап'),
  });

  const openEdit = (stage: RouteStage) =>
    setDraft({
      id: stage.id,
      order: stage.order,
      name: stage.name,
      quorum: stage.quorum,
      approverIds: stage.approvers.map((approver) => approver.user_id),
      condition: stage.condition ?? [],
      isFallback: stage.is_fallback,
      approverKind: stage.approver_kind,
      requiresAttachment: stage.requires_attachment,
      requiresComment: stage.requires_comment,
    });

  const knownNames = useMemo(() => {
    const names: Record<number, string> = {};
    for (const stage of route?.stages ?? []) {
      for (const approver of stage.approvers) {
        if (approver.full_name) names[approver.user_id] = approver.full_name;
      }
    }
    return names;
  }, [route]);

  const submitDraft = () => {
    if (!draft) return;
    if (!draft.name.trim()) {
      setDraftError('У этапа должно быть название — именно оно несёт смысл, '
        + 'ролей у платформы нет.');
      return;
    }
    if (draft.approverKind === 'named' && draft.approverIds.length === 0) {
      setDraftError('Нужен хотя бы один согласующий: этап без них движок не '
        + 'запустит.');
      return;
    }
    // Предикат без выбранного значения бэкенд отвергнет 409-м; поймать это
    // здесь дешевле, чем объяснять потом, какой из них пустой.
    const empty = draft.condition.some(
      (predicate) =>
        predicate.value === '' ||
        predicate.value === null ||
        (Array.isArray(predicate.value) && predicate.value.length === 0),
    );
    if (!draft.isFallback && empty) {
      setDraftError('В условии есть предикат без значения — выберите значение '
        + 'или уберите строку.');
      return;
    }
    setDraftError('');
    saveStage.mutate(draft);
  };

  const onlyStage = (route?.stages.length ?? 0) <= 1;

  return (
    <SignoffShell>
      <Link
        to="/signoff/routes"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors mb-4"
      >
        <ArrowLeft className="h-4 w-4" />
        Ко всем маршрутам
      </Link>

      {isLoading ? (
        <div className="space-y-3">
          <Skeleton className="h-10 w-72" />
          <Skeleton className="h-40 w-full" />
        </div>
      ) : isError || !route ? (
        <p className="text-sm text-destructive">Маршрут не найден.</p>
      ) : (
        <>
          <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0">
              <div className="flex items-center gap-3">
                <GitBranch className="h-6 w-6 text-muted-foreground shrink-0" />
                <h1 className="text-3xl font-bold break-words">{route.name}</h1>
              </div>
              <p className="text-sm text-muted-foreground mt-1">
                {subjectLabel}
                <span className="font-mono text-xs ml-2">{route.subject_type}</span>
              </p>
            </div>

            <div className="flex items-center gap-3">
              <Label htmlFor="route-active" className="text-sm">
                {route.is_active ? 'Активен' : 'Выключен'}
              </Label>
              <Switch
                id="route-active"
                checked={route.is_active}
                disabled={toggleActive.isPending}
                onCheckedChange={(checked) => toggleActive.mutate(checked)}
              />
            </div>
          </div>

          <div className="mb-6 flex flex-wrap items-end gap-2">
            <div className="flex-1 min-w-64 space-y-1.5">
              <Label htmlFor="route-rename">Название маршрута</Label>
              <Input
                id="route-rename"
                defaultValue={route.name}
                maxLength={200}
                onBlur={(event) => {
                  const value = event.target.value.trim();
                  if (value && value !== route.name) renameRoute.mutate(value);
                }}
              />
            </div>
            {renameRoute.isPending && (
              <Loader2 className="h-4 w-4 animate-spin mb-3 text-muted-foreground" />
            )}
          </div>

          {(route.coverage_gaps?.length ?? 0) > 0 && (
            <div className="mb-4 rounded-lg border border-amber-500/50 bg-amber-500/10 p-3">
              <div className="flex gap-2">
                <AlertTriangle className="h-4 w-4 shrink-0 text-amber-600 mt-0.5" />
                <div className="text-sm space-y-1">
                  <p className="font-medium">В ветвлении есть пробел</p>
                  {route.coverage_gaps?.map((gap) => (
                    <p key={`${gap.order}-${gap.field}`} className="text-muted-foreground">
                      Шаг {gap.order}, «{gap.label}»: нет ветки для{' '}
                      {gap.missing.map((option) => option.label).join(', ')}.
                    </p>
                  ))}
                  <p className="text-muted-foreground">
                    Объект с таким значением отправить на согласование не
                    получится — добавьте ветку или этап «иначе». Отказ увидит
                    тот, кто нажмёт «отправить», поэтому лучше закрыть пробел
                    здесь.
                  </p>
                </div>
              </div>
            </div>
          )}

          {route.initiator_stage_not_last && (
            <div className="mb-4 rounded-lg border border-amber-500/50 bg-amber-500/10 p-3">
              <div className="flex gap-2">
                <AlertTriangle className="h-4 w-4 shrink-0 text-amber-600 mt-0.5" />
                <div className="text-sm space-y-1">
                  <p className="font-medium">Подпись инициатора стоит не последней</p>
                  <p className="text-muted-foreground">
                    Согласование завершается, когда пройден последний шаг, — а
                    после этапа подписи в маршруте есть ещё шаги. Значит подпись
                    здесь превращается из финальной в промежуточное
                    подтверждение. Если задумывалась именно подпись автора,
                    перенесите этап на последний шаг.
                  </p>
                </div>
              </div>
            </div>
          )}

          <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
            <div>
              <h2 className="text-lg font-semibold">Этапы</h2>
              <p className="text-sm text-muted-foreground">
                Шаги идут сверху вниз; этапы внутри одного шага согласуются
                одновременно. Отказ на любом этапе отклоняет весь процесс
                сразу. Этап с условием попадёт в согласование только если
                условие сошлось.
              </p>
            </div>
            <Button onClick={() => setDraft(emptyDraft(nextOrder))}>
              <Plus className="mr-1.5 h-4 w-4" />
              Добавить этап
            </Button>
          </div>

          {route.stages.length === 0 ? (
            <div className="rounded-lg border border-dashed p-10 text-center">
              <p className="text-muted-foreground mb-4">
                Этапов нет — маршрут неисполним, отправить объект на
                согласование по нему нельзя.
              </p>
              <Button variant="outline" onClick={() => setDraft(emptyDraft(1))}>
                Добавить первый этап
              </Button>
            </div>
          ) : (
            <ol className="space-y-4">
              {groups.map(([order, stages], index) => (
                <li key={order}>
                  <div className="mb-2 flex items-center gap-2">
                    <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-semibold text-muted-foreground">
                      {index + 1}
                    </span>
                    <span className="text-sm text-muted-foreground">
                      шаг {order}
                    </span>
                    {stages.length > 1 && (
                      <Badge variant="outline" className="text-muted-foreground">
                        {stages.some((stage) => stage.condition.length > 0
                          || stage.is_fallback)
                          ? `ветвление · ${stages.length}`
                          : `параллельно · ${stages.length}`}
                      </Badge>
                    )}
                    <Button
                      size="sm"
                      variant="ghost"
                      className="ml-auto text-muted-foreground"
                      onClick={() => {
                        const next = emptyDraft(order);
                        setDraft(next);
                      }}
                    >
                      <Plus className="mr-1 h-3.5 w-3.5" />
                      в этот шаг
                    </Button>
                  </div>

                  <div
                    className={
                      stages.length > 1 ? 'grid gap-3 md:grid-cols-2' : 'grid gap-3'
                    }
                  >
                    {stages.map((stage) => (
                      <div key={stage.id} className="rounded-lg border p-3">
                        <div className="flex flex-wrap items-start justify-between gap-2">
                          <div className="min-w-0">
                            <p className="font-medium break-words">{stage.name}</p>
                            <p className="text-xs text-muted-foreground">
                              {stage.approver_kind === 'initiator'
                                ? APPROVER_KIND_LABELS.initiator.toLowerCase()
                                : QUORUM_LABELS[stage.quorum] ?? stage.quorum}
                            </p>
                            {stage.requires_attachment && (
                              <p className="mt-1 flex items-center gap-1.5 text-xs text-muted-foreground">
                                <Paperclip className="h-3.5 w-3.5 shrink-0" />
                                только с приложенным PDF
                              </p>
                            )}
                            {stage.requires_comment && (
                              <p className="mt-1 flex items-center gap-1.5 text-xs text-muted-foreground">
                                <MessageSquare className="h-3.5 w-3.5 shrink-0" />
                                только с пояснением
                              </p>
                            )}
                            {(stage.condition.length > 0 || stage.is_fallback) && (
                              <p className="mt-1 flex items-start gap-1.5 text-xs text-muted-foreground">
                                <Split className="h-3.5 w-3.5 shrink-0 mt-px" />
                                <span className="break-words">
                                  {stage.is_fallback
                                    ? 'иначе — когда в шаге не сошлось ни одно условие'
                                    : conditionText(stage.condition, fields)}
                                </span>
                              </p>
                            )}
                          </div>
                          <div className="flex gap-1">
                            <Button
                              size="icon"
                              variant="ghost"
                              aria-label="Изменить этап"
                              onClick={() => openEdit(stage)}
                            >
                              <Pencil className="h-4 w-4" />
                            </Button>
                            <AlertDialog>
                              <AlertDialogTrigger asChild>
                                <Button
                                  size="icon"
                                  variant="ghost"
                                  aria-label="Удалить этап"
                                  disabled={onlyStage}
                                  title={
                                    onlyStage
                                      ? 'Последний этап удалить нельзя — маршрут без этапов неисполним'
                                      : undefined
                                  }
                                >
                                  <Trash2 className="h-4 w-4" />
                                </Button>
                              </AlertDialogTrigger>
                              <AlertDialogContent>
                                <AlertDialogHeader>
                                  <AlertDialogTitle>
                                    Удалить этап «{stage.name}»?
                                  </AlertDialogTitle>
                                  <AlertDialogDescription>
                                    Уже идущие согласования это не затронет —
                                    они работают по снимку маршрута, сделанному
                                    при запуске. Изменится только то, что будет
                                    отправлено дальше.
                                  </AlertDialogDescription>
                                </AlertDialogHeader>
                                <AlertDialogFooter>
                                  <AlertDialogCancel>Оставить</AlertDialogCancel>
                                  <AlertDialogAction
                                    onClick={() => deleteStage.mutate(stage.id)}
                                  >
                                    Удалить
                                  </AlertDialogAction>
                                </AlertDialogFooter>
                              </AlertDialogContent>
                            </AlertDialog>
                          </div>
                        </div>

                        <div className="mt-2 flex flex-wrap gap-1.5">
                          {stage.approver_kind === 'initiator' ? (
                            <Badge variant="outline" className="text-muted-foreground">
                              <PenLine className="mr-1 h-3 w-3" />
                              инициатор согласования
                            </Badge>
                          ) : stage.approvers.length === 0 ? (
                            <span className="text-sm text-destructive">
                              согласующих нет — этап не исполнится
                            </span>
                          ) : (
                            stage.approvers.map((approver) => (
                              <Badge
                                key={approver.user_id}
                                variant="secondary"
                                className={approver.is_active ? '' : 'opacity-60'}
                              >
                                {approver.full_name
                                  || `Пользователь #${approver.user_id}`}
                                {!approver.is_active && ' (отключён)'}
                              </Badge>
                            ))
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </li>
              ))}
            </ol>
          )}

          <Dialog
            open={draft !== null}
            onOpenChange={(open) => {
              if (!open) {
                setDraft(null);
                setDraftError('');
              }
            }}
          >
            <DialogContent className="sm:max-w-lg">
              <DialogHeader>
                <DialogTitle>
                  {draft?.id === null ? 'Новый этап' : 'Этап маршрута'}
                </DialogTitle>
                <DialogDescription>
                  Этапы с одинаковым номером шага согласуются одновременно, с
                  разными — друг за другом.
                </DialogDescription>
              </DialogHeader>

              {draft && (
                <div className="space-y-4">
                  <div className="space-y-1.5">
                    <Label htmlFor="stage-name">Название этапа</Label>
                    <Input
                      id="stage-name"
                      value={draft.name}
                      maxLength={200}
                      placeholder="Например: финансовый контроль"
                      onChange={(event) =>
                        setDraft({ ...draft, name: event.target.value })
                      }
                    />
                    <p className="text-xs text-muted-foreground">
                      Роли в платформе нет — смысл этапа несёт его название.
                    </p>
                  </div>

                  <div className="grid gap-4 sm:grid-cols-2">
                    <div className="space-y-1.5">
                      <Label htmlFor="stage-order">Номер шага</Label>
                      <Input
                        id="stage-order"
                        type="number"
                        min={1}
                        max={999}
                        value={draft.order}
                        onChange={(event) =>
                          setDraft({
                            ...draft,
                            order: Math.max(1, Number(event.target.value) || 1),
                          })
                        }
                      />
                    </div>

                    {/* У этапа подписи согласующий ровно один, и кворум
                        «нужны все» из одного человека только путал бы. */}
                    {draft.approverKind === 'named' && (
                      <div className="space-y-1.5">
                        <Label>Кворум</Label>
                        <Select
                          value={draft.quorum}
                          onValueChange={(value) =>
                            setDraft({ ...draft, quorum: value as Quorum })
                          }
                        >
                          <SelectTrigger>
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="all">{QUORUM_LABELS.all}</SelectItem>
                            <SelectItem value="any">{QUORUM_LABELS.any}</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                    )}
                  </div>

                  <div className="space-y-1.5">
                    <Label>Кто согласует</Label>
                    <Select
                      value={draft.approverKind}
                      onValueChange={(value) =>
                        // Список согласующих сбрасываем сразу: у этапа
                        // подписи его быть не может, и держать невидимый
                        // черновик значило бы вернуть его при обратном
                        // переключении уже как неожиданность (тот же приём,
                        // что с условием у «иначе» ниже).
                        setDraft({
                          ...draft,
                          approverKind: value as ApproverKind,
                          approverIds: value === 'named' ? draft.approverIds : [],
                        })
                      }
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="named">
                          {APPROVER_KIND_LABELS.named}
                        </SelectItem>
                        <SelectItem value="initiator">
                          {APPROVER_KIND_LABELS.initiator}
                        </SelectItem>
                      </SelectContent>
                    </Select>
                    {draft.approverKind === 'initiator' && (
                      <p className="text-xs text-muted-foreground">
                        Согласует тот, кто отправил объект на согласование —
                        конкретный человек станет известен при запуске. Такой
                        этап ставят последним: он и есть подпись автора.
                      </p>
                    )}
                  </div>

                  <div className="flex items-start justify-between gap-3 rounded-lg border p-3">
                    <div className="min-w-0">
                      <Label htmlFor="stage-attachment" className="text-sm">
                        Требуется документ (PDF)
                      </Label>
                      <p className="text-xs text-muted-foreground mt-0.5">
                        Согласовать этап будет можно только приложив файл. На
                        отказ это не влияет: документа, который отказавшему
                        полагалось бы подписать, не существует.
                      </p>
                    </div>
                    <Switch
                      id="stage-attachment"
                      checked={draft.requiresAttachment}
                      onCheckedChange={(checked) =>
                        setDraft({ ...draft, requiresAttachment: checked })
                      }
                    />
                  </div>

                  <div className="flex items-start justify-between gap-3 rounded-lg border p-3">
                    <div className="min-w-0">
                      <Label htmlFor="stage-comment" className="text-sm">
                        Требуется пояснение
                      </Label>
                      <p className="text-xs text-muted-foreground mt-0.5">
                        Согласовать этап будет можно только с непустым
                        комментарием. На отказ и возврат на доработку не влияет:
                        там пояснение и так по смыслу обязательно.
                      </p>
                    </div>
                    <Switch
                      id="stage-comment"
                      checked={draft.requiresComment}
                      onCheckedChange={(checked) =>
                        setDraft({ ...draft, requiresComment: checked })
                      }
                    />
                  </div>

                  {draft.approverKind === 'named' && (
                    <div className="space-y-1.5">
                      <Label>Согласующие</Label>
                      <ApproverPicker
                        value={draft.approverIds}
                        knownNames={knownNames}
                        onChange={(ids) => setDraft({ ...draft, approverIds: ids })}
                      />
                      {draft.id !== null && (
                        <p className="text-xs text-muted-foreground">
                          Список заменяется целиком: сохранится ровно то, что
                          выбрано сейчас.
                        </p>
                      )}
                    </div>
                  )}

                  {fields.length > 0 && (
                    <div className="space-y-2 border-t pt-4">
                      <div className="flex items-center justify-between gap-3">
                        <Label>Когда нужен этот этап</Label>
                        <div className="flex items-center gap-2">
                          <Label
                            htmlFor="stage-fallback"
                            className="text-xs font-normal text-muted-foreground"
                          >
                            иначе
                          </Label>
                          <Switch
                            id="stage-fallback"
                            checked={draft.isFallback}
                            onCheckedChange={(checked) =>
                              // Условие сбрасываем сразу: «иначе» с
                              // собственным условием бэкенд не принимает, и
                              // хранить невидимый черновик условия значило бы
                              // вернуть его при обратном переключении уже
                              // как неожиданность.
                              setDraft({
                                ...draft,
                                isFallback: checked,
                                condition: checked ? [] : draft.condition,
                              })
                            }
                          />
                        </div>
                      </div>

                      {draft.isFallback ? (
                        <p className="text-xs text-muted-foreground">
                          Этап пойдёт, только если в его шаге не сошлось ни одно
                          условие. Собственного условия у «иначе» быть не может.
                        </p>
                      ) : (
                        <ConditionEditor
                          fields={fields}
                          value={draft.condition}
                          onChange={(condition) => setDraft({ ...draft, condition })}
                        />
                      )}
                    </div>
                  )}

                  {draftError && (
                    <p className="text-sm text-destructive">{draftError}</p>
                  )}
                </div>
              )}

              <DialogFooter>
                <Button variant="outline" onClick={() => setDraft(null)}>
                  Отмена
                </Button>
                <Button onClick={submitDraft} disabled={saveStage.isPending}>
                  {saveStage.isPending && (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  )}
                  Сохранить
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </>
      )}
    </SignoffShell>
  );
};

export default RouteEditor;
