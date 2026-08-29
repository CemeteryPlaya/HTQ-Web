import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, Loader2, Plus, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

import { accessApi } from '@/api/access';
import api from '@/api/client';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import type { Role, RoleAssignment } from '@/types/access';

/**
 * Личные назначения ролей — ИСКЛЮЧИТЕЛЬНЫЙ путь (§4.4 спеки стадии 2).
 *
 * Штатный путь — роли должности. Это окно закрывает то, чего должность
 * закрыть не может: директор холдинга без кадровой карточки, исполняющий
 * обязанности, временное расширение на период. Поэтому оно и выглядит
 * исключением — с предупреждением наверху, а не как второй равноправный
 * способ раздать права.
 *
 * **Объектной области здесь нет намеренно.** Контракт её принимает, но фильтр
 * по объекту в домене задач стадия не делает (§7 спеки): назначение с такой
 * областью не сузило бы ничего и молча работало бы как «вся компания». Дать
 * выбрать её значило бы дать завести данные, которые не действуют.
 */

export interface UserAssignmentsDialogProps {
  userId: number | null;
  userLabel: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  canEdit?: boolean;
}

interface Department {
  id: number;
  name: string;
}

export function UserAssignmentsDialog({
  userId,
  userLabel,
  open,
  onOpenChange,
  canEdit = true,
}: UserAssignmentsDialogProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<RoleAssignment[] | null>(null);
  const [pendingRole, setPendingRole] = useState('');
  const [pendingDepartment, setPendingDepartment] = useState('');

  const enabled = open && userId !== null;

  const rolesQuery = useQuery({
    queryKey: ['access', 'roles'],
    queryFn: async () => (await accessApi.listRoles()).data,
    enabled: open,
  });

  const currentQuery = useQuery({
    queryKey: ['access', 'assignments', userId],
    queryFn: async () => (await accessApi.getAssignments(userId as number)).data,
    enabled,
  });

  const departmentsQuery = useQuery({
    queryKey: ['hr-departments'],
    queryFn: async () => {
      const res = await api.get<Department[] | { results: Department[] }>('hr/v1/departments/');
      return Array.isArray(res.data) ? res.data : res.data.results ?? [];
    },
    enabled: open,
  });

  useEffect(() => {
    if (currentQuery.data) setDraft(currentQuery.data);
  }, [currentQuery.data]);

  useEffect(() => {
    if (!open) {
      setDraft(null);
      setPendingRole('');
      setPendingDepartment('');
    }
  }, [open]);

  const saveMutation = useMutation({
    mutationFn: () => accessApi.putAssignments(userId as number, draft ?? []),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['access', 'assignments', userId] });
      toast.success(t('access.assignments.saved', 'Личные назначения сохранены'));
      onOpenChange(false);
    },
    onError: () => toast.error(t('access.assignments.saveFailed', 'Не удалось сохранить')),
  });

  const roles: Role[] = rolesQuery.data ?? [];
  const roleTitle = (id: number) => roles.find((role) => role.id === id)?.title ?? `#${id}`;
  const departments = departmentsQuery.data ?? [];
  const departmentName = (id: number | null) =>
    departments.find((department) => department.id === id)?.name ?? `#${id}`;

  const add = () => {
    const roleId = Number(pendingRole);
    if (!roleId) return;
    const scopedToDepartment = pendingDepartment !== '';
    const next: RoleAssignment = scopedToDepartment
      ? { role_id: roleId, scope_kind: 'department', scope_id: Number(pendingDepartment) }
      : { role_id: roleId, scope_kind: 'company', scope_id: null };
    setDraft((prev) => [...(prev ?? []), next]);
    setPendingRole('');
    setPendingDepartment('');
  };

  const remove = (index: number) =>
    setDraft((prev) => (prev ?? []).filter((_item, i) => i !== index));

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] max-w-lg overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {t('access.assignments.title', 'Личные назначения')}: {userLabel}
          </DialogTitle>
          <DialogDescription>
            {t(
              'access.assignments.hint',
              'Действуют только в текущей компании и только на этого человека.',
            )}
          </DialogDescription>
        </DialogHeader>

        <div className="flex items-start gap-2 rounded-lg border border-amber-300/70 bg-amber-50/70 px-3 py-2 text-xs text-amber-900 dark:border-amber-800/70 dark:bg-amber-950/30 dark:text-amber-200">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <p>
            {t(
              'access.assignments.exceptionWarning',
              'Это исключение, а не штатный путь. Обычно права выдаются должности — тогда они '
              + 'достаются всем, кто её занимает, и не теряются при замене человека.',
            )}
          </p>
        </div>

        {currentQuery.isLoading ? (
          <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            {t('common.loading', 'Загрузка…')}
          </div>
        ) : (
          <ul className="space-y-2">
            {(draft ?? []).map((item, index) => (
              <li
                key={`${item.role_id}-${item.scope_kind}-${item.scope_id}-${index}`}
                className="flex items-center gap-2 rounded-md border p-2 text-sm"
              >
                <div className="min-w-0 flex-1">
                  <span className="block truncate font-medium">{roleTitle(item.role_id)}</span>
                  <span className="block truncate text-xs text-muted-foreground">
                    {item.scope_kind === 'company'
                      ? t('access.assignments.wholeCompany', 'вся компания')
                      : `${t('access.assignments.department', 'отдел')}: ${departmentName(item.scope_id)}`}
                  </span>
                </div>
                {canEdit && (
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label={t('access.assignments.remove', 'Убрать назначение')}
                    onClick={() => remove(index)}
                  >
                    <X className="h-4 w-4" />
                  </Button>
                )}
              </li>
            ))}
            {(draft ?? []).length === 0 && (
              <li className="py-4 text-center text-sm text-muted-foreground">
                {t('access.assignments.empty', 'Личных назначений нет — права идут от должности')}
              </li>
            )}
          </ul>
        )}

        {canEdit && (
          <div className="space-y-2 rounded-md border p-3">
            <label className="block text-xs font-medium" htmlFor="assignment-role">
              {t('access.assignments.addRole', 'Добавить роль')}
            </label>
            <select
              id="assignment-role"
              className="h-9 w-full rounded-md border bg-background px-2 text-sm"
              value={pendingRole}
              onChange={(event) => setPendingRole(event.target.value)}
            >
              <option value="">{t('access.assignments.pickRole', '— выберите роль —')}</option>
              {roles.map((role) => (
                <option key={role.id} value={role.id}>{role.title}</option>
              ))}
            </select>

            <label className="block text-xs font-medium" htmlFor="assignment-scope">
              {t('access.assignments.scope', 'Область')}
            </label>
            <select
              id="assignment-scope"
              className="h-9 w-full rounded-md border bg-background px-2 text-sm"
              value={pendingDepartment}
              onChange={(event) => setPendingDepartment(event.target.value)}
            >
              <option value="">{t('access.assignments.wholeCompany', 'вся компания')}</option>
              {departments.map((department) => (
                <option key={department.id} value={department.id}>{department.name}</option>
              ))}
            </select>

            <Button size="sm" className="w-full gap-1.5" disabled={!pendingRole} onClick={add}>
              <Plus className="h-4 w-4" />
              {t('access.assignments.add', 'Добавить')}
            </Button>
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t('common.cancel', 'Отмена')}
          </Button>
          {canEdit && (
            <Button
              onClick={() => saveMutation.mutate()}
              disabled={draft === null || saveMutation.isPending}
            >
              {t('access.assignments.save', 'Сохранить')}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default UserAssignmentsDialog;
