import React, { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';
import {
  AlertTriangle, Calendar, ChevronDown, ChevronRight, Edit, Gauge, MapPin,
  Plus, Search, Star, Target, Trash2,
} from 'lucide-react';

import { SiteWorkTree } from '@/components/tasks/SiteWorkTree';
import { TasksLayout } from '@/components/tasks/TasksLayout';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Collapsible, CollapsibleContent, CollapsibleTrigger,
} from '@/components/ui/collapsible';
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Progress } from '@/components/ui/progress';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import { Switch } from '@/components/ui/switch';

import {
  createProject, deleteProject, fetchProjects, fetchProjectTasks,
  fetchRoadmaps, fetchSites, setProjectSites, updateProject,
} from '@/api/tasks';
import { fetchDepartments } from '@/api/hr';
import { searchUserOptions } from '@/api/users';
import { useActiveProfile } from '@/hooks/useActiveProfile';
import { hasElevatedAccess } from '@/lib/auth/roles';
import {
  PROJECT_STATUS_ORDER, projectNeedsSites, projectStatusBadgeClass,
  projectStatusLabel,
} from '@/lib/tasks/project';
import { statusBadgeClass, statusLabel } from '@/lib/tasks/status';
import type { Project, ProjectStatus, Site, Task } from '@/types/tasks';

/** Blank form. Owner is left unset on create — the server fills it with the
 *  caller (`project_service.create_project`), which is the sane default. */
const emptyForm = {
  name: '',
  description: '',
  status: 'active' as ProjectStatus,
  color: '#3b82f6',
  start_date: '',
  end_date: '',
  department_id: '',
  owner_id: '',
  owner_name: '',
  // Календарные дни по умолчанию — стройка идёт 7/7. Флаг меняет то, как
  // читаются ВСЕ сроки проекта, поэтому он в форме, а не в настройках.
  use_production_calendar: false,
};

type FormState = typeof emptyForm;

const errorDetail = (err: unknown): string | undefined =>
  (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail as
    string | undefined;

/* ─────────────────────────── Owner picker ─────────────────────────── */

/**
 * The options endpoint is a search: it rejects queries shorter than two
 * characters and never returns more than 20 rows, so there is nothing to
 * preload and no "all users" list to render. Hence a typeahead rather than
 * a `<Select>` over a fetched array.
 */
const OwnerPicker: React.FC<{
  value: string;
  displayName: string;
  onPick: (id: string, name: string) => void;
}> = ({ value, displayName, onPick }) => {
  const { t } = useTranslation();
  const [term, setTerm] = useState('');

  const { data: options = [], isFetching } = useQuery({
    queryKey: ['user-options', term],
    queryFn: () => searchUserOptions(term),
    enabled: term.trim().length >= 2,
  });

  return (
    <div className="grid gap-2">
      <Label>{t('tasks.projects.owner', 'Владелец')}</Label>
      {value && (
        <div className="flex items-center gap-2 text-sm">
          <span className="font-medium">{displayName || `#${value}`}</span>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={() => { onPick('', ''); setTerm(''); }}
          >
            {t('common.clear', 'Очистить')}
          </Button>
        </div>
      )}
      <Input
        value={term}
        onChange={(e) => setTerm(e.target.value)}
        placeholder={t('tasks.projects.ownerSearch', 'Начните вводить имя (от 2 букв)')}
      />
      {term.trim().length >= 2 && (
        <div className="max-h-40 overflow-y-auto rounded-md border">
          {isFetching && (
            <p className="px-3 py-2 text-xs text-muted-foreground">
              {t('common.loading', 'Загрузка...')}
            </p>
          )}
          {!isFetching && options.length === 0 && (
            <p className="px-3 py-2 text-xs text-muted-foreground">
              {t('tasks.projects.ownerNotFound', 'Никого не найдено')}
            </p>
          )}
          {options.map((option) => (
            <button
              key={option.id}
              type="button"
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-muted"
              onClick={() => {
                onPick(String(option.id), option.full_name);
                setTerm('');
              }}
            >
              <span className="flex-1 truncate">{option.full_name}</span>
              {option.email && (
                <span className="truncate text-xs text-muted-foreground">{option.email}</span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
};

/* ─────────────────────────── Sites tab ─────────────────────────── */

/**
 * Выбор объектов проекта.
 *
 * `PUT /projects/{id}/sites` replaces the set wholesale — the service takes
 * a full list rather than a delta on purpose, so the form sends what the
 * user sees and never computes a difference nobody would verify.
 *
 * Живёт под деревом работ и по умолчанию свёрнут: набор объектов правят
 * один раз при заведении проекта, а смотрят во вкладку каждый день — и
 * смотрят на то, что на объектах происходит, а не на галочки.
 */
const SitePicker: React.FC<{
  project: Project;
  sites: Site[];
  canEdit: boolean;
  onSaved: () => void;
}> = ({ project, sites, canEdit, onSaved }) => {
  const { t } = useTranslation();
  const [selected, setSelected] = useState<number[]>(project.site_ids ?? []);
  const [primary, setPrimary] = useState<number | null>(
    project.sites?.find((s) => s.is_primary)?.id ?? null,
  );

  // Switching projects must reset the draft, otherwise the previous
  // project's selection leaks into the next one.
  const [ownerId, setOwnerId] = useState(project.id);
  if (ownerId !== project.id) {
    setOwnerId(project.id);
    setSelected(project.site_ids ?? []);
    setPrimary(project.sites?.find((s) => s.is_primary)?.id ?? null);
  }

  const save = useMutation({
    mutationFn: () => setProjectSites(
      project.id,
      selected,
      // A primary that is no longer selected would be rejected by the
      // server; drop it here so the user sees the list they picked.
      primary != null && selected.includes(primary) ? primary : null,
    ),
    onSuccess: () => {
      onSaved();
      toast.success(t('tasks.projects.sitesSaved', 'Объекты проекта сохранены'));
    },
    onError: (err) => toast.error(
      errorDetail(err) || t('tasks.projects.sitesError', 'Не удалось сохранить объекты'),
    ),
  });

  const toggle = (id: number) => {
    setSelected((prev) => {
      const next = prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id];
      if (!next.includes(id) && primary === id) setPrimary(null);
      return next;
    });
  };

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        {t('tasks.projects.sitesHint',
          'Задачи проекта будут предлагать только отмеченные объекты. Если объект один, он подставится в задачу сам.')}
      </p>

      <div className="divide-y rounded-lg border">
        {sites.length === 0 && (
          <p className="p-4 text-sm text-muted-foreground">
            {t('tasks.projects.noSitesInDirectory', 'Справочник объектов пуст — заведите объект на странице «Объекты».')}
          </p>
        )}
        {sites.map((site) => {
          const checked = selected.includes(site.id);
          return (
            <div key={site.id} className="flex items-center gap-3 p-3">
              <Checkbox
                id={`site-${site.id}`}
                checked={checked}
                disabled={!canEdit}
                onCheckedChange={() => toggle(site.id)}
              />
              <label
                htmlFor={`site-${site.id}`}
                className="flex flex-1 cursor-pointer items-center gap-2 text-sm"
              >
                <span
                  className="h-3 w-3 shrink-0 rounded-full"
                  style={{ backgroundColor: site.color }}
                />
                <span className="font-medium">{site.name}</span>
                {site.region && (
                  <span className="text-xs text-muted-foreground">{site.region}</span>
                )}
              </label>
              <Button
                type="button"
                size="sm"
                variant={primary === site.id ? 'default' : 'ghost'}
                disabled={!canEdit || !checked}
                onClick={() => setPrimary(primary === site.id ? null : site.id)}
                title={t('tasks.projects.primarySite', 'Основной объект')}
                aria-label={t('tasks.projects.primarySite', 'Основной объект')}
              >
                <Star className={`h-4 w-4 ${primary === site.id ? 'fill-current' : ''}`} />
              </Button>
            </div>
          );
        })}
      </div>

      {canEdit && (
        <Button onClick={() => save.mutate()} disabled={save.isPending}>
          {save.isPending
            ? t('common.saving', 'Сохранение...')
            : t('tasks.projects.saveSites', 'Сохранить объекты')}
        </Button>
      )}
    </div>
  );
};

/**
 * Вкладка «Объекты»: что на объектах проекта идёт прямо сейчас.
 *
 * Раньше здесь был только список галочек. Он отвечал на «какие объекты
 * закреплены», но не на «что там происходит», а спрашивают именно второе —
 * поэтому сверху то же дерево, что на странице роудмапа
 * (объект → блок → пакет работ → задачи), а выбор объектов уехал под него.
 */
const SitesTab: React.FC<{
  project: Project;
  sites: Site[];
  canEdit: boolean;
  onSaved: () => void;
}> = ({ project, sites, canEdit, onSaved }) => {
  const { t } = useTranslation();
  const [pickerOpen, setPickerOpen] = useState(false);

  const { data: tasks = [], isLoading } = useQuery({
    queryKey: ['hr-project-tasks', project.id],
    queryFn: () => fetchProjectTasks(project.id),
  });
  const { data: roadmaps = [], isLoading: roadmapsLoading } = useQuery({
    queryKey: ['hr-project-roadmaps', project.id],
    queryFn: () => fetchRoadmaps({ project_id: project.id }),
  });

  const hasSites = (project.sites?.length ?? 0) > 0;

  return (
    <div className="space-y-5">
      {isLoading || roadmapsLoading ? (
        <p className="py-4 text-sm text-muted-foreground">
          {t('common.loading', 'Загрузка...')}
        </p>
      ) : !hasSites && tasks.length === 0 ? (
        <p className="py-4 text-sm text-muted-foreground">
          {t('tasks.projects.noSitesYet',
            'Объекты проекта не заданы. Отметьте их ниже — работы по каждому появятся здесь.')}
        </p>
      ) : (
        <SiteWorkTree
          project={project}
          tasks={tasks}
          roadmaps={roadmaps}
          t={t}
        />
      )}

      <Collapsible open={pickerOpen} onOpenChange={setPickerOpen}>
        <CollapsibleTrigger asChild>
          <Button variant="outline" size="sm" className="w-full justify-start">
            {pickerOpen
              ? <ChevronDown className="mr-2 h-4 w-4" />
              : <ChevronRight className="mr-2 h-4 w-4" />}
            <MapPin className="mr-2 h-4 w-4" />
            {t('tasks.projects.configureSites', 'Объекты проекта')}
            <span className="ml-2 text-xs text-muted-foreground">
              {project.sites?.length ?? 0}
            </span>
          </Button>
        </CollapsibleTrigger>
        <CollapsibleContent className="pt-3">
          <SitePicker
            project={project}
            sites={sites}
            canEdit={canEdit}
            onSaved={onSaved}
          />
        </CollapsibleContent>
      </Collapsible>
    </div>
  );
};

/* ─────────────────────────── Tasks tab ─────────────────────────── */

/**
 * Плоский список всех задач проекта — сознательно без группировки.
 *
 * Иерархия целиком живёт во вкладке «Объекты»; здесь нужен ровно
 * противоположный взгляд: одним списком, чтобы найти задачу по названию и
 * увидеть, сколько их всего и в каком они состоянии.
 */
const TasksTab: React.FC<{ projectId: number }> = ({ projectId }) => {
  const { t } = useTranslation();
  const { data: tasks = [], isLoading } = useQuery({
    queryKey: ['hr-project-tasks', projectId],
    queryFn: () => fetchProjectTasks(projectId),
  });

  if (isLoading) {
    return <p className="py-6 text-sm text-muted-foreground">{t('common.loading', 'Загрузка...')}</p>;
  }
  if (tasks.length === 0) {
    return (
      <p className="py-6 text-sm text-muted-foreground">
        {t('tasks.projects.noTasks', 'В проекте пока нет задач')}
      </p>
    );
  }

  return (
    <div className="divide-y rounded-lg border">
      {tasks.map((task: Task) => (
        <Link
          key={task.id}
          to={`/tasks/${task.id}`}
          className="flex items-center gap-3 p-2 transition-colors first:rounded-t-lg last:rounded-b-lg hover:bg-muted"
        >
          <span className="font-mono text-sm text-primary">{task.key}</span>
          <span className="flex-1 truncate text-sm">{task.summary}</span>
          {task.assignee_name && (
            <span className="hidden text-xs text-muted-foreground sm:inline">
              {task.assignee_name}
            </span>
          )}
          {task.site_name && (
            <Badge variant="outline" className="text-[10px]">{task.site_name}</Badge>
          )}
          <Badge className={statusBadgeClass(task.status)} variant="secondary">
            {statusLabel(task.status, t)}
          </Badge>
        </Link>
      ))}
    </div>
  );
};

/* ─────────────────────────── Page ─────────────────────────── */

const HRProjects: React.FC = () => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { activeProfile } = useActiveProfile();
  const elevated = hasElevatedAccess(activeProfile);
  const myId = Number(activeProfile?.id);

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [siteFilter, setSiteFilter] = useState('all');
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<Project | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [confirmDelete, setConfirmDelete] = useState<Project | null>(null);

  const { data: projects = [], isLoading, error } = useQuery({
    queryKey: ['hr-projects'],
    queryFn: () => fetchProjects(),
  });
  const { data: sites = [] } = useQuery({ queryKey: ['sites'], queryFn: () => fetchSites() });
  const { data: departments = [] } = useQuery({
    queryKey: ['hr-departments'], queryFn: fetchDepartments,
  });

  /**
   * `hr-projects` is the key every consumer of the project list uses —
   * CreateTaskModal, HRTasks, HRTaskDetail, HRResourceSchedule,
   * HRContractors and HRRoadmap all read it. Skipping this invalidation is
   * what would make freshly assigned objects invisible in the task form
   * until a page reload, i.e. exactly the link this page is here to fix.
   */
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['hr-projects'] });
    queryClient.invalidateQueries({ queryKey: ['hr-tasks'] });
    queryClient.invalidateQueries({ queryKey: ['hr-task-stats'] });
    queryClient.invalidateQueries({ queryKey: ['resource-gantt'] });
  };

  const saveMutation = useMutation({
    mutationFn: (payload: FormState) => {
      const body: Partial<Project> = {
        name: payload.name.trim(),
        description: payload.description,
        status: payload.status,
        color: payload.color,
        start_date: payload.start_date || null,
        end_date: payload.end_date || null,
        department_id: payload.department_id ? Number(payload.department_id) : null,
        use_production_calendar: payload.use_production_calendar,
      };
      if (payload.owner_id) body.owner_id = Number(payload.owner_id);
      return editing ? updateProject(editing.id, body) : createProject(body);
    },
    onSuccess: (saved) => {
      invalidate();
      setDialogOpen(false);
      setSelectedId(saved.id);
      toast.success(editing
        ? t('tasks.projects.updated', 'Проект обновлён')
        : t('tasks.projects.created', 'Проект создан'));
    },
    onError: (err) => toast.error(
      errorDetail(err) || t('tasks.projects.saveError', 'Не удалось сохранить проект'),
    ),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteProject(id),
    onSuccess: (_data, id) => {
      invalidate();
      setConfirmDelete(null);
      if (selectedId === id) setSelectedId(null);
      toast.success(t('tasks.projects.deleted', 'Проект удалён'));
    },
    onError: (err) => toast.error(
      errorDetail(err) || t('tasks.projects.deleteError', 'Не удалось удалить проект'),
    ),
  });

  const filtered = useMemo(() => projects.filter((project) => {
    if (search && !project.name.toLowerCase().includes(search.toLowerCase())) return false;
    if (statusFilter !== 'all' && project.status !== statusFilter) return false;
    if (siteFilter !== 'all' && !(project.site_ids ?? []).includes(Number(siteFilter))) {
      return false;
    }
    return true;
  }), [projects, search, statusFilter, siteFilter]);

  const selected = projects.find((p) => p.id === selectedId) ?? null;
  // Mirrors `_project_for_write` on the server: inside their own scope a
  // regular employee may still only touch a project they own.
  const canWrite = (project: Project) => elevated || project.owner_id === myId;

  const openCreate = () => { setEditing(null); setForm(emptyForm); setDialogOpen(true); };
  const openEdit = (project: Project) => {
    setEditing(project);
    setForm({
      name: project.name,
      description: project.description ?? '',
      status: project.status,
      use_production_calendar: project.use_production_calendar,
      color: project.color,
      start_date: project.start_date ?? '',
      end_date: project.end_date ?? '',
      department_id: project.department_id ? String(project.department_id) : '',
      owner_id: project.owner_id ? String(project.owner_id) : '',
      owner_name: project.owner_name ?? '',
    });
    setDialogOpen(true);
  };

  return (
    // Own keys, not `pageTitle`/`pageSubtitle`: those already belong to the
    // roadmap ("Дорожная карта" / "Проекты и направления").
    <TasksLayout
      title={t('tasks.projects.manageTitle', 'Проекты')}
      subtitle={t('tasks.projects.manageSubtitle', 'Проекты, их объекты и задачи')}
    >
      <div className="flex flex-col gap-6 lg:flex-row">
        {/* ── Список ───────────────────────────────────────────── */}
        <div className="flex w-full flex-col gap-3 lg:w-96 lg:shrink-0">
          <div className="flex items-center gap-2">
            <div className="relative flex-1">
              <Search className="absolute left-2 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                className="pl-8"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={t('common.search', 'Поиск')}
              />
            </div>
            {elevated && (
              <Button onClick={openCreate} size="sm">
                <Plus className="mr-1 h-4 w-4" />
                {t('tasks.projects.newProject', 'Новый проект')}
              </Button>
            )}
          </div>

          <div className="flex gap-2">
            <Select value={statusFilter} onValueChange={setStatusFilter}>
              <SelectTrigger className="flex-1">
                <SelectValue placeholder={t('tasks.projects.status.title', 'Статус')} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t('common.all', 'Все')}</SelectItem>
                {PROJECT_STATUS_ORDER.map((status) => (
                  <SelectItem key={status} value={status}>
                    {projectStatusLabel(status, t)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={siteFilter} onValueChange={setSiteFilter}>
              <SelectTrigger className="flex-1">
                <SelectValue placeholder={t('tasks.pages.sites.siteField', 'Объект')} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t('common.all', 'Все')}</SelectItem>
                {sites.map((site) => (
                  <SelectItem key={site.id} value={String(site.id)}>{site.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {isLoading && (
            <p className="py-8 text-center text-sm text-muted-foreground">
              {t('common.loading', 'Загрузка...')}
            </p>
          )}
          {error != null && (
            <p className="py-8 text-center text-sm text-destructive">
              {t('tasks.projects.loadError', 'Не удалось загрузить проекты')}
            </p>
          )}
          {!isLoading && filtered.length === 0 && (
            <p className="py-8 text-center text-sm text-muted-foreground">
              {t('tasks.projects.noProjects', 'Пока нет ни одного проекта')}
            </p>
          )}

          <div className="flex flex-col gap-2">
            {filtered.map((project) => (
              <button
                key={project.id}
                type="button"
                onClick={() => setSelectedId(project.id)}
                className={`rounded-xl border p-3 text-left transition-colors hover:border-primary/60 ${
                  project.id === selectedId ? 'border-primary bg-primary/5' : 'bg-card'
                }`}
                style={{ borderLeftWidth: 4, borderLeftColor: project.color }}
              >
                <div className="flex items-start justify-between gap-2">
                  <span className="text-sm font-semibold">{project.name}</span>
                  <Badge className={projectStatusBadgeClass(project.status)}>
                    {projectStatusLabel(project.status, t)}
                  </Badge>
                </div>

                <div className="mt-2 flex items-center gap-2">
                  <Progress value={project.progress} className="h-1.5 flex-1" />
                  <span className="text-xs text-muted-foreground">{project.progress}%</span>
                </div>

                <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                  <span>{t('tasks.projects.taskCount', 'Задач')}: {project.task_count}</span>
                  {project.department_name && <span>{project.department_name}</span>}
                </div>

                {projectNeedsSites(project) ? (
                  <p className="mt-2 flex items-center gap-1 text-xs text-amber-600 dark:text-amber-500">
                    <AlertTriangle className="h-3 w-3 shrink-0" />
                    {t('tasks.projects.noSites', 'Объекты не заданы')}
                  </p>
                ) : (
                  <div className="mt-2 flex flex-wrap items-center gap-1">
                    <MapPin className="h-3 w-3 text-muted-foreground" />
                    {project.sites.map((site) => (
                      <Badge
                        key={site.id}
                        variant="outline"
                        className="px-1.5 py-0 text-[10px] font-normal"
                        style={{ borderColor: site.color, color: site.color }}
                      >
                        {site.is_primary && '★ '}{site.name}
                      </Badge>
                    ))}
                  </div>
                )}
              </button>
            ))}
          </div>
        </div>

        {/* ── Деталь ───────────────────────────────────────────── */}
        <div className="min-w-0 flex-1">
          {!selected ? (
            <div className="flex h-64 items-center justify-center text-sm text-muted-foreground">
              {t('tasks.projects.selectHint', 'Выберите проект из списка слева')}
            </div>
          ) : (
            <Card>
              <CardContent className="pt-6">
                <div className="mb-4 flex items-start justify-between gap-3">
                  <div>
                    <h2 className="text-lg font-semibold">{selected.name}</h2>
                    {selected.description && (
                      <p className="mt-1 text-sm text-muted-foreground">{selected.description}</p>
                    )}
                  </div>
                  <div className="flex shrink-0 gap-2">
                    {/* План/факт доступен всем, кто видит проект: это
                        отчётный экран, а не управление. */}
                    <Button asChild size="sm" variant="outline">
                      <Link to={`/tasks/projects/${selected.id}/plan-fact`}>
                        <Gauge className="mr-1 h-4 w-4" />
                        {t('tasks.planFact.title', 'План и факт')}
                      </Link>
                    </Button>
                  </div>
                  {canWrite(selected) && (
                    <div className="flex shrink-0 gap-2">
                      <Button size="sm" variant="outline" onClick={() => openEdit(selected)}>
                        <Edit className="mr-1 h-4 w-4" />
                        {t('tasks.projects.edit', 'Изменить')}
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="text-destructive hover:text-destructive"
                        onClick={() => setConfirmDelete(selected)}
                      >
                        <Trash2 className="mr-1 h-4 w-4" />
                        {t('tasks.projects.delete', 'Удалить')}
                      </Button>
                    </div>
                  )}
                </div>

                <Tabs defaultValue="general">
                  <TabsList>
                    <TabsTrigger value="general">
                      {t('tasks.projects.generalTab', 'Общее')}
                    </TabsTrigger>
                    <TabsTrigger value="sites">
                      {t('tasks.projects.sitesTab', 'Объекты')} ({selected.sites?.length ?? 0})
                    </TabsTrigger>
                    <TabsTrigger value="tasks">
                      {t('tasks.projects.tasksTab', 'Задачи')} ({selected.task_count})
                    </TabsTrigger>
                  </TabsList>

                  <TabsContent value="general" className="pt-4">
                    {projectNeedsSites(selected) && (
                      <div className="mb-4 flex items-start gap-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-100">
                        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                        <span>
                          {t('tasks.projects.noSitesHint',
                            'Объекты не заданы — объект в задачах проекта придётся выбирать вручную из всего справочника.')}
                        </span>
                      </div>
                    )}
                    <dl className="grid gap-3 text-sm sm:grid-cols-2">
                      <div>
                        <dt className="text-muted-foreground">{t('tasks.projects.status.title', 'Статус')}</dt>
                        <dd>
                          <Badge className={projectStatusBadgeClass(selected.status)}>
                            {projectStatusLabel(selected.status, t)}
                          </Badge>
                        </dd>
                      </div>
                      <div>
                        <dt className="text-muted-foreground">{t('tasks.projects.owner', 'Владелец')}</dt>
                        <dd>{selected.owner_name || '—'}</dd>
                      </div>
                      <div>
                        <dt className="text-muted-foreground">{t('tasks.projects.department', 'Отдел')}</dt>
                        <dd>{selected.department_name || '—'}</dd>
                      </div>
                      <div>
                        <dt className="text-muted-foreground">{t('tasks.projects.taskCount', 'Задач')}</dt>
                        <dd>{selected.done_count} / {selected.task_count}</dd>
                      </div>
                      <div>
                        <dt className="flex items-center gap-1 text-muted-foreground">
                          <Calendar className="h-3 w-3" />{t('tasks.projects.start', 'Начало')}
                        </dt>
                        <dd>{selected.start_date || '—'}</dd>
                      </div>
                      <div>
                        <dt className="flex items-center gap-1 text-muted-foreground">
                          <Target className="h-3 w-3" />{t('tasks.projects.end', 'Завершение')}
                        </dt>
                        <dd>{selected.end_date || '—'}</dd>
                      </div>
                    </dl>
                  </TabsContent>

                  <TabsContent value="sites" className="pt-4">
                    <SitesTab
                      project={selected}
                      sites={sites}
                      canEdit={elevated}
                      onSaved={invalidate}
                    />
                  </TabsContent>

                  <TabsContent value="tasks" className="pt-4">
                    <TasksTab projectId={selected.id} />
                  </TabsContent>
                </Tabs>
              </CardContent>
            </Card>
          )}
        </div>
      </div>

      {/* ── Диалог создания/правки ──────────────────────────────── */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-h-[85vh] max-w-lg overflow-y-auto">
          <DialogHeader>
            <DialogTitle>
              {editing
                ? t('tasks.projects.edit', 'Изменить проект')
                : t('tasks.projects.newProject', 'Новый проект')}
            </DialogTitle>
          </DialogHeader>

          <div className="grid gap-4">
            <div className="grid gap-2">
              <Label htmlFor="project-name">{t('tasks.projects.name', 'Название')}</Label>
              <Input
                id="project-name"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
              />
            </div>

            <div className="grid gap-2">
              <Label htmlFor="project-description">{t('tasks.projects.description', 'Описание')}</Label>
              <Textarea
                id="project-description"
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
              />
            </div>

            {/* Мера длительности. Флаг переключает то, как читаются ВСЕ
                сроки проекта — план, факт и расхождение, — поэтому он
                стоит в форме проекта, а не в общих настройках. */}
            <div className="flex items-start justify-between gap-4 rounded-md border p-3">
              <div className="space-y-0.5">
                <Label htmlFor="project-calendar">
                  {t('tasks.projects.workingDays', 'Считать в рабочих днях')}
                </Label>
                <p className="text-xs text-muted-foreground">
                  {t('tasks.projects.workingDaysHint',
                     'По умолчанию сроки считаются в календарных днях — стройка идёт 7/7. Включите для офисных проектов: тогда выходные и праздники в срок не входят.')}
                </p>
              </div>
              <Switch
                id="project-calendar"
                checked={form.use_production_calendar}
                onCheckedChange={(checked) =>
                  setForm({ ...form, use_production_calendar: checked })}
              />
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="grid gap-2">
                <Label>{t('tasks.projects.status.title', 'Статус')}</Label>
                <Select
                  value={form.status}
                  onValueChange={(v) => setForm({ ...form, status: v as ProjectStatus })}
                >
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {PROJECT_STATUS_ORDER.map((status) => (
                      <SelectItem key={status} value={status}>
                        {projectStatusLabel(status, t)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="grid gap-2">
                <Label htmlFor="project-color">{t('tasks.projects.color', 'Цвет')}</Label>
                <Input
                  id="project-color"
                  type="color"
                  className="h-10 p-1"
                  value={form.color}
                  onChange={(e) => setForm({ ...form, color: e.target.value })}
                />
              </div>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="grid gap-2">
                <Label htmlFor="project-start">{t('tasks.projects.start', 'Начало')}</Label>
                <Input
                  id="project-start"
                  type="date"
                  value={form.start_date}
                  onChange={(e) => setForm({ ...form, start_date: e.target.value })}
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="project-end">{t('tasks.projects.end', 'Завершение')}</Label>
                <Input
                  id="project-end"
                  type="date"
                  value={form.end_date}
                  onChange={(e) => setForm({ ...form, end_date: e.target.value })}
                />
              </div>
            </div>

            <div className="grid gap-2">
              <Label>{t('tasks.projects.department', 'Отдел')}</Label>
              <Select
                value={form.department_id || '__none__'}
                onValueChange={(v) => setForm({ ...form, department_id: v === '__none__' ? '' : v })}
              >
                <SelectTrigger>
                  <SelectValue placeholder={t('tasks.projects.selectDepartment', 'Выберите отдел')} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__none__">—</SelectItem>
                  {departments.map((dept) => (
                    <SelectItem key={dept.id} value={String(dept.id)}>{dept.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <OwnerPicker
              value={form.owner_id}
              displayName={form.owner_name}
              onPick={(id, name) => setForm({ ...form, owner_id: id, owner_name: name })}
            />
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>
              {t('common.cancel', 'Отмена')}
            </Button>
            <Button
              onClick={() => {
                if (!form.name.trim()) {
                  toast.error(t('tasks.projects.nameRequired', 'Укажите название проекта'));
                  return;
                }
                saveMutation.mutate(form);
              }}
              disabled={saveMutation.isPending}
            >
              {saveMutation.isPending
                ? t('common.saving', 'Сохранение...')
                : t('common.save', 'Сохранить')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── Подтверждение удаления ──────────────────────────────── */}
      <Dialog open={confirmDelete != null} onOpenChange={(o) => !o && setConfirmDelete(null)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{t('tasks.projects.delete', 'Удалить проект')}</DialogTitle>
          </DialogHeader>
          <p className="text-sm">
            {t('tasks.projects.deleteConfirm', 'Удалить проект «{{name}}»?', {
              name: confirmDelete?.name ?? '',
            })}
          </p>
          {(confirmDelete?.task_count ?? 0) > 0 && (
            // Task.project is SET_NULL: the tasks survive but drop out of
            // every per-project report. Saying how many is the difference
            // between an informed click and a surprise.
            <p className="text-sm text-amber-700 dark:text-amber-400">
              {t('tasks.projects.deleteWarning',
                'Задач в проекте: {{count}}. Они не удалятся, но потеряют связь с проектом и пропадут из отчётов по нему.',
                { count: confirmDelete?.task_count ?? 0 })}
            </p>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmDelete(null)}>
              {t('common.cancel', 'Отмена')}
            </Button>
            <Button
              variant="destructive"
              onClick={() => confirmDelete && deleteMutation.mutate(confirmDelete.id)}
              disabled={deleteMutation.isPending}
            >
              {t('tasks.projects.delete', 'Удалить')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </TasksLayout>
  );
};

export default HRProjects;
