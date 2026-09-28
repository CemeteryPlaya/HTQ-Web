/**
 * «Проекты» (D-02) — список проектов компании для модуля БЗО.
 *
 * Кого показывать, решает сервер: ПМ (без узла `project.all`) получает
 * только проекты, где он участник, — экран сам ничего не отсеивает.
 * «Только мои» — параметр `mine=1` для тех, кто видит все. Архивных
 * проектов ручка не отдаёт.
 *
 * «Новый проект» — по узлу `project.projects` `create`.
 */
import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { Plus, Search } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { usePermissions } from '@/hooks/usePermissions';

import { projectApi, projectHref, projectKeys } from './api';
import { projectKindLabel } from './labels';
import { ProjectFormDialog } from './ProjectFormDialog';
import { ProjectStatusBadge } from './ProjectStatusBadge';
import { useUserNames } from './useUserNames';

export function ProjectsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const permissions = usePermissions();
  const nameOf = useUserNames();
  const [search, setSearch] = useState('');
  const [mine, setMine] = useState(false);
  const [creating, setCreating] = useState(false);

  const query = search.trim();
  const { data = [], isLoading, isError } = useQuery({
    queryKey: projectKeys.list(query, mine),
    queryFn: () => projectApi.list(query, mine),
  });

  const canCreate = permissions.can('project.projects', 'create');
  const colSpan = 6;

  return (
    <div className="space-y-4">
      <h2 className="text-2xl font-bold tracking-tight">{t('bpp.projects.title', 'Проекты')}</h2>

      <div className="flex flex-wrap items-center gap-3">
        <div className="relative w-full sm:w-72">
          <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={t('bpp.projects.search', 'Поиск по коду и наименованию')}
            aria-label={t('bpp.projects.searchLabel', 'Поиск проекта')}
            className="pl-8"
          />
        </div>
        <label className="flex items-center gap-2 text-sm">
          <Checkbox checked={mine} onCheckedChange={(checked) => setMine(checked === true)} />
          {t('bpp.projects.mine', 'Только мои')}
        </label>
        {canCreate && (
          <Button size="sm" className="ml-auto" onClick={() => setCreating(true)}>
            <Plus className="mr-1.5 h-4 w-4" />
            {t('bpp.projects.create', 'Новый проект')}
          </Button>
        )}
      </div>

      <div className="overflow-x-auto rounded-lg border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t('bpp.projects.code', 'Код')}</TableHead>
              <TableHead>{t('bpp.projects.name', 'Наименование')}</TableHead>
              <TableHead>{t('bpp.projects.kindTitle', 'Вид')}</TableHead>
              <TableHead>{t('bpp.projects.country', 'Страна')}</TableHead>
              <TableHead>{t('bpp.projects.manager', 'Руководитель проекта')}</TableHead>
              <TableHead>{t('bpp.projects.statusTitle', 'Статус')}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              [0, 1, 2].map((row) => (
                <TableRow key={row}>
                  <TableCell colSpan={colSpan}><Skeleton className="h-6 w-full" /></TableCell>
                </TableRow>
              ))
            ) : isError ? (
              <TableRow>
                <TableCell colSpan={colSpan} className="py-8 text-center text-destructive">
                  {t('bpp.projects.loadError', 'Не удалось загрузить проекты. Обновите страницу.')}
                </TableCell>
              </TableRow>
            ) : data.length === 0 ? (
              <TableRow>
                <TableCell colSpan={colSpan} className="py-10 text-center text-muted-foreground">
                  {query
                    ? t('bpp.projects.nothingFound', 'Ничего не найдено. Измените поиск.')
                    : t('bpp.projects.empty', 'Проектов, доступных вам, нет')}
                </TableCell>
              </TableRow>
            ) : (
              data.map((project) => (
                <TableRow
                  key={project.id}
                  className="cursor-pointer"
                  onClick={() => navigate(projectHref(project.id))}
                >
                  <TableCell className="font-mono">{project.code}</TableCell>
                  <TableCell className="font-medium">{project.name}</TableCell>
                  <TableCell>{projectKindLabel(t, project.kind)}</TableCell>
                  <TableCell>{project.country_code}</TableCell>
                  <TableCell>{nameOf(project.manager_user_id)}</TableCell>
                  <TableCell><ProjectStatusBadge status={project.status} /></TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      {canCreate && (
        <ProjectFormDialog
          open={creating}
          onOpenChange={setCreating}
          onSaved={(project) => {
            void queryClient.invalidateQueries({ queryKey: projectKeys.all });
            navigate(projectHref(project.id));
          }}
        />
      )}
    </div>
  );
}

export default ProjectsPage;
