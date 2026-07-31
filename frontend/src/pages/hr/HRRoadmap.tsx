/**
 * HRRoadmap — вся иерархия работ одним деревом.
 *
 * Проект → площадка → блок → роудмап (пакет работ) → задачи → подзадачи.
 *
 * Раньше страница показывала два уровня, проект → задачи, и называлась
 * «дорожной картой» при том, что роудмапа как сущности не существовало.
 * Теперь он есть и живёт на блоке, так что уровней пять; роут
 * `/tasks/roadmap` при этом тот же.
 *
 * Две корзины, которые НЕ являются ошибкой и потому показываются наравне
 * с остальным:
 *
 * * «без роудмапа» — задачи проекта вне пакетов; так живут все задачи,
 *   заведённые до появления этого уровня;
 * * «без блока» — задача не привязана к участку;
 * * «без объекта» — у исторических задач объекта нет и не будет.
 *
 * Standalone-задачи (project = null) сюда по-прежнему не попадают — они
 * живут на основной доске.
 */
import React, { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { TasksLayout } from '@/components/tasks/TasksLayout';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import {
  Collapsible, CollapsibleContent, CollapsibleTrigger,
} from '@/components/ui/collapsible';
import {
  Plus, ChevronDown, ChevronRight, Calendar, Target, MapPin, AlertCircle,
} from 'lucide-react';
import { SiteWorkTree } from '@/components/tasks/SiteWorkTree';
import { buildWorkTree } from '@/lib/tasks/workTree';
import { fetchProjects, fetchProjectTasks, fetchRoadmaps } from '@/api/tasks';
import api from '@/api/client';
import { usesEmployeeTaskExperience } from '@/lib/auth/roles';
import type { UserProfile } from '@/types/userProfile';
import type { Project } from '@/types/tasks';
import { projectStatusBadgeClass, projectStatusLabel } from '@/lib/tasks/project';

/* ---- Config ---- */

// Project status palette moved to `lib/tasks/project.ts` — it is shared with
// the projects page now, and a second copy is how the task-status table
// ended up with three divergent versions.

/* ---- Project card with expandable nested tasks ---- */

function ProjectCard({ project }: { project: Project }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const { data: tasks, isLoading } = useQuery({
    queryKey: ['hr-project-tasks', project.id],
    queryFn: () => fetchProjectTasks(project.id),
    enabled: open,
  });
  const { data: roadmaps = [], isLoading: roadmapsLoading } = useQuery({
    queryKey: ['hr-project-roadmaps', project.id],
    queryFn: () => fetchRoadmaps({ project_id: project.id }),
    enabled: open,
  });

  // Раскладка по площадкам, блокам и пакетам — общая с вкладкой
  // «Объекты» карточки проекта.
  const tree = useMemo(
    () => buildWorkTree(project, tasks ?? [], roadmaps, t),
    [project, tasks, roadmaps, t],
  );

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
                  <Badge className={projectStatusBadgeClass(project.status)}>
                    {projectStatusLabel(project.status, t)}
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
                  {project.sites?.length > 0 && (
                    <span className="flex items-center gap-1.5 flex-wrap">
                      <MapPin className="h-3 w-3" />
                      {project.sites.map((site) => (
                        <Badge
                          key={site.id}
                          variant="outline"
                          className="text-[10px] px-1.5 py-0 font-normal"
                          style={{ borderColor: site.color, color: site.color }}
                          title={site.is_primary
                            ? t('tasks.pages.sites.primary', 'Основной объект')
                            : undefined}
                        >
                          {site.is_primary && '★ '}{site.name}
                        </Badge>
                      ))}
                    </span>
                  )}
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
            {isLoading || roadmapsLoading ? (
              <p className="text-muted-foreground text-sm py-4">{t('common.loading', 'Загрузка...')}</p>
            ) : tree.siteRows.length === 0 ? (
              <p className="text-muted-foreground text-sm py-4">
                {t('tasks.projects.empty', 'В проекте нет задач')}
              </p>
            ) : (
              <SiteWorkTree
                project={project}
                tasks={tasks ?? []}
                roadmaps={roadmaps}
                t={t}
              />
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
          {/* Creation lives on /manage/projects, not here. The dialog that
              used to sit on this page could not assign objects, so every
              project born on the roadmap was permanently object-less — and
              a project without objects opts out of the whole
              project→object→task axis. One form, one place. */}
          {!isRegularEmployee && (
            <Button asChild>
              <Link to="/manage/projects">
                <Plus className="h-4 w-4 mr-1" />
                {t('tasks.projects.manageLink', 'Управление проектами')}
              </Link>
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

    </TasksLayout>
  );
};

export default HRRoadmap;
