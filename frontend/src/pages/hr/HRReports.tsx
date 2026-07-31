import React, { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { TasksLayout } from '@/components/tasks/TasksLayout';
import { GanttChart, type GanttGroupBy } from '@/components/tasks/GanttChart';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Checkbox } from '@/components/ui/checkbox';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import {
  AlertCircle, BarChart3, PieChart as PieIcon, TrendingUp, Users,
  GanttChartSquare, Search,
} from 'lucide-react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend, LineChart, Line, Area, AreaChart,
} from 'recharts';
import { fetchTaskStats, fetchTasks } from '@/api/tasks';
import {
  ACTIVE_STATUSES, OPEN_STATUSES, TASK_STATUS_ORDER, TERMINAL_STATUSES,
  countStatuses, statusHex, statusLabel,
} from '@/lib/tasks/status';
import { priorityHex, priorityLabel } from '@/lib/tasks/priority';
import type { TaskStats } from '@/types/tasks';

/* ---- Color palettes ---- */

const TYPE_LABEL_KEYS: Record<string, string> = {
  task: 'tasks.pages.list.type.task',
  bug: 'tasks.pages.list.type.bug',
  story: 'tasks.pages.list.type.story',
  epic: 'tasks.pages.list.type.epic',
  subtask: 'tasks.pages.list.type.subtask',
};

const CHART_COLORS = ['#3b82f6', '#22c55e', '#a855f7', '#f97316', '#ef4444', '#06b6d4', '#eab308'];

/* ---- Helpers ---- */

type Labeller = (key: string) => string;
type Colourer = (key: string) => string;

/**
 * Turn a `{key: count}` aggregate into recharts rows.
 *
 * `label` and `colour` are resolvers rather than lookup tables because the
 * previous tables were keyed on statuses this backend does not emit
 * (`open`/`closed`), so every real status fell through to its raw key and a
 * default colour. Going through `statusLabel`/`statusHex` makes that
 * impossible.
 */
function toChartData(
  record: Record<string, number>,
  label: Labeller,
  colour: Colourer,
) {
  return Object.entries(record).map(([key, value]) => ({
    name: label(key),
    value,
    key,
    fill: colour(key),
  }));
}

/* ---- Stat Card ---- */

function StatCard({ title, value, icon, color }: {
  title: string; value: string | number; icon: React.ReactNode; color: string;
}) {
  return (
    <Card>
      <CardContent className="p-4 flex items-center gap-4">
        <div className={`p-3 rounded-xl ${color}`}>
          {icon}
        </div>
        <div>
          <p className="text-sm text-muted-foreground">{title}</p>
          <p className="text-2xl font-bold">{value}</p>
        </div>
      </CardContent>
    </Card>
  );
}

/* ---- Gantt report section (Task selection + Gantt chart) ---- */

const GROUP_OPTIONS: { value: GanttGroupBy; labelKey: string }[] = [
  { value: 'assignee', labelKey: 'tasks.pages.reports.groupByAssignee' },
  { value: 'department', labelKey: 'tasks.pages.reports.groupByDepartment' },
  // Оси иерархии работ — «сколько идёт по этому пакету / на этом блоке»
  // это тот же вопрос, что «по этому исполнителю», только другой разрез.
  { value: 'site', labelKey: 'tasks.pages.reports.groupBySite' },
  { value: 'roadmap', labelKey: 'tasks.pages.reports.groupByRoadmap' },
  { value: 'block', labelKey: 'tasks.pages.reports.groupByBlock' },
  { value: 'none', labelKey: 'tasks.pages.reports.groupByNone' },
];

/** Server cap on ``limit`` (``_int_param(..., maximum=200)``). */
const GANTT_TASK_LIMIT = 200;

const GanttReportSection: React.FC = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [groupBy, setGroupBy] = useState<GanttGroupBy>('assignee');
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [selected, setSelected] = useState<Set<number>>(new Set());

  // The status filter is applied server-side so the ``limit`` below covers
  // the tasks the user actually asked for. Previously this called
  // ``fetchTasks()`` with no arguments, silently accepted the server's
  // default page of 50, and filtered that page in the browser — so the
  // chart showed "all tasks" while quietly dropping everything past the
  // 50th, with nothing in the UI to say so.
  const params: Record<string, string> = { limit: String(GANTT_TASK_LIMIT) };
  if (statusFilter !== 'all') params.status = statusFilter;

  const { data: tasks = [], isLoading, error } = useQuery({
    queryKey: ['gantt-tasks', params],
    queryFn: () => fetchTasks(params),
  });

  const truncated = tasks.length >= GANTT_TASK_LIMIT;

  /* Список для выбора с учётом текстового поиска (статус отфильтрован сервером). */
  const filtered = useMemo(
    () =>
      tasks.filter((t) => {
        if (search && !`${t.key} ${t.summary}`.toLowerCase().includes(search.toLowerCase())) return false;
        return true;
      }),
    [tasks, search],
  );

  const shownTasks = useMemo(
    () => filtered.filter((t) => selected.has(t.id)),
    [filtered, selected],
  );

  const allVisibleSelected = filtered.length > 0 && filtered.every((t) => selected.has(t.id));

  const toggle = (id: number) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const toggleAllVisible = () =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (allVisibleSelected) filtered.forEach((t) => next.delete(t.id));
      else filtered.forEach((t) => next.add(t.id));
      return next;
    });

  if (isLoading) {
    return (
      <div className="text-center py-12 text-muted-foreground">
        {t('tasks.pages.reports.loadingTasks', 'Загрузка задач...')}
      </div>
    );
  }
  if (error) {
    return (
      <div className="flex items-center gap-2 text-red-500 py-12 justify-center">
        <AlertCircle className="h-5 w-5" />
        {t('tasks.pages.reports.loadTasksError', 'Ошибка загрузки задач')}
      </div>
    );
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[300px_minmax(0,1fr)] items-start">
      {/* Панель выбора задач */}
      <Card className="lg:sticky lg:top-4">
        <CardHeader className="pb-3">
          <CardTitle className="text-sm">
            {t('tasks.pages.reports.selectTasks', 'Выбор задач')}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder={t('tasks.pages.reports.searchTasks', 'Поиск задач')}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9 h-9"
            />
          </div>

          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger className="h-9">
              <SelectValue placeholder={t('tasks.pages.list.table.status')} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t('tasks.pages.list.allStatuses')}</SelectItem>
              {TASK_STATUS_ORDER.map((s) => (
                <SelectItem key={s} value={s}>{statusLabel(s, t)}</SelectItem>
              ))}
            </SelectContent>
          </Select>

          {truncated && (
            <p className="text-[11px] leading-snug text-amber-600 dark:text-amber-500">
              {t('tasks.pages.reports.truncated',
                'Показаны первые {{count}} задач. Уточните фильтр, чтобы увидеть остальные.',
                { count: GANTT_TASK_LIMIT })}
            </p>
          )}

          <div className="flex items-center justify-between text-xs">
            <button
              type="button"
              onClick={toggleAllVisible}
              className="text-primary hover:underline"
            >
              {allVisibleSelected
                ? t('tasks.pages.reports.deselectAll', 'Снять все')
                : t('tasks.pages.reports.selectAll', 'Выбрать все')}
            </button>
            <span className="text-muted-foreground">
              {t('tasks.pages.reports.selectedCount', 'Выбрано')}: {shownTasks.length} / {filtered.length}
            </span>
          </div>

          <ScrollArea className="h-[360px] pr-3 -mr-3">
            <div className="space-y-1">
              {filtered.length === 0 ? (
                <p className="text-xs text-muted-foreground py-4 text-center">
                  {t('tasks.pages.reports.noTasks', 'Нет задач')}
                </p>
              ) : (
                filtered.map((task) => (
                  <label
                    key={task.id}
                    className="flex items-start gap-2 rounded-md px-2 py-1.5 hover:bg-muted/60 cursor-pointer"
                  >
                    <Checkbox
                      checked={selected.has(task.id)}
                      onCheckedChange={() => toggle(task.id)}
                      className="mt-0.5"
                    />
                    <span className="min-w-0">
                      <span className="font-mono text-xs text-primary mr-1">{task.key}</span>
                      <span className="text-sm">{task.summary}</span>
                    </span>
                  </label>
                ))
              )}
            </div>
          </ScrollArea>
        </CardContent>
      </Card>

      {/* Диаграмма */}
      <Card className="min-w-0">
        <CardHeader className="flex flex-row items-center justify-between gap-3 space-y-0">
          <CardTitle>{t('tasks.pages.reports.ganttTitle', 'Диаграмма Ганта')}</CardTitle>
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground hidden sm:inline">
              {t('tasks.pages.reports.groupBy', 'Группировка')}:
            </span>
            <Select value={groupBy} onValueChange={(v) => setGroupBy(v as GanttGroupBy)}>
              <SelectTrigger className="h-9 w-[180px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {GROUP_OPTIONS.map((o) => (
                  <SelectItem key={o.value} value={o.value}>{t(o.labelKey)}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </CardHeader>
        <CardContent>
          <GanttChart
            tasks={shownTasks}
            groupBy={groupBy}
            onTaskClick={(t) => navigate(`/tasks/${t.id}`)}
          />
        </CardContent>
      </Card>
    </div>
  );
};

/* ---- Main Component ---- */

const HRReports: React.FC = () => {
  const { t } = useTranslation();
  const [tab, setTab] = useState('overview');
  const title = t('tasks.pages.reports.title', 'Отчёты');
  const subtitle = t('tasks.pages.reports.subtitle', 'Аналитика по задачам');

  const { data: stats, isLoading, error } = useQuery({
    queryKey: ['hr-task-stats'],
    queryFn: () => fetchTaskStats(),
  });

  if (isLoading) {
    return (
      <TasksLayout title={title} subtitle={subtitle}>
        <div className="text-center py-12 text-muted-foreground">
          {t('tasks.pages.reports.loading', 'Загрузка данных...')}
        </div>
      </TasksLayout>
    );
  }

  if (error || !stats) {
    return (
      <TasksLayout title={title} subtitle={subtitle}>
        <div className="flex items-center gap-2 text-red-500 py-12 justify-center">
          <AlertCircle className="h-5 w-5" />
          {t('tasks.pages.reports.loadError', 'Ошибка загрузки данных')}
        </div>
      </TasksLayout>
    );
  }

  const statusData = toChartData(
    stats.by_status, (k) => statusLabel(k, t), statusHex);
  const priorityData = toChartData(
    stats.by_priority, (k) => priorityLabel(k, t), priorityHex);
  const typeData = toChartData(
    stats.by_type,
    (k) => (TYPE_LABEL_KEYS[k] ? t(TYPE_LABEL_KEYS[k], k) : k),
    () => '',   // types are coloured by position, see the Cell below
  );

  /* Merge created/resolved per day into unified array */
  const daySet = new Set<string>();
  stats.created_per_day.forEach((d) => daySet.add(d.day));
  stats.resolved_per_day.forEach((d) => daySet.add(d.day));
  const days = Array.from(daySet).sort();
  const createdMap = Object.fromEntries(stats.created_per_day.map((d) => [d.day, d.count]));
  const resolvedMap = Object.fromEntries(stats.resolved_per_day.map((d) => [d.day, d.count]));
  const createdVsResolved = days.map((day) => ({
    day: new Date(day).toLocaleDateString('ru', { day: '2-digit', month: '2-digit' }),
    created: createdMap[day] || 0,
    resolved: resolvedMap[day] || 0,
  }));

  /* Department bar data */
  const deptData = stats.by_department.map((d) => ({
    name: d.department__name,
    count: d.count,
  }));

  /* Объекты и проекты — ось «где» и ось «что». Цвет объекта приходит с
     сервера, поэтому столбцы совпадают по цвету с чипами в роадмапе и
     полосами в графике работ. */
  const siteData = (stats.by_site ?? []).map((s) => ({
    name: s.site__name,
    count: s.count,
    fill: s.site__color || '#94a3b8',
  }));
  const projectData = (stats.by_project ?? []).map((p) => ({
    name: p.project__name,
    count: p.count,
  }));

  /* Workload data */
  const workloadData = stats.by_assignee.map((a) => {
    const name = [a.assignee__first_name, a.assignee__last_name].filter(Boolean).join(' ')
      || a.assignee__username;
    return { name, count: a.count };
  });

  // Counted over the real status vocabulary. The previous version summed
  // `open + in_progress + in_review` and `done + closed`: `open` and
  // `closed` do not exist in this backend, so "In progress" silently
  // dropped every backlog/todo/blocked task and "Completed" dropped every
  // cancelled one — the two tiles never added up to the total.
  const openCount = countStatuses(stats.by_status, OPEN_STATUSES)
    + countStatuses(stats.by_status, ACTIVE_STATUSES);
  const doneCount = countStatuses(stats.by_status, TERMINAL_STATUSES);

  return (
    <TasksLayout title={title} subtitle={subtitle}>
      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard
          title={t('tasks.pages.reports.totalTasks', 'Всего задач')}
          value={stats.total}
          icon={<BarChart3 className="h-5 w-5 text-white" />}
          color="bg-blue-500"
        />
        <StatCard
          title={t('tasks.pages.reports.inWork', 'В работе')}
          value={openCount}
          icon={<TrendingUp className="h-5 w-5 text-white" />}
          color="bg-orange-500"
        />
        <StatCard
          title={t('tasks.pages.reports.completed', 'Завершено')}
          value={doneCount}
          icon={<PieIcon className="h-5 w-5 text-white" />}
          color="bg-green-500"
        />
        <StatCard
          title={t('tasks.pages.reports.assignees', 'Исполнителей')}
          value={stats.by_assignee.length}
          icon={<Users className="h-5 w-5 text-white" />}
          color="bg-purple-500"
        />
      </div>

      {/* Tabs */}
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="grid w-full grid-cols-3 md:grid-cols-6">
          <TabsTrigger value="overview">
            {t('tasks.pages.reports.tabOverview', 'Обзор')}
          </TabsTrigger>
          <TabsTrigger value="created-resolved">
            {t('tasks.pages.reports.tabCreatedResolved', 'Создано / Решено')}
          </TabsTrigger>
          <TabsTrigger value="workload">
            {t('tasks.pages.reports.tabWorkload', 'Нагрузка')}
          </TabsTrigger>
          <TabsTrigger value="departments">
            {t('tasks.pages.reports.tabDepartments', 'Отделы')}
          </TabsTrigger>
          <TabsTrigger value="sites">
            {t('tasks.pages.reports.tabSites', 'Объекты')}
          </TabsTrigger>
          <TabsTrigger value="gantt" className="gap-1.5">
            <GanttChartSquare className="h-4 w-4" />
            {t('tasks.pages.reports.tabGantt', 'Гантт')}
          </TabsTrigger>
        </TabsList>

        {/* ===== OVERVIEW TAB ===== */}
        <TabsContent value="overview" className="mt-4">
          <div className="grid md:grid-cols-3 gap-6">
            {/* By Status - Pie */}
            <Card>
              <CardHeader><CardTitle className="text-sm">
                {t('tasks.pages.reports.byStatus', 'По статусу')}
              </CardTitle></CardHeader>
              <CardContent>
                {statusData.length === 0 ? (
                  <p className="text-muted-foreground text-sm text-center py-8">
                    {t('tasks.pages.reports.noData', 'Нет данных')}
                  </p>
                ) : (
                  <ResponsiveContainer width="100%" height={250}>
                    <PieChart>
                      <Pie
                        data={statusData}
                        cx="50%" cy="50%"
                        outerRadius={80}
                        dataKey="value"
                        label={({ name, value }) => `${name}: ${value}`}
                      >
                        {statusData.map((entry) => (
                          <Cell key={entry.key} fill={entry.fill} />
                        ))}
                      </Pie>
                      <Tooltip />
                    </PieChart>
                  </ResponsiveContainer>
                )}
              </CardContent>
            </Card>

            {/* By Priority - Pie */}
            <Card>
              <CardHeader><CardTitle className="text-sm">
                {t('tasks.pages.reports.byPriority', 'По приоритету')}
              </CardTitle></CardHeader>
              <CardContent>
                {priorityData.length === 0 ? (
                  <p className="text-muted-foreground text-sm text-center py-8">
                    {t('tasks.pages.reports.noData', 'Нет данных')}
                  </p>
                ) : (
                  <ResponsiveContainer width="100%" height={250}>
                    <PieChart>
                      <Pie
                        data={priorityData}
                        cx="50%" cy="50%"
                        outerRadius={80}
                        dataKey="value"
                        label={({ name, value }) => `${name}: ${value}`}
                      >
                        {priorityData.map((entry) => (
                          <Cell key={entry.key} fill={entry.fill} />
                        ))}
                      </Pie>
                      <Tooltip />
                    </PieChart>
                  </ResponsiveContainer>
                )}
              </CardContent>
            </Card>

            {/* By Type - Bar */}
            <Card>
              <CardHeader><CardTitle className="text-sm">
                {t('tasks.pages.reports.byType', 'По типу')}
              </CardTitle></CardHeader>
              <CardContent>
                {typeData.length === 0 ? (
                  <p className="text-muted-foreground text-sm text-center py-8">
                    {t('tasks.pages.reports.noData', 'Нет данных')}
                  </p>
                ) : (
                  <ResponsiveContainer width="100%" height={250}>
                    <BarChart data={typeData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="name" fontSize={12} />
                      <YAxis allowDecimals={false} />
                      <Tooltip />
                      <Bar dataKey="value"
                        name={t('tasks.pages.reports.tasksAxis', 'Задач')}
                        radius={[4, 4, 0, 0]}>
                        {typeData.map((_, i) => (
                          <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        {/* ===== CREATED VS RESOLVED TAB ===== */}
        <TabsContent value="created-resolved" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle>
                {t('tasks.pages.reports.createdVsResolved', 'Создано vs Решено (30 дней)')}
              </CardTitle>
            </CardHeader>
            <CardContent>
              {createdVsResolved.length === 0 ? (
                <p className="text-muted-foreground text-sm text-center py-12">
                  {t('tasks.pages.reports.noDataLast30', 'Нет данных за последние 30 дней')}
                </p>
              ) : (
                <ResponsiveContainer width="100%" height={350}>
                  <AreaChart data={createdVsResolved}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="day" fontSize={11} />
                    <YAxis allowDecimals={false} />
                    <Tooltip />
                    <Legend />
                    <Area
                      type="monotone" dataKey="created"
                      name={t('tasks.pages.reports.created', 'Создано')}
                      stroke="#3b82f6" fill="#3b82f680" strokeWidth={2}
                    />
                    <Area
                      type="monotone" dataKey="resolved"
                      name={t('tasks.pages.reports.resolved', 'Решено')}
                      stroke="#22c55e" fill="#22c55e80" strokeWidth={2}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* ===== WORKLOAD TAB ===== */}
        <TabsContent value="workload" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle>
                {t('tasks.pages.reports.workloadTitle', 'Нагрузка по исполнителям')}
              </CardTitle>
            </CardHeader>
            <CardContent>
              {workloadData.length === 0 ? (
                <p className="text-muted-foreground text-sm text-center py-12">
                  {t('tasks.pages.reports.noAssignedTasks', 'Нет назначенных задач')}
                </p>
              ) : (
                <ResponsiveContainer width="100%" height={Math.max(300, workloadData.length * 40)}>
                  <BarChart data={workloadData} layout="vertical">
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis type="number" allowDecimals={false} />
                    <YAxis dataKey="name" type="category" width={140} fontSize={12} />
                    <Tooltip />
                    <Bar dataKey="count"
                      name={t('tasks.pages.reports.tasksAxis', 'Задач')}
                      fill="#6366f1" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* ===== DEPARTMENTS TAB ===== */}
        <TabsContent value="departments" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle>
                {t('tasks.pages.reports.byDepartmentTitle', 'Задачи по отделам')}
              </CardTitle>
            </CardHeader>
            <CardContent>
              {deptData.length === 0 ? (
                <p className="text-muted-foreground text-sm text-center py-12">
                  {t('tasks.pages.reports.noDepartmentTasks', 'Нет задач, привязанных к отделам')}
                </p>
              ) : (
                <ResponsiveContainer width="100%" height={350}>
                  <BarChart data={deptData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="name" fontSize={12} />
                    <YAxis allowDecimals={false} />
                    <Tooltip />
                    <Bar dataKey="count"
                      name={t('tasks.pages.reports.tasksAxis', 'Задач')}
                      radius={[4, 4, 0, 0]}>
                      {deptData.map((_, i) => (
                        <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* ===== SITES TAB ===== */}
        <TabsContent value="sites" className="mt-4">
          <div className="grid gap-6 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>
                  {t('tasks.pages.reports.bySiteTitle', 'Задачи по объектам')}
                </CardTitle>
              </CardHeader>
              <CardContent>
                {siteData.length === 0 ? (
                  <p className="text-muted-foreground text-sm text-center py-12">
                    {t('tasks.pages.reports.noData', 'Нет данных')}
                  </p>
                ) : (
                  <ResponsiveContainer width="100%" height={Math.max(300, siteData.length * 44)}>
                    <BarChart data={siteData} layout="vertical">
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis type="number" allowDecimals={false} />
                      <YAxis dataKey="name" type="category" width={140} fontSize={12} />
                      <Tooltip />
                      <Bar dataKey="count"
                        name={t('tasks.pages.reports.tasksAxis', 'Задач')}
                        radius={[0, 4, 4, 0]}>
                        {siteData.map((entry, i) => (
                          <Cell key={i} fill={entry.fill} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>
                  {t('tasks.pages.reports.byProjectTitle', 'Задачи по проектам')}
                </CardTitle>
              </CardHeader>
              <CardContent>
                {projectData.length === 0 ? (
                  <p className="text-muted-foreground text-sm text-center py-12">
                    {t('tasks.pages.reports.noData', 'Нет данных')}
                  </p>
                ) : (
                  <ResponsiveContainer width="100%" height={Math.max(300, projectData.length * 44)}>
                    <BarChart data={projectData} layout="vertical">
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis type="number" allowDecimals={false} />
                      <YAxis dataKey="name" type="category" width={140} fontSize={12} />
                      <Tooltip />
                      <Bar dataKey="count"
                        name={t('tasks.pages.reports.tasksAxis', 'Задач')}
                        radius={[0, 4, 4, 0]}>
                        {projectData.map((_, i) => (
                          <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        {/* ===== GANTT TAB ===== */}
        <TabsContent value="gantt" className="mt-4">
          <GanttReportSection />
        </TabsContent>
      </Tabs>
    </TasksLayout>
  );
};

export default HRReports;
