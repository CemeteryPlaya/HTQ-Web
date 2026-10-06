/**
 * «Проектные роли» — справочник компании (спек
 * docs/plans/2026-10-06-project-structure-spec.md §2.1, §5).
 *
 * Роль одна на все проекты («Технический директор» — та же на любом), у неё
 * уровень L1–L4 и часть по умолчанию. Правит держатель узла
 * `project.roles` (ФД, ТД, ОД, ГД, АДМ, `hr-lead`); остальным — «Недостаточно
 * прав». Роль, уже стоящую на местах, сервер не удаляет и не даёт сменить ей
 * уровень (409 `E-PRJ-07`) — её выключают.
 */
import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { usePermissions } from '@/hooks/usePermissions';
import { reportApiError } from '@/lib/apiError';

import { PROJECTS_BASE } from './api';
import { LEVELS, structureApi, structureKeys, type ProjectPart } from './structureApi';

const selectClass = 'h-9 rounded-md border bg-background px-2 text-sm';

export function ProjectRolesPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const permissions = usePermissions();
  const canEdit = permissions.can('project.roles', 'edit');
  const [name, setName] = useState('');
  const [level, setLevel] = useState('3');
  const [part, setPart] = useState<ProjectPart>('office');
  const [busy, setBusy] = useState(false);

  const roles = useQuery({
    queryKey: structureKeys.roles(false),
    queryFn: () => structureApi.roles(false),
    enabled: canEdit,
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: structureKeys.rolesAll });

  const run = async (action: () => Promise<unknown>) => {
    if (busy) return;
    setBusy(true);
    try {
      await action();
      await refresh();
    } catch (error) {
      reportApiError(error, t('bpp.structure.rolesFailed', 'Не удалось изменить справочник ролей'));
    } finally {
      setBusy(false);
    }
  };

  const back = (
    <Link to={PROJECTS_BASE} className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
      <ArrowLeft className="h-4 w-4" />
      {t('bpp.projects.backToList', 'К списку проектов')}
    </Link>
  );

  if (!canEdit) {
    return (
      <div className="space-y-4">
        {back}
        <p className="rounded-2xl border bg-card p-8 text-center text-sm text-muted-foreground">
          {t('common.errors.forbidden', 'Недостаточно прав для этого действия')}
        </p>
      </div>
    );
  }

  const partLabel = (value: ProjectPart) =>
    value === 'office' ? t('bpp.structure.office', 'Офис') : t('bpp.structure.site', 'Объект');

  return (
    <div className="space-y-4">
      {back}
      <h2 className="text-2xl font-bold tracking-tight">{t('bpp.structure.rolesTitle', 'Проектные роли')}</h2>

      <form className="flex flex-wrap items-end gap-3 rounded-2xl border bg-card p-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (!name.trim()) return;
          void run(async () => {
            await structureApi.createRole({ name: name.trim(), level: Number(level), default_part: part, sort_order: 0 });
            setName('');
          });
        }}>
        <div className="space-y-1">
          <Label htmlFor="role-name">{t('bpp.structure.roleName', 'Название')}</Label>
          <Input id="role-name" value={name} maxLength={100} onChange={(e) => setName(e.target.value)} className="w-64" />
        </div>
        <div className="space-y-1">
          <Label htmlFor="role-level">{t('bpp.structure.level', 'Уровень')}</Label>
          <select id="role-level" className={selectClass} value={level} onChange={(e) => setLevel(e.target.value)}>
            {LEVELS.map((l) => <option key={l} value={l}>{`L${l}`}</option>)}
          </select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="role-part">{t('bpp.structure.defaultPart', 'Часть по умолчанию')}</Label>
          <select id="role-part" className={selectClass} value={part} onChange={(e) => setPart(e.target.value as ProjectPart)}>
            <option value="office">{partLabel('office')}</option>
            <option value="site">{partLabel('site')}</option>
          </select>
        </div>
        <Button type="submit" disabled={busy || !name.trim()}>{t('bpp.structure.addRole', 'Добавить роль')}</Button>
      </form>

      {roles.isLoading ? (
        <Skeleton className="h-40 w-full" />
      ) : roles.isError ? (
        <p className="text-sm text-destructive">{t('bpp.structure.rolesLoadError', 'Не удалось загрузить справочник')}</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t('bpp.structure.level', 'Уровень')}</TableHead>
                <TableHead>{t('bpp.structure.roleName', 'Название')}</TableHead>
                <TableHead>{t('bpp.structure.defaultPart', 'Часть по умолчанию')}</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {(roles.data ?? []).map((role) => (
                <TableRow key={role.id}>
                  <TableCell>{`L${role.level}`}</TableCell>
                  <TableCell>
                    {role.name}
                    {!role.is_active && (
                      <Badge variant="secondary" className="ml-2">{t('bpp.structure.inactive', 'выключена')}</Badge>
                    )}
                  </TableCell>
                  <TableCell>{partLabel(role.default_part)}</TableCell>
                  <TableCell className="space-x-3 text-right text-sm">
                    <button type="button" className="hover:underline" disabled={busy}
                      onClick={() => { void run(() => structureApi.updateRole(role.id, { is_active: !role.is_active })); }}>
                      {role.is_active ? t('bpp.structure.disable', 'Выключить') : t('bpp.structure.enable', 'Включить')}
                    </button>
                    <button type="button" className="text-destructive hover:underline" disabled={busy}
                      onClick={() => { void run(() => structureApi.deleteRole(role.id)); }}>
                      {t('bpp.structure.delete', 'Удалить')}
                    </button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}

export default ProjectRolesPage;
