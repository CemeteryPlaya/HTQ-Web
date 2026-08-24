/**
 * «Ежедневные отчёты проекта» — численность персонала по блокам за день.
 *
 * Вторая ось факта рядом с «Ежедневкой». Та отвечает «сколько сделано»
 * (выработка в штуках по задаче), эта — «сколькими людьми» (численность по
 * ролям на участке). Строка есть у КАЖДОГО блока проекта, даже пустая:
 * страница отвечает в том числе на «где ещё не отчитались».
 *
 * Три числа в строке блока намеренно разного происхождения:
 *   факт     — то, что завели здесь;
 *   план     — ResourceRequirement(kind=human) роадмапов блока на эту дату;
 *   ежедневка — Σ DailyReport.headcount по задачам блока, СВЕРКА, а не
 *               источник: там headcount необязателен и почти всегда меньше.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import {
  AlertTriangle, CalendarDays, ChevronLeft, ChevronRight, ClipboardCheck,
  Edit, MapPin, Plus, Users,
} from 'lucide-react';

import { TasksLayout } from '@/components/tasks/TasksLayout';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { ProjectStaffReportDialog } from '@/components/tasks/ProjectStaffReportDialog';
import {
  fetchProjectStaffBoard, fetchProjectStaffReport, fetchStaffReportProjects,
} from '@/api/tasks';
import type { ProjectStaffBoardBlock } from '@/types/tasks';

const isoDay = (value: Date) => {
  // Локальные части, а не toISOString(): тот сдвигает в UTC и в вечерних
  // часовых поясах отдаёт вчерашний день.
  const month = String(value.getMonth() + 1).padStart(2, '0');
  const day = String(value.getDate()).padStart(2, '0');
  return `${value.getFullYear()}-${month}-${day}`;
};
const today = () => isoDay(new Date());

const shiftDay = (day: string, days: number): string => {
  const value = new Date(`${day}T00:00:00`);
  value.setDate(value.getDate() + days);
  return isoDay(value);
};

/* ────────────────────────────── Сводка сверху ────────────────────────────── */

const Stat: React.FC<{
  label: string; value: React.ReactNode; hint?: string; accent?: boolean;
}> = ({ label, value, hint, accent }) => (
  <Card className="rounded-2xl border bg-card/70 shadow-2xs">
    <CardContent className="p-4">
      <div className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
        {label}
      </div>
      <div className={`mt-1 text-2xl font-bold ${accent ? 'text-primary' : 'text-foreground'}`}>
        {value}
      </div>
      {hint && <div className="mt-0.5 text-xs text-muted-foreground">{hint}</div>}
    </CardContent>
  </Card>
);

/* ────────────────────────────── Строка блока ────────────────────────────── */

const BlockRow: React.FC<{
  row: ProjectStaffBoardBlock;
  onFill: (row: ProjectStaffBoardBlock) => void;
}> = ({ row, onFill }) => {
  const { t } = useTranslation();
  const filed = row.report_id !== null;

  return (
    <div className="rounded-2xl border bg-card/70 p-4 shadow-2xs transition-colors hover:border-primary/30">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-foreground">
              {row.site_block_name}
            </span>
            {filed ? (
              <Badge variant="secondary" className="gap-1 rounded-xl text-[10px]">
                <ClipboardCheck className="h-3 w-3 text-emerald-500" />
                {row.total_headcount} {t('tasks.projectStaff.people', 'чел.')}
              </Badge>
            ) : (
              <Badge variant="outline" className="rounded-xl text-[10px] text-muted-foreground">
                {t('tasks.projectStaff.notFiled', 'Не заполнено')}
              </Badge>
            )}
          </div>
          {row.comment && (
            <div className="mt-1 truncate text-xs text-muted-foreground">
              {row.comment}
            </div>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-4 text-xs">
          {/* План показываем, только когда он есть: null означает «сравнивать
              не с чем», и нарисованный ноль читался бы как «расхождений нет». */}
          {row.planned_headcount !== null && (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
                {t('tasks.projectStaff.plan', 'План')}
              </div>
              <div className="font-semibold text-foreground">
                {row.total_headcount} / {row.planned_headcount}
                {row.delta !== null && row.delta !== 0 && (
                  <span className={row.delta < 0 ? 'ml-1 text-amber-600' : 'ml-1 text-emerald-600'}>
                    {row.delta > 0 ? `+${row.delta}` : row.delta}
                  </span>
                )}
              </div>
            </div>
          )}
          <div>
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
              {t('tasks.projectStaff.byDaily', 'По ежедневке')}
            </div>
            <div className="font-semibold text-muted-foreground">
              {row.daily_headcount}
            </div>
          </div>
          <Button
            size="sm"
            variant={filed ? 'outline' : 'default'}
            className="h-9 rounded-xl text-xs"
            onClick={() => onFill(row)}
          >
            {filed
              ? <><Edit className="mr-1 h-3.5 w-3.5" />{t('common.edit', 'Изменить')}</>
              : <><Plus className="mr-1 h-3.5 w-3.5" />{t('tasks.projectStaff.fill', 'Заполнить')}</>}
          </Button>
        </div>
      </div>

      {row.roles.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5 border-t pt-3">
          {row.roles.map((role) => (
            <Badge
              key={`${role.work_role_id ?? 'none'}`}
              variant="outline"
              className="rounded-lg text-[10px] font-normal"
            >
              {role.work_role_name}: {role.actual}
              {role.planned !== null && (
                <span className="text-muted-foreground"> / {role.planned}</span>
              )}
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
};

/* ────────────────────────────── Главный компонент ────────────────────────────── */

const HRProjectStaffReports: React.FC = () => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [date, setDate] = useState<string>(today());
  const [projectId, setProjectId] = useState<number | null>(null);
  const [dialogBlock, setDialogBlock] = useState<ProjectStaffBoardBlock | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);

  const { data: projects = [], isLoading: projectsLoading } = useQuery({
    queryKey: ['staff-report-projects'],
    queryFn: fetchStaffReportProjects,
  });

  // Первый проект выбираем сами: пустой экран с одним селектом ничего не
  // объясняет, а у большинства ответственных проект ровно один.
  useEffect(() => {
    if (projectId === null && projects.length > 0) setProjectId(projects[0].id);
  }, [projects, projectId]);

  const { data: board, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['project-staff-board', projectId, date],
    queryFn: () => fetchProjectStaffBoard(projectId!, date),
    enabled: projectId !== null,
  });

  // Отчёт со строками нужен только когда его открывают на правку.
  const { data: editing = null } = useQuery({
    queryKey: ['project-staff-report', dialogBlock?.report_id],
    queryFn: () => fetchProjectStaffReport(dialogBlock!.report_id!),
    enabled: dialogOpen && !!dialogBlock?.report_id,
  });

  // Через useMemo, а не `?? []` инлайном: пустой литерал был бы новым
  // массивом на каждый рендер и пересчитывал бы группировку впустую.
  const blocks = useMemo(() => board?.blocks ?? [], [board]);

  // Группировка по площадке: блок сам по себе («Блок 1») ни о чём не
  // говорит, у разных объектов они называются одинаково.
  const groups = useMemo(() => {
    const map = new Map<string, ProjectStaffBoardBlock[]>();
    for (const row of blocks) {
      if (!map.has(row.site_name)) map.set(row.site_name, []);
      map.get(row.site_name)!.push(row);
    }
    return Array.from(map.entries());
  }, [blocks]);

  const filed = blocks.filter((row) => row.report_id !== null).length;

  const openDialog = (row: ProjectStaffBoardBlock) => {
    setDialogBlock(row);
    setDialogOpen(true);
  };

  return (
    <TasksLayout
      title={t('tasks.projectStaff.pageTitle', 'Ежедневные отчеты проекта')}
      subtitle={t('tasks.projectStaff.pageSubtitle',
        'Численность персонала по участкам за смену')}
    >
      {/* Проект и дата */}
      <Card className="rounded-2xl border bg-card/70 shadow-2xs">
        <CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex min-w-0 flex-1 items-center gap-2">
            <MapPin className="h-4 w-4 shrink-0 text-muted-foreground" />
            <Select
              value={projectId !== null ? String(projectId) : ''}
              onValueChange={(value) => setProjectId(Number(value))}
              disabled={projects.length === 0}
            >
              <SelectTrigger className="h-10 max-w-sm rounded-xl text-sm">
                <SelectValue placeholder={t('tasks.projectStaff.pickProject', 'Выберите проект...')} />
              </SelectTrigger>
              <SelectContent className="rounded-2xl">
                {projects.map((project) => (
                  <SelectItem key={project.id} value={String(project.id)}>
                    {project.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="flex items-center gap-1">
            <Button
              variant="outline" size="icon"
              className="h-10 w-10 rounded-xl"
              onClick={() => setDate((day) => shiftDay(day, -1))}
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <div className="relative">
              <CalendarDays className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
              <input
                type="date"
                value={date}
                onChange={(e) => setDate(e.target.value || today())}
                className="h-10 rounded-xl border bg-background pl-9 pr-3 text-sm"
              />
            </div>
            <Button
              variant="outline" size="icon"
              className="h-10 w-10 rounded-xl"
              onClick={() => setDate((day) => shiftDay(day, 1))}
            >
              <ChevronRight className="h-4 w-4" />
            </Button>
            {date !== today() && (
              <Button
                variant="ghost" size="sm"
                className="h-10 rounded-xl text-xs"
                onClick={() => setDate(today())}
              >
                {t('tasks.projectStaff.today', 'Сегодня')}
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Сводка */}
      {board && (
        <div className="grid gap-3 sm:grid-cols-3">
          <Stat
            accent
            label={t('tasks.projectStaff.totalActual', 'Людей на проекте')}
            value={board.total_actual}
            hint={t('tasks.projectStaff.filedOf', 'Заполнено участков: {{filed}} из {{total}}', {
              filed, total: blocks.length,
            })}
          />
          <Stat
            label={t('tasks.projectStaff.totalPlanned', 'По плану')}
            value={board.total_planned ?? '—'}
            hint={board.total_planned === null
              ? t('tasks.projectStaff.noPlan', 'Потребности не заведены')
              : t('tasks.projectStaff.fromRequirements', 'Из потребностей роадмапов')}
          />
          <Stat
            label={t('tasks.projectStaff.totalDaily', 'По ежедневке')}
            value={board.total_daily}
            hint={t('tasks.projectStaff.dailyHint', 'Сверка с отчётами по задачам')}
          />
        </div>
      )}

      {/* Состояния */}
      {projectsLoading && <Skeleton className="h-24 w-full rounded-2xl" />}

      {!projectsLoading && projects.length === 0 && (
        <Card className="rounded-2xl border-dashed">
          <CardContent className="p-8 text-center text-sm text-muted-foreground">
            <Users className="mx-auto mb-2 h-8 w-8 opacity-40" />
            {t('tasks.projectStaff.noProjects',
              'Вам не назначен ни один проект. Численность ведёт ответственный за проект или руководство.')}
          </CardContent>
        </Card>
      )}

      {isLoading && projectId !== null && (
        <div className="space-y-3">
          {[0, 1, 2].map((i) => <Skeleton key={i} className="h-24 w-full rounded-2xl" />)}
        </div>
      )}

      {isError && (
        <Card className="rounded-2xl border-destructive/40">
          <CardContent className="flex items-center gap-3 p-5 text-sm">
            <AlertTriangle className="h-5 w-5 text-destructive" />
            <span className="flex-1">
              {(error as Error)?.message
                || t('tasks.projectStaff.loadError', 'Не удалось загрузить данные')}
            </span>
            <Button variant="outline" size="sm" className="rounded-xl"
                    onClick={() => refetch()}>
              {t('common.retry', 'Повторить')}
            </Button>
          </CardContent>
        </Card>
      )}

      {board && blocks.length === 0 && (
        <Card className="rounded-2xl border-dashed">
          <CardContent className="p-8 text-center text-sm text-muted-foreground">
            <MapPin className="mx-auto mb-2 h-8 w-8 opacity-40" />
            <div>
              {t('tasks.projectStaff.noBlocks',
                'У проекта нет участков — численность вести не по чему.')}
            </div>
            <Link to="/tasks/sites" className="mt-2 inline-block text-primary hover:underline">
              {t('tasks.projectStaff.goToSites', 'Перейти к объектам')}
            </Link>
          </CardContent>
        </Card>
      )}

      {/* Блоки по площадкам */}
      {groups.map(([siteName, rows]) => (
        <div key={siteName} className="space-y-3">
          <div className="flex items-center gap-2 px-1 text-xs font-bold uppercase tracking-wider text-muted-foreground">
            <MapPin className="h-3.5 w-3.5" />
            {siteName}
          </div>
          {rows.map((row) => (
            <BlockRow key={row.site_block_id} row={row} onFill={openDialog} />
          ))}
        </div>
      ))}

      {projectId !== null && (
        <ProjectStaffReportDialog
          projectId={projectId}
          date={date}
          block={dialogBlock}
          report={dialogBlock?.report_id ? editing : null}
          open={dialogOpen}
          onOpenChange={setDialogOpen}
          onChanged={() => {
            queryClient.invalidateQueries({ queryKey: ['project-staff-report'] });
          }}
        />
      )}
    </TasksLayout>
  );
};

export default HRProjectStaffReports;
