/**
 * TaskDailyReporting — ежедневная отчётность на карточке задачи.
 *
 * Отчитывается прораб, и открывает он СВОЮ задачу, а не пакет работ проекта.
 * До этого блока попасть в форму можно было только со страницы роудмапа —
 * подняться на два уровня вверх, найти свой пакет и отчитаться оттуда. Так
 * этим не пользуются.
 *
 * Здесь же живёт редактор ПЛАНОВОГО объёма, и не за компанию: отчёт обязан
 * называть вид работ, а виды берутся из плановых объёмов задачи
 * (`resolve_volume_type`). Без объёма отчёт отклоняется с 422 — значит на
 * любой задаче, созданной через интерфейс, отчитаться было нельзя вообще,
 * потому что задать объём в интерфейсе тоже было негде.
 *
 * Оба действия — отчёт и плановый объём — под одним серверным правом
 * (`require_soft_edit`), поэтому и гейтятся одним `canReportOnTask`.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import {
  ChevronDown, ChevronRight, ClipboardList, Plus, Ruler, Trash2,
} from 'lucide-react';

import { DailyReportDialog } from '@/components/tasks/DailyReportDialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Collapsible, CollapsibleContent, CollapsibleTrigger,
} from '@/components/ui/collapsible';
import { Input } from '@/components/ui/input';
import { Progress } from '@/components/ui/progress';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { fetchTaskDailyReports, fetchVolumeTypes, setTaskVolumes } from '@/api/tasks';
import { useActiveProfile } from '@/hooks/useActiveProfile';
import { hasElevatedAccess } from '@/lib/auth/roles';
import { canReportOnTask } from '@/lib/tasks/dailyReport';
import { volumeUnitLabel } from '@/lib/tasks/roadmap';
import type { Task, TaskVolume } from '@/types/tasks';

/** Сколько последних отчётов показывать в карточке. Полная лента — в диалоге. */
const RECENT_LIMIT = 3;

const errorDetail = (err: unknown): string | undefined =>
  (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail as
    string | undefined;

/* ─────────────────────── План/факт по видам работ ─────────────────────── */

const VolumeRow: React.FC<{ volume: TaskVolume }> = ({ volume }) => {
  const unit = volumeUnitLabel(volume.unit);
  // Процент считаем только когда план положительный: делить на ноль нечем, а
  // «0 %» читалось бы как «не начинали» — тот же приём, что в block_progress.
  const percent = volume.planned_quantity > 0
    ? Math.min(volume.completed_quantity / volume.planned_quantity * 100, 100)
    : null;

  return (
    <div className="space-y-1">
      <div className="flex items-center gap-2 text-sm">
        <span className="flex-1 truncate">{volume.volume_type_name}</span>
        <span className="tabular-nums font-medium">
          {volume.completed_quantity} / {volume.planned_quantity}
        </span>
        <span className="text-xs text-muted-foreground">{unit}</span>
        {percent !== null && (
          <span className="w-12 text-right text-xs tabular-nums text-muted-foreground">
            {Math.round(percent)}%
          </span>
        )}
      </div>
      <Progress value={percent ?? 0} className="h-1.5" />
    </div>
  );
};

/* ─────────────────────── Редактор планового объёма ─────────────────────── */

interface DraftRow {
  volume_type_id: string;
  planned_quantity: string;
}

const VolumeEditor: React.FC<{
  taskId: number;
  volumes: TaskVolume[];
  onSaved: () => void;
}> = ({ taskId, volumes, onSaved }) => {
  const { t } = useTranslation();
  const [rows, setRows] = useState<DraftRow[]>([]);

  // Черновик пересобирается при смене задачи или набора объёмов: иначе
  // сохранённые значения остались бы старыми на экране.
  useEffect(() => {
    setRows(volumes.map((v) => ({
      volume_type_id: String(v.volume_type_id),
      planned_quantity: String(v.planned_quantity),
    })));
  }, [taskId, volumes]);

  const { data: types = [] } = useQuery({
    queryKey: ['volume-types'],
    queryFn: () => fetchVolumeTypes({ active_only: true }),
  });

  const save = useMutation({
    mutationFn: () => setTaskVolumes(taskId, rows
      .filter((row) => row.volume_type_id && row.planned_quantity !== '')
      .map((row) => ({
        volume_type_id: Number(row.volume_type_id),
        planned_quantity: Number(row.planned_quantity),
      }))),
    onSuccess: () => {
      toast.success(t('tasks.volumes.saved', 'Плановый объём сохранён'));
      onSaved();
    },
    onError: (err) => toast.error(
      errorDetail(err) || t('tasks.volumes.saveError', 'Не удалось сохранить объём'),
    ),
  });

  // Один вид работ — одна строка: сервер отвергает дубликаты
  // (`VolumesUpdate.volume_types_are_unique`), и предлагать их в селекте
  // значило бы вести в отказ.
  const taken = new Set(rows.map((row) => row.volume_type_id));

  const update = (index: number, patch: Partial<DraftRow>) => setRows(
    (prev) => prev.map((row, i) => (i === index ? { ...row, ...patch } : row)));

  return (
    <div className="space-y-2">
      {rows.map((row, index) => (
        <div key={index} className="flex items-center gap-2">
          <Select
            value={row.volume_type_id}
            onValueChange={(value) => update(index, { volume_type_id: value })}
          >
            <SelectTrigger className="flex-1">
              <SelectValue placeholder={t('tasks.volumes.type', 'Вид работ')} />
            </SelectTrigger>
            <SelectContent>
              {types
                .filter((type) => String(type.id) === row.volume_type_id
                  || !taken.has(String(type.id)))
                .map((type) => (
                  <SelectItem key={type.id} value={String(type.id)}>
                    {type.name} ({volumeUnitLabel(type.unit)})
                  </SelectItem>
                ))}
            </SelectContent>
          </Select>
          <Input
            type="number" min="0" step="any"
            className="w-28 tabular-nums"
            placeholder={t('tasks.volumes.quantity', 'Кол-во')}
            value={row.planned_quantity}
            onChange={(event) => update(index, {
              planned_quantity: event.target.value,
            })}
          />
          <Button
            size="icon" variant="ghost"
            className="h-9 w-9 text-muted-foreground hover:text-destructive"
            title={t('common.delete', 'Удалить')}
            onClick={() => setRows((prev) => prev.filter((_, i) => i !== index))}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      ))}

      <div className="flex items-center gap-2">
        <Button
          size="sm" variant="outline"
          onClick={() => setRows((prev) => [
            ...prev, { volume_type_id: '', planned_quantity: '' },
          ])}
        >
          <Plus className="mr-1 h-4 w-4" />
          {t('tasks.volumes.add', 'Добавить вид работ')}
        </Button>
        <Button
          size="sm"
          disabled={save.isPending}
          onClick={() => save.mutate()}
        >
          {save.isPending
            ? t('common.saving', 'Сохранение...')
            : t('tasks.volumes.save', 'Сохранить объём')}
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">
        {t('tasks.volumes.hint',
          'Список задаётся целиком: убранная строка удаляет вид работ из плана.')}
      </p>
    </div>
  );
};

/* ─────────────────────────────── Карточка ─────────────────────────────── */

export const TaskDailyReporting: React.FC<{
  task: Task;
  /** Сбросить кэш задачи: план/факт по объёмам приезжает в её ответе. */
  onChanged: () => void;
}> = ({ task, onChanged }) => {
  const { t } = useTranslation();
  const { activeProfile } = useActiveProfile();
  const elevated = hasElevatedAccess(activeProfile);
  const myId = Number(activeProfile?.id);
  const mayReport = canReportOnTask(task, myId, elevated);

  const [dialogOpen, setDialogOpen] = useState(false);
  // Через useMemo, а не `task.volumes ?? []` на месте: пустой литерал создаёт
  // новую ссылку на каждый рендер, а она уходит в зависимости useEffect
  // редактора — вышел бы бесконечный цикл перерисовки. Сейчас сервер всегда
  // присылает массив, но полагаться на это здесь незачем.
  const volumes = useMemo(() => task.volumes ?? [], [task.volumes]);
  const hasVolumes = volumes.length > 0;
  const [editorOpen, setEditorOpen] = useState(false);

  const { data: reports = [] } = useQuery({
    // Тот же ключ, что у диалога — кэш общий, второго запроса не будет.
    queryKey: ['task-daily-reports', task.id],
    queryFn: () => fetchTaskDailyReports(task.id),
  });

  const recent = useMemo(
    () => [...reports]
      .sort((a, b) => b.work_date.localeCompare(a.work_date))
      .slice(0, RECENT_LIMIT),
    [reports],
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <span className="flex items-center gap-2">
            <ClipboardList className="h-4 w-4" />
            {t('tasks.dailyReports.title', 'Ежедневные отчёты')}
            {reports.length > 0 && (
              <span className="text-sm font-normal text-muted-foreground">
                ({reports.length})
              </span>
            )}
          </span>
          <Button
            size="sm"
            variant="outline"
            // Без планового объёма форма гарантированно ответит 422 — вести в
            // неё значило бы сделать ту самую сломанную кнопку.
            disabled={!hasVolumes || !mayReport}
            title={!mayReport
              ? t('tasks.dailyReports.noRight',
                'Отчитываться могут исполнители, супервайзер и админ')
              : undefined}
            onClick={() => setDialogOpen(true)}
          >
            <Plus className="mr-1 h-4 w-4" />
            {t('tasks.dailyReports.report', 'Отчитаться')}
          </Button>
        </CardTitle>
      </CardHeader>

      <CardContent className="space-y-4">
        {hasVolumes ? (
          <div className="space-y-3">
            {volumes.map((volume) => (
              <VolumeRow key={volume.id} volume={volume} />
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            {mayReport
              ? t('tasks.volumes.emptyEditable',
                'Плановый объём не задан. Задайте его ниже — тогда можно будет отчитываться в штуках, а не только процентом выполнения.')
              : t('tasks.volumes.empty',
                'Плановый объём не задан — отчитываться в штуках по этой задаче нельзя.')}
          </p>
        )}

        {recent.length > 0 && (
          <div className="space-y-1 border-t pt-3">
            {recent.map((report) => (
              <div key={report.id} className="flex items-center gap-2 text-sm">
                <span className="tabular-nums font-medium">
                  {report.work_date}
                </span>
                <span className="tabular-nums">
                  {report.quantity} {volumeUnitLabel(report.unit)}
                </span>
                <span className="flex-1 truncate text-xs text-muted-foreground">
                  {report.volume_type_name}
                  {report.author_name && ` · ${report.author_name}`}
                </span>
                {report.current_revision > 1 && (
                  <Badge variant="outline" className="text-[10px]">
                    {t('tasks.dailyReports.revision', 'Версия')}{' '}
                    {report.current_revision}
                  </Badge>
                )}
              </div>
            ))}
            {reports.length > RECENT_LIMIT && (
              <Button
                size="sm" variant="ghost" className="h-7 px-2"
                onClick={() => setDialogOpen(true)}
              >
                {t('tasks.dailyReports.all', 'Все отчёты')} ({reports.length})
              </Button>
            )}
          </div>
        )}

        {mayReport && (
          <Collapsible
            // Без объёмов раскрыт сразу: это единственное, что тут можно
            // сделать, и прятать его за лишний клик незачем.
            open={editorOpen || !hasVolumes}
            onOpenChange={setEditorOpen}
          >
            <CollapsibleTrigger asChild>
              <Button variant="ghost" size="sm" className="w-full justify-start px-2">
                {editorOpen || !hasVolumes
                  ? <ChevronDown className="mr-2 h-4 w-4" />
                  : <ChevronRight className="mr-2 h-4 w-4" />}
                <Ruler className="mr-2 h-4 w-4" />
                {t('tasks.volumes.title', 'Плановый объём работ')}
              </Button>
            </CollapsibleTrigger>
            <CollapsibleContent className="pt-2">
              <VolumeEditor
                taskId={task.id}
                volumes={volumes}
                onSaved={onChanged}
              />
            </CollapsibleContent>
          </Collapsible>
        )}
      </CardContent>

      <DailyReportDialog
        taskId={dialogOpen ? task.id : null}
        taskKey={task.key}
        supervisorId={task.supervisor}
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        onChanged={onChanged}
      />
    </Card>
  );
};

export default TaskDailyReporting;
