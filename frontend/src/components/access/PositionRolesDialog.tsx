import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

import { accessApi } from '@/api/access';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import type { Role } from '@/types/access';

/**
 * Роли должности — штатный путь выдачи прав (§4.3 спеки стадии 2).
 *
 * Права получает должность, а не человек: одинаковый набор, выданный десяти
 * должностям, правится в одном месте. Личные назначения существуют, но живут
 * на карточке учётной записи и помечены исключением — здесь их нет намеренно,
 * они ключуются на пользователе, а у должности пользователей много.
 *
 * Набор заменяется ЦЕЛИКОМ одним запросом: серия «добавить/убрать» прошла бы
 * через состояния, которых администратор не выбирал, и обрыв посередине
 * оставил бы должность с половиной ролей.
 */

export interface PositionRolesDialogProps {
  positionId: number | null;
  positionTitle: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Правка доступна не всем: у гейта на бэкенде свои правила. */
  canEdit?: boolean;
}

export function PositionRolesDialog({
  positionId,
  positionTitle,
  open,
  onOpenChange,
  canEdit = true,
}: PositionRolesDialogProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<number[] | null>(null);

  const enabled = open && positionId !== null;

  const rolesQuery = useQuery({
    queryKey: ['access', 'roles'],
    queryFn: async () => (await accessApi.listRoles()).data,
    enabled: open,
  });

  const currentQuery = useQuery({
    queryKey: ['access', 'positions', positionId, 'roles'],
    queryFn: async () => (await accessApi.getPositionRoles(positionId as number)).data,
    enabled,
  });

  useEffect(() => {
    if (currentQuery.data) setSelected(currentQuery.data.map((item) => item.role_id));
  }, [currentQuery.data]);

  // Закрытие сбрасывает черновик: иначе следующая должность откроется с
  // набором предыдущей, и разница заметна далеко не сразу.
  useEffect(() => {
    if (!open) setSelected(null);
  }, [open]);

  const saveMutation = useMutation({
    mutationFn: () => accessApi.putPositionRoles(positionId as number, selected ?? []),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ['access', 'positions', positionId, 'roles'],
      });
      toast.success(t('access.positionRoles.saved', 'Роли должности сохранены'));
      onOpenChange(false);
    },
    onError: () => toast.error(t('access.positionRoles.saveFailed', 'Не удалось сохранить роли')),
  });

  const roles: Role[] = rolesQuery.data ?? [];
  const isLoading = rolesQuery.isLoading || currentQuery.isLoading;

  const toggle = (roleId: number, checked: boolean) => {
    setSelected((prev) => {
      const base = prev ?? [];
      return checked ? [...base, roleId] : base.filter((id) => id !== roleId);
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] max-w-lg overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {t('access.positionRoles.title', 'Роли должности')}: {positionTitle}
          </DialogTitle>
          <DialogDescription>
            {t(
              'access.positionRoles.hint',
              'Права получают все сотрудники этой должности. Роли общие для всех компаний, '
              + 'а набор действует только в текущей.',
            )}
          </DialogDescription>
        </DialogHeader>

        {isLoading ? (
          <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            {t('common.loading', 'Загрузка…')}
          </div>
        ) : (
          <ul className="space-y-2">
            {roles.map((role) => {
              const checked = (selected ?? []).includes(role.id);
              return (
                <li key={role.id} className="flex items-start gap-3 rounded-md border p-2">
                  <Checkbox
                    id={`role-${role.id}`}
                    checked={checked}
                    disabled={!canEdit}
                    onCheckedChange={(value) => toggle(role.id, value === true)}
                  />
                  <label htmlFor={`role-${role.id}`} className="min-w-0 flex-1 cursor-pointer">
                    <span className="block truncate text-sm font-medium">{role.title}</span>
                    <span className="block truncate text-xs text-muted-foreground">
                      {role.code}
                    </span>
                  </label>
                </li>
              );
            })}
            {roles.length === 0 && (
              <li className="py-6 text-center text-sm text-muted-foreground">
                {t('access.positionRoles.noRoles', 'В каталоге пока нет ролей')}
              </li>
            )}
          </ul>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t('common.cancel', 'Отмена')}
          </Button>
          {canEdit && (
            <Button
              onClick={() => saveMutation.mutate()}
              disabled={selected === null || saveMutation.isPending}
            >
              {t('access.positionRoles.save', 'Сохранить')}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default PositionRolesDialog;
