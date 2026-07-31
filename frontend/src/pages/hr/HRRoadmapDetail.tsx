/**
 * HRRoadmapDetail — карточка пакета работ: план против факта.
 *
 * Три оси с доски, каждая своей строкой: график работ, человеческие
 * ресурсы, учёт техники. Слева план, введённый руками, справа факт,
 * свёрнутый бэкендом из задач пакета.
 *
 * Ключевое различие, которое страница обязана показывать честно: «план не
 * задан» (`planned === null`) и «запланировали ноль» — разные состояния.
 * Первое рисуется прочерком, второе числом; см. `varianceTone` в
 * `lib/tasks/roadmap.ts`, где это различие и живёт.
 */
import React, { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  AlertCircle, ArrowLeft, Boxes, CalendarRange, ClipboardList, Layers,
  MapPin, Truck, Users,
} from 'lucide-react';

import { TasksLayout } from '@/components/tasks/TasksLayout';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import {
  fetchResourceRequirements, fetchRoadmap, fetchRoadmapDailyReports,
  fetchRoadmapMetrics, fetchRoadmapTasks,
} from '@/api/tasks';
import { DailyReportDialog } from '@/components/tasks/DailyReportDialog';
import { GanttChart } from '@/components/tasks/GanttChart';
import { statusBadgeClass } from '@/lib/tasks/status';
import {
  VARIANCE_CLASS, formatDelta, roadmapStatusBadgeClass, roadmapStatusLabel,
  varianceTone,
} from '@/lib/tasks/roadmap';

/** Одна строка сравнения: план | факт | расхождение. */
const ComparisonRow: React.FC<{
  icon: React.ReactNode;
  label: string;
  planned: number | null;
  actual: number | null;
  delta: number | null;
  unit: string;
  noPlanLabel: string;
}> = ({ icon, label, planned, actual, delta, unit, noPlanLabel }) => (
  <div className="flex items-center gap-3 py-3 border-b last:border-b-0">
    <span className="text-muted-foreground shrink-0">{icon}</span>
    <span className="text-sm flex-1">{label}</span>
    <span className="text-sm tabular-nums w-28 text-right">
      {planned === null
        ? <span className="text-muted-foreground">{noPlanLabel}</span>
        : <>{planned} {unit}</>}
    </span>
    <span className="text-sm tabular-nums w-28 text-right font-medium">
      {actual === null ? '—' : <>{actual} {unit}</>}
    </span>
    <span className={`text-sm tabular-nums w-20 text-right ${VARIANCE_CLASS[varianceTone(delta)]}`}>
      {formatDelta(delta)}
    </span>
  </div>
);

const HRRoadmapDetail: React.FC = () => {
  const { t } = useTranslation();
  const { id } = useParams<{ id: string }>();
  const roadmapId = Number(id);

  const { data: roadmap, isLoading, error } = useQuery({
    queryKey: ['roadmap', roadmapId],
    queryFn: () => fetchRoadmap(roadmapId),
    enabled: Number.isFinite(roadmapId),
  });
  const { data: metrics } = useQuery({
    queryKey: ['roadmap-metrics', roadmapId],
    queryFn: () => fetchRoadmapMetrics(roadmapId),
    enabled: Number.isFinite(roadmapId),
  });
  const { data: tasks = [] } = useQuery({
    queryKey: ['roadmap-tasks', roadmapId],
    queryFn: () => fetchRoadmapTasks(roadmapId),
    enabled: Number.isFinite(roadmapId),
  });
  const { data: requirements = [] } = useQuery({
    queryKey: ['roadmap-requirements', roadmapId],
    queryFn: () => fetchResourceRequirements({ roadmap_id: roadmapId }),
    enabled: Number.isFinite(roadmapId),
  });
  const { data: reports = [] } = useQuery({
    queryKey: ['roadmap-daily-reports', roadmapId],
    queryFn: () => fetchRoadmapDailyReports(roadmapId),
    enabled: Number.isFinite(roadmapId),
  });

  const [reportFor, setReportFor] = useState<{ id: number; key: string } | null>(
    null);

  /**
   * Сводка «по дням»: задачи × даты выполнения.
   *
   * Колонки — только те дни, где что-то отчитывали. Календарная сетка от
   * начала до конца пакета дала бы месяц пустых столбцов, через которые
   * пришлось бы горизонтально скроллить до первой цифры.
   */
  const { days, byTask, dayTotals, grandTotal } = useMemo(() => {
    const dayset = new Set<string>();
    const tasks = new Map<number, { taskId: number; taskKey: string;
                                    byDay: Record<string, number>;
                                    total: number }>();
    const totals: Record<string, number> = {};
    let sum = 0;

    reports.forEach((report) => {
      dayset.add(report.work_date);
      if (!tasks.has(report.task_id)) {
        tasks.set(report.task_id, {
          taskId: report.task_id, taskKey: report.task_key,
          byDay: {}, total: 0,
        });
      }
      const row = tasks.get(report.task_id)!;
      row.byDay[report.work_date] =
        (row.byDay[report.work_date] ?? 0) + report.quantity;
      row.total += report.quantity;
      totals[report.work_date] = (totals[report.work_date] ?? 0) + report.quantity;
      sum += report.quantity;
    });

    return {
      days: [...dayset].sort(),
      byTask: [...tasks.values()].sort((a, b) =>
        a.taskKey.localeCompare(b.taskKey)),
      dayTotals: totals,
      grandTotal: sum,
    };
  }, [reports]);

  const noPlan = t('tasks.pages.roadmaps.noPlan', 'План не задан');

  /** Потребности отдельно по видам — они рисуются двумя списками. */
  const [humanNeeds, equipmentNeeds] = useMemo(() => [
    requirements.filter((row) => row.kind === 'human'),
    requirements.filter((row) => row.kind === 'equipment'),
  ], [requirements]);

  if (isLoading) {
    return (
      <TasksLayout title={t('tasks.pages.roadmaps.editTitle', 'Роудмап')}>
        <p className="text-center text-muted-foreground py-10">
          {t('common.loading', 'Загрузка...')}
        </p>
      </TasksLayout>
    );
  }

  if (error || !roadmap) {
    return (
      <TasksLayout title={t('tasks.pages.roadmaps.editTitle', 'Роудмап')}>
        <div className="flex items-center gap-2 justify-center text-red-500 py-10">
          <AlertCircle className="h-5 w-5" />
          {t('tasks.pages.roadmaps.loadError', 'Не удалось загрузить роудмапы')}
        </div>
      </TasksLayout>
    );
  }

  return (
    <TasksLayout title={roadmap.name} subtitle={roadmap.description || undefined}>
      <Button asChild variant="ghost" size="sm" className="mb-3">
        <Link to="/tasks/roadmap">
          <ArrowLeft className="h-4 w-4 mr-1" />
          {t('tasks.nav.roadmap', 'Дорожная карта')}
        </Link>
      </Button>

      <Card style={{ borderLeftWidth: 4, borderLeftColor: roadmap.color }}>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-2">
            <Layers className="h-5 w-5" style={{ color: roadmap.color }} />
            <CardTitle className="text-lg">{roadmap.name}</CardTitle>
            <Badge className={roadmapStatusBadgeClass(roadmap.status)}>
              {roadmapStatusLabel(roadmap.status, t)}
            </Badge>
          </div>
          <div className="flex flex-wrap items-center gap-4 mt-2 text-xs text-muted-foreground">
            <span>{t('tasks.pages.roadmaps.project', 'Проект')}: {roadmap.project_name}</span>
            <span className="flex items-center gap-1">
              <MapPin className="h-3 w-3" style={{ color: roadmap.site_color }} />
              {roadmap.site_name}
            </span>
            <span className="flex items-center gap-1">
              <Boxes className="h-3 w-3" />
              {roadmap.site_block_name}
            </span>
            {roadmap.owner_name && (
              <span>{t('tasks.pages.roadmaps.owner', 'Владелец')}: {roadmap.owner_name}</span>
            )}
          </div>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-3">
            <Progress value={metrics?.progress ?? 0} className="h-2 flex-1" />
            <span className="text-sm font-medium tabular-nums w-16 text-right">
              {metrics?.progress === null || metrics?.progress === undefined
                ? '—'
                : `${metrics.progress}%`}
            </span>
          </div>
          <p className="text-xs text-muted-foreground mt-1">
            {t('tasks.pages.roadmaps.tasks', 'Задачи')}: {metrics?.done_count ?? 0}
            {' / '}{metrics?.task_count ?? 0}
          </p>
        </CardContent>
      </Card>

      {/* План против факта — ядро страницы */}
      <Card className="mt-4">
        <CardHeader>
          <CardTitle className="text-base">
            {t('tasks.pages.roadmaps.planVsFact', 'План и факт')}
          </CardTitle>
          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            <span className="flex-1" />
            <span className="w-28 text-right">{t('tasks.pages.roadmaps.plan', 'План')}</span>
            <span className="w-28 text-right">{t('tasks.pages.roadmaps.fact', 'Факт')}</span>
            <span className="w-20 text-right">{t('tasks.pages.roadmaps.delta', 'Расхождение')}</span>
          </div>
        </CardHeader>
        <CardContent className="pt-0">
          {metrics && (
            <>
              <ComparisonRow
                icon={<CalendarRange className="h-4 w-4" />}
                label={t('tasks.pages.roadmaps.schedule', 'График работ')}
                planned={metrics.schedule.planned_working_days}
                actual={metrics.schedule.actual_working_days}
                delta={metrics.schedule.delta_working_days}
                unit={t('tasks.pages.roadmaps.days', 'дн.')}
                noPlanLabel={noPlan}
              />
              <ComparisonRow
                icon={<Users className="h-4 w-4" />}
                label={t('tasks.pages.roadmaps.human', 'Человеческие ресурсы')}
                planned={metrics.human.planned}
                actual={metrics.human.actual}
                delta={metrics.human.delta}
                unit={t('tasks.pages.roadmaps.people', 'чел.')}
                noPlanLabel={noPlan}
              />
              <ComparisonRow
                icon={<Truck className="h-4 w-4" />}
                label={t('tasks.pages.roadmaps.equipment', 'Учёт техники')}
                planned={metrics.equipment.planned}
                actual={metrics.equipment.actual}
                delta={metrics.equipment.delta}
                unit={t('tasks.pages.roadmaps.units', 'ед.')}
                noPlanLabel={noPlan}
              />
            </>
          )}
        </CardContent>
      </Card>

      {/* Потребности: сколько и чего запланировано, сколько уже закрыто */}
      <Card className="mt-4">
        <CardHeader>
          <CardTitle className="text-base">
            {t('tasks.pages.roadmaps.requirements', 'Потребность в ресурсах')}
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-0">
          {requirements.length === 0 ? (
            <p className="text-sm text-muted-foreground py-2">{noPlan}</p>
          ) : (
            <div className="grid gap-4 md:grid-cols-2">
              {([
                [t('tasks.pages.roadmaps.kindHuman', 'Люди'), humanNeeds] as const,
                [t('tasks.pages.roadmaps.kindEquipment', 'Техника'), equipmentNeeds] as const,
              ]).map(([title, rows]) => (
                <div key={title}>
                  <p className="text-xs font-medium text-muted-foreground mb-1">{title}</p>
                  {rows.length === 0 ? (
                    <p className="text-sm text-muted-foreground">—</p>
                  ) : rows.map((row) => (
                    <div key={row.id} className="flex items-center gap-2 py-1 text-sm">
                      <span className="flex-1 truncate">
                        {row.work_role_name
                          ?? row.equipment_category_name
                          ?? t('tasks.pages.roadmaps.quantity', 'Количество')}
                      </span>
                      <span className="tabular-nums text-muted-foreground">
                        {row.filled}/{row.quantity}
                      </span>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Задачи пакета */}
      <Card className="mt-4">
        <CardHeader>
          <CardTitle className="text-base">
            {t('tasks.pages.roadmaps.tasks', 'Задачи')}
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-0">
          {tasks.length === 0 ? (
            <p className="text-sm text-muted-foreground py-2">
              {t('tasks.pages.roadmaps.noTasks', 'Задач пока нет')}
            </p>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>#</TableHead>
                    <TableHead>{t('tasks.pages.list.summary', 'Задача')}</TableHead>
                    <TableHead>{t('tasks.pages.blocks.block', 'Блок')}</TableHead>
                    <TableHead>{t('tasks.pages.list.status.title', 'Статус')}</TableHead>
                    <TableHead className="text-right">
                      {t('tasks.pages.blocks.volumes', 'Объёмы работ')}
                    </TableHead>
                    <TableHead className="w-[120px]" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {tasks.map((task) => (
                    <TableRow key={task.id}>
                      <TableCell className="font-mono text-xs">
                        <Link to={`/tasks/${task.id}`} className="text-primary">
                          {task.key}
                        </Link>
                      </TableCell>
                      <TableCell className="max-w-[24rem] truncate">{task.summary}</TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {task.site_block_name ?? '—'}
                      </TableCell>
                      <TableCell>
                        <Badge className={statusBadgeClass(task.status)} variant="secondary">
                          {t(`tasks.pages.list.status.${task.status}`, task.status)}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right text-xs tabular-nums">
                        {task.volumes?.length
                          ? task.volumes
                            .map((v) => `${v.completed_quantity}/${v.planned_quantity}`)
                            .join(', ')
                          : '—'}
                      </TableCell>
                      <TableCell className="text-right">
                        <Button
                          size="sm" variant="ghost" className="h-7"
                          onClick={() => setReportFor(task)}
                        >
                          <ClipboardList className="h-4 w-4 mr-1" />
                          {t('tasks.dailyReports.short', 'Отчёты')}
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Гант пакета. Группировка по блоку не нужна — блок у пакета один. */}
      {tasks.length > 0 && (
        <Card className="mt-4">
          <CardHeader>
            <CardTitle className="text-base">
              {t('tasks.pages.reports.ganttTitle', 'Диаграмма Ганта')}
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            <GanttChart tasks={tasks} groupBy="assignee" />
          </CardContent>
        </Card>
      )}

      {/* «По дням»: строки — задачи, колонки — даты выполнения работ.
          Именно work_date, а не дата заполнения: таблица читается как
          хроника смен. */}
      <Card className="mt-4">
        <CardHeader>
          <CardTitle className="text-base">
            {t('tasks.dailyReports.byDay', 'По дням')}
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-0">
          {days.length === 0 ? (
            <p className="text-sm text-muted-foreground py-2">
              {t('tasks.dailyReports.empty', 'Отчётов пока нет')}
            </p>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="sticky left-0 bg-background">
                      {t('tasks.pages.list.summary', 'Задача')}
                    </TableHead>
                    {days.map((day) => (
                      <TableHead key={day} className="text-right whitespace-nowrap">
                        {day.slice(5)}
                      </TableHead>
                    ))}
                    <TableHead className="text-right">
                      {t('tasks.dailyReports.total', 'Всего')}
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {byTask.map((row) => (
                    <TableRow key={row.taskId}>
                      <TableCell className="sticky left-0 bg-background font-mono text-xs">
                        {row.taskKey}
                      </TableCell>
                      {days.map((day) => (
                        <TableCell key={day} className="text-right tabular-nums text-xs">
                          {row.byDay[day] ?? ''}
                        </TableCell>
                      ))}
                      <TableCell className="text-right tabular-nums font-medium">
                        {row.total}
                      </TableCell>
                    </TableRow>
                  ))}
                  <TableRow>
                    <TableCell className="sticky left-0 bg-background font-medium">
                      {t('tasks.dailyReports.total', 'Всего')}
                    </TableCell>
                    {days.map((day) => (
                      <TableCell key={day} className="text-right tabular-nums font-medium">
                        {dayTotals[day] ?? ''}
                      </TableCell>
                    ))}
                    <TableCell className="text-right tabular-nums font-semibold">
                      {grandTotal}
                    </TableCell>
                  </TableRow>
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      <DailyReportDialog
        taskId={reportFor?.id ?? null}
        taskKey={reportFor?.key}
        open={reportFor !== null}
        onOpenChange={(next) => { if (!next) setReportFor(null); }}
      />
    </TasksLayout>
  );
};

export default HRRoadmapDetail;
