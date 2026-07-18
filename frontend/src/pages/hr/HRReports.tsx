import React, { useState, useMemo, useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
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
import type { TaskStats } from '@/types/tasks';

/* ---- Color palettes ---- */

const STATUS_COLORS: Record<string, string> = {
  open: '#64748b', in_progress: '#3b82f6', in_review: '#a855f7',
  done: '#22c55e', closed: '#6b7280',
};

const STATUS_LABELS: Record<string, string> = {
  open: 'Открыта', in_progress: 'В работе', in_review: 'На ревью',
  done: 'Готова', closed: 'Закрыта',
};

const PRIORITY_COLORS: Record<string, string> = {
  critical: '#ef4444', high: '#f97316', medium: '#eab308',
  low: '#3b82f6', trivial: '#9ca3af',
};

const PRIORITY_LABELS: Record<string, string> = {
  critical: 'Критический', high: 'Высокий', medium: 'Средний',
  low: 'Низкий', trivial: 'Тривиальный',
};

const TYPE_LABELS: Record<string, string> = {
  task: 'Задача', bug: 'Баг', story: 'История', epic: 'Эпик', subtask: 'Подзадача',
};

const CHART_COLORS = ['#3b82f6', '#22c55e', '#a855f7', '#f97316', '#ef4444', '#06b6d4', '#eab308'];

/* ---- Helpers ---- */

function toChartData(record: Record<string, number>, labels: Record<string, string>) {
  return Object.entries(record).map(([key, value]) => ({
    name: labels[key] || key,
    value,
    key,
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

const GROUP_OPTIONS: { value: GanttGroupBy; label: string }[] = [
  { value: 'assignee', label: 'По исполнителю' },
  { value: 'department', label: 'По отделу' },
  { value: 'none', label: 'Без группировки' },
];

const GanttReportSection: React.FC = () => {
  const navigate = useNavigate();
  const [groupBy, setGroupBy] = useState<GanttGroupBy>('assignee');
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const seeded = useRef(false);

  const { data: tasks = [], isLoading, error } = useQuery({
    queryKey: ['gantt-tasks'],
    queryFn: () => fetchTasks(),
  });

  /* По умолчанию выбраны все задачи (один раз после загрузки). */
  useEffect(() => {
    if (!seeded.current && tasks.length) {
      seeded.current = true;
      setSelected(new Set(tasks.map((t) => t.id)));
    }
  }, [tasks]);

  /* Список для выбора с учётом фильтров. */
  const filtered = useMemo(
    () =>
      tasks.filter((t) => {
        if (statusFilter !== 'all' && t.status !== statusFilter) return false;
        if (search && !`${t.key} ${t.summary}`.toLowerCase().includes(search.toLowerCase())) return false;
        return true;
      }),
    [tasks, statusFilter, search],
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
    return <div className="text-center py-12 text-muted-foreground">Загрузка задач...</div>;
  }
  if (error) {
    return (
      <div className="flex items-center gap-2 text-red-500 py-12 justify-center">
        <AlertCircle className="h-5 w-5" /> Ошибка загрузки задач
      </div>
    );
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[300px_minmax(0,1fr)] items-start">
      {/* Панель выбора задач */}
      <Card className="lg:sticky lg:top-4">
        <CardHeader className="pb-3">
          <CardTitle className="text-sm">Выбор задач</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Поиск задач"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9 h-9"
            />
          </div>

          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger className="h-9">
              <SelectValue placeholder="Статус" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Все статусы</SelectItem>
              {Object.entries(STATUS_LABELS).map(([k, label]) => (
                <SelectItem key={k} value={k}>{label}</SelectItem>
              ))}
            </SelectContent>
          </Select>

          <div className="flex items-center justify-between text-xs">
            <button
              type="button"
              onClick={toggleAllVisible}
              className="text-primary hover:underline"
            >
              {allVisibleSelected ? 'Снять все' : 'Выбрать все'}
            </button>
            <span className="text-muted-foreground">Выбрано: {shownTasks.length} / {filtered.length}</span>
          </div>

          <ScrollArea className="h-[360px] pr-3 -mr-3">
            <div className="space-y-1">
              {filtered.length === 0 ? (
                <p className="text-xs text-muted-foreground py-4 text-center">Нет задач</p>
              ) : (
                filtered.map((t) => (
                  <label
                    key={t.id}
                    className="flex items-start gap-2 rounded-md px-2 py-1.5 hover:bg-muted/60 cursor-pointer"
                  >
                    <Checkbox
                      checked={selected.has(t.id)}
                      onCheckedChange={() => toggle(t.id)}
                      className="mt-0.5"
                    />
                    <span className="min-w-0">
                      <span className="font-mono text-xs text-primary mr-1">{t.key}</span>
                      <span className="text-sm">{t.summary}</span>
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
          <CardTitle>Диаграмма Ганта</CardTitle>
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground hidden sm:inline">Группировка:</span>
            <Select value={groupBy} onValueChange={(v) => setGroupBy(v as GanttGroupBy)}>
              <SelectTrigger className="h-9 w-[180px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {GROUP_OPTIONS.map((o) => (
                  <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
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
  const [tab, setTab] = useState('overview');

  const { data: stats, isLoading, error } = useQuery({
    queryKey: ['hr-task-stats'],
    queryFn: () => fetchTaskStats(),
  });

  if (isLoading) {
    return (
      <TasksLayout title="Отчёты" subtitle="Аналитика по задачам">
        <div className="text-center py-12 text-muted-foreground">Загрузка данных...</div>
      </TasksLayout>
    );
  }

  if (error || !stats) {
    return (
      <TasksLayout title="Отчёты" subtitle="Аналитика по задачам">
        <div className="flex items-center gap-2 text-red-500 py-12 justify-center">
          <AlertCircle className="h-5 w-5" /> Ошибка загрузки данных
        </div>
      </TasksLayout>
    );
  }

  const statusData = toChartData(stats.by_status, STATUS_LABELS);
  const priorityData = toChartData(stats.by_priority, PRIORITY_LABELS);
  const typeData = toChartData(stats.by_type, TYPE_LABELS);

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

  /* Workload data */
  const workloadData = stats.by_assignee.map((a) => {
    const name = [a.assignee__first_name, a.assignee__last_name].filter(Boolean).join(' ')
      || a.assignee__username;
    return { name, count: a.count };
  });

  const openCount = (stats.by_status.open || 0) + (stats.by_status.in_progress || 0) + (stats.by_status.in_review || 0);
  const doneCount = (stats.by_status.done || 0) + (stats.by_status.closed || 0);

  return (
    <TasksLayout title="Отчёты" subtitle="Аналитика по задачам">
      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard
          title="Всего задач"
          value={stats.total}
          icon={<BarChart3 className="h-5 w-5 text-white" />}
          color="bg-blue-500"
        />
        <StatCard
          title="В работе"
          value={openCount}
          icon={<TrendingUp className="h-5 w-5 text-white" />}
          color="bg-orange-500"
        />
        <StatCard
          title="Завершено"
          value={doneCount}
          icon={<PieIcon className="h-5 w-5 text-white" />}
          color="bg-green-500"
        />
        <StatCard
          title="Исполнителей"
          value={stats.by_assignee.length}
          icon={<Users className="h-5 w-5 text-white" />}
          color="bg-purple-500"
        />
      </div>

      {/* Tabs */}
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="grid w-full grid-cols-3 md:grid-cols-5">
          <TabsTrigger value="overview">Обзор</TabsTrigger>
          <TabsTrigger value="created-resolved">Создано / Решено</TabsTrigger>
          <TabsTrigger value="workload">Нагрузка</TabsTrigger>
          <TabsTrigger value="departments">Отделы</TabsTrigger>
          <TabsTrigger value="gantt" className="gap-1.5">
            <GanttChartSquare className="h-4 w-4" /> Гантт
          </TabsTrigger>
        </TabsList>

        {/* ===== OVERVIEW TAB ===== */}
        <TabsContent value="overview" className="mt-4">
          <div className="grid md:grid-cols-3 gap-6">
            {/* By Status - Pie */}
            <Card>
              <CardHeader><CardTitle className="text-sm">По статусу</CardTitle></CardHeader>
              <CardContent>
                {statusData.length === 0 ? (
                  <p className="text-muted-foreground text-sm text-center py-8">Нет данных</p>
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
                          <Cell key={entry.key} fill={STATUS_COLORS[entry.key] || '#8884d8'} />
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
              <CardHeader><CardTitle className="text-sm">По приоритету</CardTitle></CardHeader>
              <CardContent>
                {priorityData.length === 0 ? (
                  <p className="text-muted-foreground text-sm text-center py-8">Нет данных</p>
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
                          <Cell key={entry.key} fill={PRIORITY_COLORS[entry.key] || '#8884d8'} />
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
              <CardHeader><CardTitle className="text-sm">По типу</CardTitle></CardHeader>
              <CardContent>
                {typeData.length === 0 ? (
                  <p className="text-muted-foreground text-sm text-center py-8">Нет данных</p>
                ) : (
                  <ResponsiveContainer width="100%" height={250}>
                    <BarChart data={typeData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="name" fontSize={12} />
                      <YAxis allowDecimals={false} />
                      <Tooltip />
                      <Bar dataKey="value" name="Задач" radius={[4, 4, 0, 0]}>
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
              <CardTitle>Создано vs Решено (30 дней)</CardTitle>
            </CardHeader>
            <CardContent>
              {createdVsResolved.length === 0 ? (
                <p className="text-muted-foreground text-sm text-center py-12">
                  Нет данных за последние 30 дней
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
                      type="monotone" dataKey="created" name="Создано"
                      stroke="#3b82f6" fill="#3b82f680" strokeWidth={2}
                    />
                    <Area
                      type="monotone" dataKey="resolved" name="Решено"
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
              <CardTitle>Нагрузка по исполнителям</CardTitle>
            </CardHeader>
            <CardContent>
              {workloadData.length === 0 ? (
                <p className="text-muted-foreground text-sm text-center py-12">
                  Нет назначенных задач
                </p>
              ) : (
                <ResponsiveContainer width="100%" height={Math.max(300, workloadData.length * 40)}>
                  <BarChart data={workloadData} layout="vertical">
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis type="number" allowDecimals={false} />
                    <YAxis dataKey="name" type="category" width={140} fontSize={12} />
                    <Tooltip />
                    <Bar dataKey="count" name="Задач" fill="#6366f1" radius={[0, 4, 4, 0]} />
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
              <CardTitle>Задачи по отделам</CardTitle>
            </CardHeader>
            <CardContent>
              {deptData.length === 0 ? (
                <p className="text-muted-foreground text-sm text-center py-12">
                  Нет задач, привязанных к отделам
                </p>
              ) : (
                <ResponsiveContainer width="100%" height={350}>
                  <BarChart data={deptData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="name" fontSize={12} />
                    <YAxis allowDecimals={false} />
                    <Tooltip />
                    <Bar dataKey="count" name="Задач" radius={[4, 4, 0, 0]}>
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

        {/* ===== GANTT TAB ===== */}
        <TabsContent value="gantt" className="mt-4">
          <GanttReportSection />
        </TabsContent>
      </Tabs>
    </TasksLayout>
  );
};

export default HRReports;
