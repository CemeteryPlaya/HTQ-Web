import React, { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { TasksLayout } from '@/components/tasks/TasksLayout';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import {
  Collapsible, CollapsibleContent, CollapsibleTrigger,
} from '@/components/ui/collapsible';
import {
  Plus, ChevronDown, ChevronRight, Calendar, Target, MapPin, AlertCircle, Layers
} from 'lucide-react';
import { SiteWorkTree } from '@/components/tasks/SiteWorkTree';
import { buildWorkTree } from '@/lib/tasks/workTree';
import { fetchProjects, fetchProjectTasks, fetchRoadmaps } from '@/api/tasks';
import api from '@/api/client';
import { usesEmployeeTaskExperience } from '@/lib/auth/roles';
import type { UserProfile } from '@/types/userProfile';
import type { Project } from '@/types/tasks';
import { projectStatusBadgeClass, projectStatusLabel } from '@/lib/tasks/project';

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

  const tree = useMemo(
    () => buildWorkTree(project, tasks ?? [], roadmaps, t),
    [project, tasks, roadmaps, t],
  );

  return (
    <Collapsible open={open} onOpenChange={setOpen} className="w-full">
      <div
        className="rounded-2xl border bg-card/90 shadow-2xs overflow-hidden transition-all duration-200"
        style={{ borderLeftWidth: 4, borderLeftColor: project.color || '#3b82f6' }}
      >
        <CollapsibleTrigger asChild>
          <div className="p-4 cursor-pointer hover:bg-muted/30 transition-colors flex items-center justify-between gap-4">
            <div className="flex items-center gap-3 min-w-0 flex-1">
              <div className="p-1 rounded-lg hover:bg-muted text-muted-foreground transition-colors shrink-0">
                {open
                  ? <ChevronDown className="h-5 w-5" />
                  : <ChevronRight className="h-5 w-5" />}
              </div>

              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 mb-1 flex-wrap">
                  <h3 className="text-base font-bold text-foreground truncate">{project.name}</h3>
                  <Badge className={projectStatusBadgeClass(project.status)}>
                    {projectStatusLabel(project.status, t)}
                  </Badge>
                </div>

                {project.description && (
                  <p className="text-xs text-muted-foreground line-clamp-1 mb-2">{project.description}</p>
                )}

                <div className="flex items-center gap-4 text-xs text-muted-foreground flex-wrap">
                  {project.start_date && (
                    <span className="flex items-center gap-1">
                      <Calendar className="h-3.5 w-3.5" /> {t('tasks.projects.start', 'Начало')}: {project.start_date}
                    </span>
                  )}
                  {project.end_date && (
                    <span className="flex items-center gap-1">
                      <Target className="h-3.5 w-3.5" /> {t('tasks.projects.end', 'Завершение')}: {project.end_date}
                    </span>
                  )}
                  <span className="font-medium text-foreground">{t('tasks.projects.taskCount', 'Задач')}: {project.task_count}</span>
                  {project.sites?.length > 0 && (
                    <span className="flex items-center gap-1.5 flex-wrap">
                      <MapPin className="h-3.5 w-3.5" />
                      {project.sites.map((site) => (
                        <Badge
                          key={site.id}
                          variant="outline"
                          className="text-[10px] px-1.5 py-0 font-normal rounded-md"
                          style={{ borderColor: site.color, color: site.color }}
                        >
                          {site.is_primary && '★ '}{site.name}
                        </Badge>
                      ))}
                    </span>
                  )}
                </div>
              </div>
            </div>

            <div className="w-28 text-right shrink-0">
              <div className="text-xs font-bold mb-1 text-foreground">{project.progress}%</div>
              <Progress value={project.progress} className="h-2 rounded-full" />
            </div>
          </div>
        </CollapsibleTrigger>

        <CollapsibleContent>
          <div className="p-4 pt-0 border-t bg-muted/10">
            {isLoading || roadmapsLoading ? (
              <p className="text-muted-foreground text-xs py-4 text-center">{t('common.loading', 'Загрузка дерева задач…')}</p>
            ) : tree.siteRows.length === 0 ? (
              <p className="text-muted-foreground text-xs py-4 text-center">
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
          </div>
        </CollapsibleContent>
      </div>
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
      subtitle={t('tasks.projects.pageSubtitle', 'Иерархическое дерево проектов, объектов и этапов')}
    >
      {/* Header Toolbar */}
      <div className="rounded-3xl border bg-card p-4 shadow-2xs flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-2xl bg-primary/10 flex items-center justify-center text-primary shrink-0">
            <Layers className="h-5 w-5" />
          </div>
          <div>
            <h2 className="text-sm font-bold text-foreground">Дерево объектов и задач</h2>
            <p className="text-xs text-muted-foreground">
              {t('tasks.projects.intro', 'Раскройте проект для детализации по объектам, блокам и пакетам задач.')}
            </p>
          </div>
        </div>

        {!isRegularEmployee && (
          <Button asChild className="h-9 gap-2 rounded-xl bg-primary text-primary-foreground hover:bg-primary/90 font-semibold shadow-2xs shrink-0">
            <Link to="/manage/projects">
              <Plus className="h-4 w-4" />
              {t('tasks.projects.manageLink', 'Управление проектами')}
            </Link>
          </Button>
        )}
      </div>

      {/* Projects list */}
      <div className="rounded-3xl border bg-card p-4 shadow-2xs space-y-3">
        {isLoading ? (
          <p className="text-center text-muted-foreground text-xs py-8">{t('common.loading', 'Загрузка проектов…')}</p>
        ) : error ? (
          <div className="flex items-center gap-2 justify-center text-red-500 text-xs py-8">
            <AlertCircle className="h-5 w-5" />
            {t('tasks.projects.loadError', 'Не удалось загрузить проекты')}
          </div>
        ) : projects.length === 0 ? (
          <p className="text-center text-muted-foreground text-xs py-8">
            {t('tasks.projects.noProjects', 'Пока нет ни одного проекта')}
          </p>
        ) : (
          projects.map((p) => <ProjectCard key={p.id} project={p} />)
        )}
      </div>
    </TasksLayout>
  );
};

export default HRRoadmap;
