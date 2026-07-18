/**
 * HRRoadmap — projects + nested tasks.
 *
 * Replaces the old release-roadmap (ProjectVersion → Project). Each
 * project expands to show its tasks; tasks render hierarchically when
 * they have parent/child relationships (parent_id chain). Standalone
 * tasks (project_id = NULL) do NOT appear here — they live in the main
 * task board.
 */
import React, { useState, useMemo } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { TasksLayout } from '@/components/tasks/TasksLayout';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from '@/components/ui/dialog';
import {
  Collapsible, CollapsibleContent, CollapsibleTrigger,
} from '@/components/ui/collapsible';
import { toast } from 'sonner';
import {
  Plus, ChevronDown, ChevronRight, Calendar, Target,
  AlertCircle, CheckSquare, Bug, BookOpen, Layers, ListTodo,
} from 'lucide-react';
import {
  fetchProjects, createProject, fetchProjectTasks,
} from '@/api/tasks';
import { fetchDepartments } from '@/api/hr';
import api from '@/api/client';
import { usesEmployeeTaskExperience } from '@/lib/auth/roles';
import type { UserProfile } from '@/types/userProfile';
import type { Project, ProjectStatus, Task, TaskStatus } from '@/types/tasks';

/* ---- Config ---- */

const PROJECT_STATUS: Record<ProjectStatus, { labelKey: string; color: string }> = {
  active: { labelKey: 'tasks.projects.status.active', color: 'bg-blue-600 text-white' },
  completed: { labelKey: 'tasks.projects.status.completed', color: 'bg-green-500 text-white' },
  archived: { labelKey: 'tasks.projects.status.archived', color: 'bg-gray-400 text-white' },
};

const STATUS_CONFIG: Record<TaskStatus, { color: string }> = {
  backlog: { color: 'bg-slate-400 text-white' },
  todo: { color: 'bg-slate-600 text-white' },
  in_progress: { color: 'bg-blue-600 text-white' },
  in_review: { color: 'bg-purple-500 text-white' },
  blocked: { color: 'bg-red-500 text-white' },
  done: { color: 'bg-green-500 text-white' },
  cancelled: { color: 'bg-gray-600 text-white' },
};

const TYPE_ICONS: Record<string, React.ReactNode> = {
  task: <CheckSquare className="h-4 w-4 text-blue-500" />,
  bug: <Bug className="h-4 w-4 text-red-500" />,
  story: <BookOpen className="h-4 w-4 text-green-500" />,
  epic: <Layers className="h-4 w-4 text-purple-500" />,
  subtask: <ListTodo className="h-4 w-4 text-gray-500" />,
};

/* ---- Hierarchical task tree builder ---- */

interface TaskNode {
  task: Task;
  children: TaskNode[];
}

function buildTaskTree(tasks: Task[]): TaskNode[] {
  // Group tasks by parent_id so a top-level task ("direction") has its
  // subtasks nested. Tasks whose parent is outside this project list
  // are treated as roots in the project — they still display.
  const byId = new Map<number, TaskNode>();
  tasks.forEach(t => byId.set(t.id, { task: t, children: [] }));

  const roots: TaskNode[] = [];
  byId.forEach((node) => {
    const pid = node.task.parent;
    if (pid && byId.has(pid)) {
      byId.get(pid)!.children.push(node);
    } else {
      roots.push(node);
    }
  });
  return roots;
}

const TaskRow: React.FC<{ node: TaskNode; depth: number; t: (k: string, d?: string) => string }> = ({ node, depth, t }) => {
  const { task } = node;
  return (
    <>
      <Link
        to={`/tasks/${task.id}`}
        className="flex items-center gap-3 p-2 rounded-lg hover:bg-muted transition-colors"
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
      >
        {depth > 0 && (
          <span className="text-muted-foreground text-xs">↳</span>
        )}
        {TYPE_ICONS[task.task_type] ?? <CheckSquare className="h-4 w-4 text-muted-foreground" />}
        <span className="font-mono text-sm text-primary">{task.key}</span>
        <span className="text-sm flex-1 truncate">{task.summary}</span>
        <Badge className={STATUS_CONFIG[task.status]?.color} variant="secondary">
          {t(`tasks.pages.list.status.${task.status}`, task.status)}
        </Badge>
        {task.assignee_name && (
          <span className="text-xs text-muted-foreground">{task.assignee_name}</span>
        )}
      </Link>
      {node.children.map(child => (
        <TaskRow key={child.task.id} node={child} depth={depth + 1} t={t} />
      ))}
    </>
  );
};

/* ---- Project card with expandable nested tasks ---- */

function ProjectCard({ project }: { project: Project }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const { data: tasks, isLoading } = useQuery({
    queryKey: ['hr-project-tasks', project.id],
    queryFn: () => fetchProjectTasks(project.id),
    enabled: open,
  });

  const tree = useMemo(() => (tasks ? buildTaskTree(tasks) : []), [tasks]);
  const statusCfg = PROJECT_STATUS[project.status];

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <Card style={{ borderLeftWidth: 4, borderLeftColor: project.color }}>
        <CollapsibleTrigger asChild>
          <CardHeader className="cursor-pointer hover:bg-muted/30 transition-colors">
            <div className="flex items-center gap-3">
              {open
                ? <ChevronDown className="h-5 w-5 text-muted-foreground" />
                : <ChevronRight className="h-5 w-5 text-muted-foreground" />}

              <div className="flex-1">
                <div className="flex items-center gap-2 mb-1">
                  <CardTitle className="text-lg">{project.name}</CardTitle>
                  <Badge className={statusCfg.color}>
                    {t(statusCfg.labelKey, project.status)}
                  </Badge>
                </div>

                {project.description && (
                  <p className="text-sm text-muted-foreground line-clamp-1">{project.description}</p>
                )}

                <div className="flex items-center gap-4 mt-2 text-xs text-muted-foreground">
                  {project.start_date && (
                    <span className="flex items-center gap-1">
                      <Calendar className="h-3 w-3" /> {t('tasks.projects.start', 'Начало')}: {project.start_date}
                    </span>
                  )}
                  {project.end_date && (
                    <span className="flex items-center gap-1">
                      <Target className="h-3 w-3" /> {t('tasks.projects.end', 'Завершение')}: {project.end_date}
                    </span>
                  )}
                  <span>{t('tasks.projects.taskCount', 'Задач')}: {project.task_count}</span>
                </div>
              </div>

              <div className="w-32 text-right">
                <div className="text-sm font-medium mb-1">{project.progress}%</div>
                <Progress value={project.progress} className="h-2" />
              </div>
            </div>
          </CardHeader>
        </CollapsibleTrigger>

        <CollapsibleContent>
          <CardContent className="pt-0">
            {isLoading ? (
              <p className="text-muted-foreground text-sm py-4">{t('common.loading', 'Загрузка...')}</p>
            ) : !tasks || tasks.length === 0 ? (
              <p className="text-muted-foreground text-sm py-4">
                {t('tasks.projects.empty', 'В проекте нет задач')}
              </p>
            ) : (
              <div className="space-y-1">
                {tree.map(node => (
                  <TaskRow key={node.task.id} node={node} depth={0} t={t} />
                ))}
              </div>
            )}
          </CardContent>
        </CollapsibleContent>
      </Card>
    </Collapsible>
  );
}

/* ---- Main Roadmap Page ---- */

const HRRoadmap: React.FC = () => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [form, setForm] = useState({
    name: '',
    description: '',
    status: 'active' as ProjectStatus,
    color: '#3b82f6',
    start_date: '',
    end_date: '',
    department: '',
  });

  const { data: projects = [], isLoading, error } = useQuery({
    queryKey: ['hr-projects'],
    queryFn: () => fetchProjects(),
  });

  const { data: profile } = useQuery({
    queryKey: ['profile'],
    queryFn: async () => {
      const res = await api.get<UserProfile>('users/v1/profile/me');
      return res.data;
    },
  });

  const isRegularEmployee = usesEmployeeTaskExperience(profile);

  const { data: departments = [] } = useQuery({
    queryKey: ['hr-departments'],
    queryFn: fetchDepartments,
    enabled: Boolean(profile && !isRegularEmployee),
  });

  const createMutation = useMutation({
    mutationFn: (data: Partial<Project>) => createProject(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hr-projects'] });
      setCreateOpen(false);
      setForm({ name: '', description: '', status: 'active', color: '#3b82f6', start_date: '', end_date: '', department: '' });
      toast.success(t('tasks.projects.created', 'Проект создан'));
    },
    onError: () => toast.error(t('tasks.projects.createError', 'Ошибка создания проекта')),
  });

  function handleCreate() {
    if (!form.name.trim()) {
      toast.error(t('tasks.projects.nameRequired', 'Название обязательно'));
      return;
    }
    const payload: any = {
      name: form.name,
      description: form.description,
      status: form.status,
      color: form.color,
    };
    if (form.start_date) payload.start_date = form.start_date;
    if (form.end_date) payload.end_date = form.end_date;
    if (form.department) payload.department = Number(form.department);
    createMutation.mutate(payload);
  }

  return (
    <TasksLayout
      title={t('tasks.projects.pageTitle', 'Дорожная карта')}
      subtitle={t('tasks.projects.pageSubtitle', 'Проекты и направления')}
    >
      {/* Toolbar */}
      <Card>
        <CardContent className="p-4 flex flex-wrap items-center gap-3">
          <div className="flex-1 text-sm text-muted-foreground">
            {t('tasks.projects.intro', 'Группировка задач по проектам и направлениям. Раскройте проект, чтобы увидеть его задачи.')}
          </div>
          {!isRegularEmployee && (
            <Button onClick={() => setCreateOpen(true)}>
              <Plus className="h-4 w-4 mr-1" /> {t('tasks.projects.newProject', 'Новый проект')}
            </Button>
          )}
        </CardContent>
      </Card>

      {/* Projects list */}
      <Card className="mt-4">
        <CardContent className="p-4 space-y-3">
          {isLoading ? (
            <p className="text-center text-muted-foreground py-6">{t('common.loading', 'Загрузка...')}</p>
          ) : error ? (
            <div className="flex items-center gap-2 justify-center text-red-500 py-6">
              <AlertCircle className="h-5 w-5" />
              {t('tasks.projects.loadError', 'Не удалось загрузить проекты')}
            </div>
          ) : projects.length === 0 ? (
            <p className="text-center text-muted-foreground py-6">
              {t('tasks.projects.noProjects', 'Пока нет ни одного проекта')}
            </p>
          ) : (
            projects.map(p => <ProjectCard key={p.id} project={p} />)
          )}
        </CardContent>
      </Card>

      {/* Create dialog */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>{t('tasks.projects.newProject', 'Новый проект')}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label>{t('tasks.projects.name', 'Название')}</Label>
              <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </div>
            <div>
              <Label>{t('tasks.projects.description', 'Описание')}</Label>
              <Textarea
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
                rows={3}
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>{t('tasks.projects.status.title', 'Статус')}</Label>
                <Select value={form.status} onValueChange={(v) => setForm({ ...form, status: v as ProjectStatus })}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {(Object.keys(PROJECT_STATUS) as ProjectStatus[]).map(s => (
                      <SelectItem key={s} value={s}>{t(PROJECT_STATUS[s].labelKey, s)}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label>{t('tasks.projects.color', 'Цвет')}</Label>
                <Input type="color" value={form.color} onChange={(e) => setForm({ ...form, color: e.target.value })} />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>{t('tasks.projects.start', 'Начало')}</Label>
                <Input type="date" value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} />
              </div>
              <div>
                <Label>{t('tasks.projects.end', 'Завершение')}</Label>
                <Input type="date" value={form.end_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })} />
              </div>
            </div>
            {!isRegularEmployee && (
              <div>
                <Label>{t('tasks.projects.department', 'Отдел')}</Label>
                <Select value={form.department} onValueChange={(v) => setForm({ ...form, department: v })}>
                  <SelectTrigger>
                    <SelectValue placeholder={t('tasks.projects.selectDepartment', 'Все отделы')} />
                  </SelectTrigger>
                  <SelectContent>
                    {departments.map((d: any) => (
                      <SelectItem key={d.id} value={String(d.id)}>{d.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>{t('common.cancel', 'Отмена')}</Button>
            <Button onClick={handleCreate} disabled={createMutation.isPending}>
              {createMutation.isPending ? t('common.saving', 'Сохранение...') : t('common.create', 'Создать')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </TasksLayout>
  );
};

export default HRRoadmap;
