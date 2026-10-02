/**
 * Карточка проекта (D-02): реквизиты и участники.
 *
 * Чужой проект сервер отдаёт 404, как несуществующий (у ПМ без узла
 * `project.all` — все, где он не участник), — экран говорит «Проект не
 * найден», не различая причин.
 *
 * Правка — узел `project.projects` `edit`; участники — `project.members`
 * `edit` (ПМ и HR, Q-B17). Руководитель — участник автоматически и не
 * снимается, пока он руководитель (сервер ответит 422 E-PRJ-02), поэтому
 * кнопки «Убрать» у него нет.
 *
 * «Доска задач» — ссылка на доску задач проекта (`/manage/projects?board=`)
 * у держателей узла `project.board` (ТД, ОД, АДМ, ПМ — решение 01.10); доски
 * нет — так и написано.
 */
import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft, Pencil, X } from 'lucide-react';

import { fetchProjectBoard } from '@/api/tasks';
import { EmployeePicker } from '@/components/common/EmployeePicker';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { usePermissions } from '@/hooks/usePermissions';
import { errorStatus, reportApiError } from '@/lib/apiError';

import { formatDate } from '../format';

import { PROJECTS_BASE, projectApi, projectKeys, type Project } from './api';
import { projectKindLabel } from './labels';
import { ProjectFormDialog } from './ProjectFormDialog';
import { ProjectStatusBadge } from './ProjectStatusBadge';
import { useUserNames } from './useUserNames';

function Detail({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="text-sm">{value || '—'}</dd>
    </div>
  );
}

export function ProjectCardPage() {
  const { t } = useTranslation();
  const { id = '' } = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const permissions = usePermissions();
  const nameOf = useUserNames();
  const [editing, setEditing] = useState(false);
  const [busyMember, setBusyMember] = useState<number | null>(null);

  const project = useQuery({
    queryKey: projectKeys.card(id),
    queryFn: () => projectApi.get(id),
    enabled: Boolean(id),
  });
  const members = useQuery({
    queryKey: projectKeys.members(id),
    queryFn: () => projectApi.members(id),
    enabled: project.isSuccess,
  });

  const canEdit = permissions.can('project.projects', 'edit');
  const canMembers = permissions.can('project.members', 'edit');
  const canBoard = permissions.can('project.board', 'view');
  const board = useQuery({
    queryKey: ['tasks', 'project-board', id],
    queryFn: () => fetchProjectBoard(id),
    enabled: project.isSuccess && canBoard,
  });

  const refreshMembers = () => queryClient.invalidateQueries({ queryKey: projectKeys.members(id) });

  const changeMember = async (userId: number, add: boolean) => {
    if (busyMember !== null) return;
    setBusyMember(userId);
    try {
      if (add) await projectApi.addMember(id, userId);
      else await projectApi.removeMember(id, userId);
      await refreshMembers();
    } catch (error) {
      reportApiError(error, t('bpp.projects.membersFailed', 'Не удалось изменить участников'));
    } finally {
      setBusyMember(null);
    }
  };

  const back = (
    <Link to={PROJECTS_BASE} className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
      <ArrowLeft className="h-4 w-4" />
      {t('bpp.projects.backToList', 'К списку проектов')}
    </Link>
  );

  if (project.isLoading) return <Skeleton className="h-64 w-full" />;
  if (project.error || !project.data) {
    return (
      <div className="space-y-4">
        {back}
        <p className="rounded-2xl border bg-card p-8 text-center text-sm text-muted-foreground">
          {errorStatus(project.error) === 404
            ? t('bpp.projects.notFound', 'Проект не найден')
            : t('bpp.projects.cardLoadError', 'Не удалось загрузить проект. Обновите страницу.')}
        </p>
      </div>
    );
  }

  const data: Project = project.data;
  const memberIds = members.data ?? [];

  return (
    <div className="space-y-6">
      {back}
      <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-2xl font-bold tracking-tight">{data.name}</h2>
            <ProjectStatusBadge status={data.status} />
          </div>
          <p className="text-sm text-muted-foreground">
            <span className="font-mono">{data.code}</span>
            {' · '}{projectKindLabel(t, data.kind)}{' · '}{data.country_code}
          </p>
        </div>
        {canEdit && (
          <Button variant="outline" onClick={() => setEditing(true)}>
            <Pencil className="mr-1.5 h-4 w-4" />
            {t('bpp.projects.edit', 'Изменить')}
          </Button>
        )}
      </header>

      <dl className="grid gap-4 rounded-2xl border bg-card p-4 sm:grid-cols-2 sm:p-6">
        <Detail label={t('bpp.projects.manager', 'Руководитель проекта')} value={nameOf(data.manager_user_id)} />
        <Detail label={t('bpp.projects.customer', 'Заказчик')} value={data.customer_name} />
        <Detail label={t('bpp.projects.dateStart', 'Начало')} value={data.date_start ? formatDate(data.date_start) : ''} />
        <Detail label={t('bpp.projects.dateEnd', 'Окончание')} value={data.date_end ? formatDate(data.date_end) : ''} />
        {canBoard && (
          <div data-testid="project-board">
            <dt className="text-xs text-muted-foreground">{t('bpp.projects.board', 'Доска задач')}</dt>
            <dd className="text-sm">
              {board.isLoading ? (
                <Skeleton className="h-5 w-40" />
              ) : board.data ? (
                <Link to={`/manage/projects?board=${board.data.id}`} className="text-primary hover:underline">
                  {board.data.name}
                </Link>
              ) : board.isError ? (
                t('bpp.projects.boardLoadError', 'Не удалось проверить доску задач')
              ) : (
                t('bpp.projects.noBoard', 'Доски задач у проекта нет')
              )}
            </dd>
          </div>
        )}
      </dl>

      <section className="space-y-3">
        <h3 className="text-lg font-semibold">{t('bpp.projects.members', 'Участники')}</h3>
        {members.isLoading ? (
          <Skeleton className="h-10 w-full" />
        ) : members.isError ? (
          <p className="text-sm text-destructive">
            {t('bpp.projects.membersLoadError', 'Не удалось загрузить участников')}
          </p>
        ) : memberIds.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t('bpp.projects.noMembers', 'Участников нет')}</p>
        ) : (
          <ul className="flex flex-wrap gap-2">
            {memberIds.map((userId) => {
              const isManager = userId === data.manager_user_id;
              return (
                <li key={userId} className="inline-flex items-center gap-1.5 rounded-full border bg-muted/40 px-3 py-1 text-sm">
                  {nameOf(userId)}
                  {isManager && (
                    <Badge variant="secondary" className="h-5 px-1.5 text-[11px]">
                      {t('bpp.projects.managerShort', 'руководитель')}
                    </Badge>
                  )}
                  {canMembers && !isManager && (
                    <button
                      type="button"
                      disabled={busyMember !== null}
                      onClick={() => { void changeMember(userId, false); }}
                      aria-label={t('bpp.projects.removeMember', 'Убрать участника {{name}}', { name: nameOf(userId) })}
                      className="text-muted-foreground hover:text-destructive disabled:opacity-50"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        )}
        {canMembers && (
          <EmployeePicker
            value={[]}
            onChange={(ids) => { if (ids[0] !== undefined) void changeMember(ids[0], true); }}
            multiple={false}
            addLabel={t('bpp.projects.addMember', 'Добавить участника')}
          />
        )}
      </section>

      {canEdit && (
        <ProjectFormDialog
          open={editing}
          onOpenChange={setEditing}
          project={data}
          onSaved={(saved) => {
            queryClient.setQueryData(projectKeys.card(saved.id), saved);
            void queryClient.invalidateQueries({ queryKey: projectKeys.all });
            void refreshMembers(); // новый руководитель — участник автоматически
          }}
        />
      )}
    </div>
  );
}

export default ProjectCardPage;
