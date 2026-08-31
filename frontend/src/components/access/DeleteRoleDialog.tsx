import { useQuery } from '@tanstack/react-query';
import { Loader2, Users } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { accessApi } from '@/api/access';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import type { Role, RoleHolder } from '@/types/access';

/**
 * Удаление роли: сначала показать, у кого она есть.
 *
 * Роль удаляется только свободной, и это правило само по себе бесполезно, если
 * отказ называет одно число. «Назначена трём должностям» не говорит, к кому
 * идти: снять роль по такому ответу нельзя, придётся искать вручную по всем
 * компаниям. Поэтому диалог спрашивает держателей ДО удаления и показывает их
 * поимённо — с компанией, отделом и должностью.
 *
 * Различие «должностной / личный» важнее, чем кажется: должностного снимают у
 * ДОЛЖНОСТИ, иначе роль вернётся следующему сотруднику на этом месте, а
 * личного — у человека.
 */

export interface DeleteRoleDialogProps {
  role: Role | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: (role: Role) => void;
  isDeleting?: boolean;
}

export function DeleteRoleDialog({
  role,
  open,
  onOpenChange,
  onConfirm,
  isDeleting = false,
}: DeleteRoleDialogProps) {
  const { t } = useTranslation();

  const holdersQuery = useQuery({
    queryKey: ['access', 'roles', role?.id, 'holders'],
    queryFn: async () => (await accessApi.getRoleHolders(role!.id)).data,
    enabled: open && role !== null,
  });

  const holders: RoleHolder[] = holdersQuery.data ?? [];
  const free = !holdersQuery.isLoading && holders.length === 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {t('access.delete.title', 'Удалить роль')}: {role?.title}
          </DialogTitle>
          <DialogDescription>
            {free
              ? t('access.delete.free', 'Роль ни у кого не задействована — её можно удалить.')
              : t('access.delete.inUse',
                'Роль задействована. Удалить её можно только после того, как её '
                + 'снимут у всех перечисленных.')}
          </DialogDescription>
        </DialogHeader>

        {holdersQuery.isLoading ? (
          <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            {t('common.loading', 'Загрузка…')}
          </div>
        ) : holders.length > 0 ? (
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full text-sm">
              <thead className="bg-muted/50 text-xs text-muted-foreground">
                <tr>
                  <th scope="col" className="px-3 py-2 text-left font-medium">
                    {t('access.delete.person', 'Сотрудник')}
                  </th>
                  <th scope="col" className="px-3 py-2 text-left font-medium">
                    {t('access.delete.company', 'Компания')}
                  </th>
                  <th scope="col" className="px-3 py-2 text-left font-medium">
                    {t('access.delete.department', 'Отдел')}
                  </th>
                  <th scope="col" className="px-3 py-2 text-left font-medium">
                    {t('access.delete.position', 'Должность')}
                  </th>
                </tr>
              </thead>
              <tbody>
                {holders.map((holder) => (
                  <tr key={`${holder.source}-${holder.company}-${holder.user_id}`} className="border-t">
                    <td className="px-3 py-2">
                      {holder.full_name}
                      {holder.source === 'personal' && (
                        // Личное назначение снимают у человека, должностное — у
                        // должности: пометка говорит, куда идти.
                        <Badge variant="outline" className="ml-2 text-[10px]">
                          {t('access.delete.personal', 'лично')}
                        </Badge>
                      )}
                    </td>
                    <td className="px-3 py-2 font-mono text-xs">{holder.company}</td>
                    <td className="px-3 py-2">{holder.department ?? '—'}</td>
                    <td className="px-3 py-2">{holder.position ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="flex items-center gap-2 py-4 text-sm text-muted-foreground">
            <Users className="h-4 w-4" />
            {t('access.delete.nobody', 'Роль никому не выдана')}
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t('common.cancel', 'Отмена')}
          </Button>
          <Button
            variant="destructive"
            disabled={!free || isDeleting || role === null}
            onClick={() => role && onConfirm(role)}
          >
            {t('access.delete.confirm', 'Удалить')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default DeleteRoleDialog;
