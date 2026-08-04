import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { TasksLayout } from '@/components/tasks/TasksLayout';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { toast } from 'sonner';
import {
  Plus, Search, Filter, AlertCircle, ArrowUpDown,
  Bug, BookOpen, Layers, CheckSquare, ListTodo, Edit, Trash2, LayoutGrid, LayoutList
} from 'lucide-react';
import {
  fetchTasks, createTask, deleteTask, updateTask,
  fetchLabels, fetchProjects, fetchSites, fetchTaskTypes, fetchContractors,
} from '@/api/tasks';
import { fetchDepartments, fetchEmployeeUsers } from '@/api/hr';
import api from '@/api/client';
import { KanbanBoard } from '@/components/tasks/KanbanBoard';
import { CreateTaskModal } from '@/components/tasks/CreateTaskModal';
import {
  TASK_STATUS_ORDER, statusBadgeClass, statusLabel,
} from '@/lib/tasks/status';
import {
  TASK_PRIORITY, TASK_PRIORITY_ORDER, priorityLabel,
} from '@/lib/tasks/priority';
import type { TaskStatus } from '@/types/tasks';
import type { UserProfile } from '@/types/userProfile';

/* ---- Constants ---- */

const TYPE_ICONS: Record<string, React.ReactNode> = {
  task: <CheckSquare className="h-4 w-4 text-blue-500" />,
  bug: <Bug className="h-4 w-4 text-red-500" />,
  story: <BookOpen className="h-4 w-4 text-green-500" />,
  epic: <Layers className="h-4 w-4 text-purple-500" />,
  subtask: <ListTodo className="h-4 w-4 text-gray-500" />,
};

/* ---- Component ---- */

const HRTasks: React.FC = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  /* filters */
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [priorityFilter, setPriorityFilter] = useState<string>('all');
  const [typeFilter, setTypeFilter] = useState<string>('all');
  const [departmentFilter, setDepartmentFilter] = useState<string>('all');
  const [supervisorFilter, setSupervisorFilter] = useState<string>('all');
  const [projectFilter, setProjectFilter] = useState<string>('all');
  const [siteFilter, setSiteFilter] = useState<string>('all');
  const [contractorFilter, setContractorFilter] = useState<string>('all');
  const [showFilters, setShowFilters] = useState(false);
  const [viewMode, setViewMode] = useState<'table' | 'board'>('board');

  /* create dialog */
  const [createOpen, setCreateOpen] = useState(false);

  /* queries */
  const params: Record<string, string> = {};
  if (search) params.search = search;
  if (statusFilter !== 'all') params.status = statusFilter;
  if (priorityFilter !== 'all') params.priority = priorityFilter;
  if (typeFilter !== 'all') params.task_type = typeFilter;
  if (departmentFilter !== 'all') params.department = departmentFilter;
  if (supervisorFilter !== 'all') params.supervisor = supervisorFilter;
  if (projectFilter === 'standalone') params.standalone = 'true';
  else if (projectFilter !== 'all') params.project = projectFilter;
  if (siteFilter === 'none') params.no_site = 'true';
  else if (siteFilter !== 'all') params.site_id = siteFilter;
  if (contractorFilter === 'own') params.own_crew = 'true';
  else if (contractorFilter !== 'all') params.contractor_id = contractorFilter;

  const { data: tasks = [], isLoading, error } = useQuery({
    queryKey: ['hr-tasks', params],
    queryFn: () => fetchTasks(params),
  });

  const { data: departments = [] } = useQuery({
    queryKey: ['hr-departments'],
    queryFn: fetchDepartments,
  });

  const { data: users = [] } = useQuery({
    queryKey: ['hr-users'],
    queryFn: fetchEmployeeUsers,
  });

  const { data: taskTypes = [] } = useQuery({
    queryKey: ['hr-task-types'],
    queryFn: fetchTaskTypes,
  });

  const { data: projects = [] } = useQuery({
    queryKey: ['hr-projects'],
    queryFn: () => fetchProjects(),
  });

  const { data: sites = [] } = useQuery({
    queryKey: ['hr-sites'],
    queryFn: fetchSites,
  });

  const { data: contractors = [] } = useQuery({
    queryKey: ['hr-contractors'],
    queryFn: fetchContractors,
  });

  const { data: labels = [] } = useQuery({
    queryKey: ['hr-labels'],
    queryFn: fetchLabels,
  });

  const updateStatusMutation = useMutation({
    mutationFn: ({ id, status }: { id: number; status: TaskStatus }) => updateTask(id, { status }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hr-tasks'] });
      toast.success(t('tasks.pages.list.statusUpdated', 'Статус обновлен'));
    },
    onError: () => toast.error(t('tasks.pages.list.statusError', 'Ошибка обновления статуса')),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteTask(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hr-tasks'] });
      toast.success(t('tasks.pages.list.createDialog.success'));
    },
    onError: () => toast.error(t('tasks.pages.list.createDialog.error')),
  });

  return (
    <TasksLayout title={t('tasks.pages.list.title', 'Задачи')} subtitle={t('tasks.pages.list.subtitle', 'Оперативный реестр задач и канбан-доска')}>
      {/* Modern Toolbar */}
      <div className="rounded-3xl border bg-card p-4 shadow-2xs space-y-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex flex-1 flex-wrap items-center gap-3">
            <div className="relative flex-1 min-w-[220px] max-w-md">
              <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder={t('tasks.pages.list.search', 'Поиск по задачам…')}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="pl-9 h-9 text-xs bg-muted/30 rounded-xl"
              />
            </div>

            <Select value={statusFilter} onValueChange={setStatusFilter}>
              <SelectTrigger className="h-9 w-[150px] text-xs rounded-xl bg-muted/30">
                <SelectValue placeholder={t('tasks.pages.list.table.status', 'Статус')} />
              </SelectTrigger>
              <SelectContent className="rounded-2xl">
                <SelectItem value="all">{t('tasks.pages.list.allStatuses', 'Все статусы')}</SelectItem>
                {TASK_STATUS_ORDER.map((k) => (
                  <SelectItem key={k} value={k}>{statusLabel(k, t)}</SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Select value={priorityFilter} onValueChange={setPriorityFilter}>
              <SelectTrigger className="h-9 w-[150px] text-xs rounded-xl bg-muted/30">
                <SelectValue placeholder={t('tasks.pages.list.table.priority', 'Приоритет')} />
              </SelectTrigger>
              <SelectContent className="rounded-2xl">
                <SelectItem value="all">{t('tasks.pages.list.allPriorities', 'Все приоритеты')}</SelectItem>
                {TASK_PRIORITY_ORDER.map((k) => (
                  <SelectItem key={k} value={k}>
                    {TASK_PRIORITY[k].icon} {priorityLabel(k, t)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Button
              variant={showFilters ? 'default' : 'outline'}
              size="sm"
              onClick={() => setShowFilters(!showFilters)}
              className="h-9 w-9 p-0 rounded-xl"
              title="Фильтры"
            >
              <Filter className="h-4 w-4" />
            </Button>

            <div className="text-xs font-semibold text-muted-foreground whitespace-nowrap hidden md:block">
              Всего: {tasks.length}
            </div>
          </div>

          <div className="flex items-center gap-2">
            <div className="flex bg-muted/40 p-1 rounded-xl border">
              <Button
                variant={viewMode === 'board' ? 'secondary' : 'ghost'}
                size="sm"
                className="h-7 gap-1 px-3 text-xs rounded-lg font-medium shadow-2xs"
                onClick={() => setViewMode('board')}
              >
                <LayoutGrid className="h-3.5 w-3.5" />
                Канбан
              </Button>
              <Button
                variant={viewMode === 'table' ? 'secondary' : 'ghost'}
                size="sm"
                className="h-7 gap-1 px-3 text-xs rounded-lg font-medium shadow-2xs"
                onClick={() => setViewMode('table')}
              >
                <LayoutList className="h-3.5 w-3.5" />
                Таблица
              </Button>
            </div>

            <Button
              onClick={() => setCreateOpen(true)}
              className="h-9 gap-2 rounded-xl bg-primary text-primary-foreground hover:bg-primary/90 font-semibold shadow-2xs"
            >
              <Plus className="h-4 w-4" />
              {t('tasks.pages.list.create', 'Создать задачу')}
            </Button>
          </div>
        </div>

        {/* Extended filters */}
        {showFilters && (
          <div className="pt-3 border-t grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
            <Select value={typeFilter} onValueChange={setTypeFilter}>
              <SelectTrigger className="h-9 text-xs rounded-xl bg-muted/30">
                <SelectValue placeholder={t('tasks.pages.list.table.type')} />
              </SelectTrigger>
              <SelectContent className="rounded-2xl">
                <SelectItem value="all">{t('tasks.pages.list.allTypes', 'Все типы')}</SelectItem>
                {taskTypes.map((tt) => (
                  <SelectItem key={tt.id} value={tt.slug}>
                    <span className="inline-flex items-center gap-2">
                      <span className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: tt.color }} />
                      {tt.name}
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Select value={projectFilter} onValueChange={setProjectFilter}>
              <SelectTrigger className="h-9 text-xs rounded-xl bg-muted/30">
                <SelectValue placeholder={t('tasks.pages.list.table.project', 'Проект')} />
              </SelectTrigger>
              <SelectContent className="rounded-2xl">
                <SelectItem value="all">{t('tasks.pages.list.allProjects', 'Все проекты')}</SelectItem>
                <SelectItem value="standalone">{t('tasks.pages.list.standaloneOnly', 'Без проекта')}</SelectItem>
                {projects.map((p) => (
                  <SelectItem key={p.id} value={String(p.id)}>
                    <span className="inline-flex items-center gap-2">
                      <span className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: p.color }} />
                      {p.name}
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Select value={siteFilter} onValueChange={setSiteFilter}>
              <SelectTrigger className="h-9 text-xs rounded-xl bg-muted/30">
                <SelectValue placeholder={t('tasks.pages.sites.title', 'Объект')} />
              </SelectTrigger>
              <SelectContent className="rounded-2xl">
                <SelectItem value="all">{t('tasks.pages.sites.allSites', 'Все объекты')}</SelectItem>
                <SelectItem value="none">{t('tasks.pages.sites.withoutSite', 'Без объекта')}</SelectItem>
                {sites.map((s) => (
                  <SelectItem key={s.id} value={String(s.id)}>
                    <span className="inline-flex items-center gap-2">
                      <span className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: s.color }} />
                      {s.name}
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Select value={contractorFilter} onValueChange={setContractorFilter}>
              <SelectTrigger className="h-9 text-xs rounded-xl bg-muted/30">
                <SelectValue placeholder={t('tasks.pages.contractors.one', 'Подрядчик')} />
              </SelectTrigger>
              <SelectContent className="rounded-2xl">
                <SelectItem value="all">{t('tasks.pages.contractors.allPerformers', 'Все исполнители')}</SelectItem>
                <SelectItem value="own">{t('tasks.pages.contractors.ownCrew', 'Своя команда')}</SelectItem>
                {contractors.map((c) => (
                  <SelectItem key={c.id} value={String(c.id)}>{c.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Select value={departmentFilter} onValueChange={setDepartmentFilter}>
              <SelectTrigger className="h-9 text-xs rounded-xl bg-muted/30">
                <SelectValue placeholder={t('tasks.pages.list.table.department', 'Отдел')} />
              </SelectTrigger>
              <SelectContent className="rounded-2xl">
                <SelectItem value="all">{t('tasks.pages.list.allDepartments', 'Все отделы')}</SelectItem>
                {departments.map((d) => (
                  <SelectItem key={d.id} value={String(d.id)}>{d.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Select value={supervisorFilter} onValueChange={setSupervisorFilter}>
              <SelectTrigger className="h-9 text-xs rounded-xl bg-muted/30">
                <SelectValue placeholder={t('tasks.pages.list.table.supervisor', 'Супервизор')} />
              </SelectTrigger>
              <SelectContent className="rounded-2xl">
                <SelectItem value="all">{t('tasks.pages.list.allSupervisors', 'Все супервизоры')}</SelectItem>
                {users.map((u: any) => (
                  <SelectItem key={u.id} value={String(u.id)}>
                    {u.full_name || u.username}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}
      </div>

      {/* Main Container */}
      <div className="bg-card rounded-3xl border shadow-2xs overflow-hidden p-4">
        {isLoading ? (
          <div className="text-center py-12 text-muted-foreground">{t('tasks.pages.list.loading', 'Загрузка задач…')}</div>
        ) : error ? (
          <div className="flex items-center gap-2 text-red-500 py-12 justify-center font-medium">
            <AlertCircle className="h-5 w-5" />
            {t('tasks.pages.list.error', 'Ошибка при загрузке задач')}
          </div>
        ) : tasks.length === 0 ? (
          <div className="text-center py-12 text-muted-foreground">
            {t('tasks.pages.list.empty', 'Задачи не найдены')}
          </div>
        ) : viewMode === 'board' ? (
          <div className="w-full min-w-0">
            <KanbanBoard
              tasks={tasks}
              onStatusChange={(taskId, newStatus) => updateStatusMutation.mutate({ id: taskId, status: newStatus })}
            />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <Table className="text-sm">
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[100px]">{t('tasks.pages.list.table.type')}</TableHead>
                  <TableHead className="w-[110px]">{t('tasks.pages.list.table.key')}</TableHead>
                  <TableHead>{t('tasks.pages.list.table.summary')}</TableHead>
                  <TableHead className="w-[120px]">{t('tasks.pages.list.table.status')}</TableHead>
                  <TableHead className="w-[120px]">{t('tasks.pages.list.table.priority')}</TableHead>
                  <TableHead className="w-[150px]">{t('tasks.pages.list.table.assignee')}</TableHead>
                  <TableHead className="w-[150px]">{t('tasks.pages.list.table.department')}</TableHead>
                  <TableHead className="w-[100px]">{t('tasks.pages.list.table.dueDate')}</TableHead>
                  <TableHead className="w-[80px] text-right"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {tasks.map((task) => (
                  <TableRow
                    key={task.id}
                    className="cursor-pointer hover:bg-muted/40"
                    onClick={() => navigate(`/tasks/${task.id}`)}
                  >
                    <TableCell className="py-2.5">
                      <div className="flex items-center gap-1.5">
                        {TYPE_ICONS[task.task_type] ?? (
                          <span
                            className="inline-block h-3 w-3 rounded-full shrink-0"
                            style={{ backgroundColor: task.task_type_color || '#6b7280' }}
                          />
                        )}
                        <span className="text-xs text-muted-foreground">
                          {task.task_type_name || t(`tasks.pages.list.type.${task.task_type}`, task.task_type)}
                        </span>
                      </div>
                    </TableCell>
                    <TableCell className="py-2.5">
                      <span className="font-mono text-xs font-semibold text-primary">
                        {task.key}
                      </span>
                    </TableCell>
                    <TableCell className="py-2.5">
                      <div>
                        <div className="font-medium text-foreground">{task.summary}</div>
                        {task.labels && task.labels.length > 0 && (
                          <div className="flex gap-1 mt-1">
                            {task.labels.map((l) => (
                              <Badge
                                key={l.id}
                                variant="outline"
                                className="text-[10px] px-1.5 py-0 rounded-md"
                                style={{ borderColor: l.color, color: l.color }}
                              >
                                {l.name}
                              </Badge>
                            ))}
                          </div>
                        )}
                      </div>
                    </TableCell>
                    <TableCell className="py-2.5">
                      <Badge className={statusBadgeClass(task.status)}>
                        {statusLabel(task.status, t)}
                      </Badge>
                    </TableCell>
                    <TableCell className="py-2.5">
                      <span className="text-xs font-medium flex items-center gap-1">
                        {TASK_PRIORITY[task.priority]?.icon}
                        {priorityLabel(task.priority, t)}
                      </span>
                    </TableCell>
                    <TableCell className="py-2.5 text-xs">
                      {task.assignees && task.assignees.length > 0 ? (
                        <div className="flex flex-col gap-0.5">
                          {task.assignees.slice(0, 2).map((a) => (
                            <span key={a.user_id} className="inline-flex items-center gap-1">
                              {a.role === 'primary' && <span className="text-amber-500 text-xs">★</span>}
                              <span className="truncate">{a.name || `#${a.user_id}`}</span>
                            </span>
                          ))}
                          {task.assignees.length > 2 && (
                            <span className="text-xs text-muted-foreground">
                              +{task.assignees.length - 2}
                            </span>
                          )}
                        </div>
                      ) : (
                        task.assignee_name || '—'
                      )}
                    </TableCell>
                    <TableCell className="py-2.5 text-xs text-muted-foreground">
                      {task.department_name || '—'}
                    </TableCell>
                    <TableCell className="py-2.5 text-xs text-muted-foreground">
                      {task.due_date || '—'}
                    </TableCell>
                    <TableCell className="py-2.5 text-right" onClick={(e) => e.stopPropagation()}>
                      <div className="flex justify-end gap-1">
                        <Button
                          size="icon"
                          variant="ghost"
                          className="h-8 w-8 text-muted-foreground hover:text-primary rounded-lg"
                          onClick={(e) => {
                            e.stopPropagation();
                            navigate(`/tasks/${task.id}`);
                          }}
                          title={t('common.edit', 'Редактировать')}
                        >
                          <Edit className="h-4 w-4" />
                        </Button>
                        <Button
                          size="icon"
                          variant="ghost"
                          className="h-8 w-8 text-muted-foreground hover:text-destructive rounded-lg"
                          onClick={(e) => {
                            e.stopPropagation();
                            if (window.confirm(t('tasks.pages.list.deleteConfirm', 'Вы уверены, что хотите удалить задачу?'))) {
                              deleteMutation.mutate(task.id);
                            }
                          }}
                          title={t('common.delete', 'Удалить')}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </div>

      {/* Create Task Dialog */}
      <CreateTaskModal open={createOpen} onOpenChange={setCreateOpen} />
    </TasksLayout>
  );
};

export default HRTasks;
