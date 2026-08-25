import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import {
  fetchIdentityApprover,
  fetchIdentityRequests,
  setIdentityApprover,
  type IdentityRequestStatus,
} from '@/api/identity';
import { fetchEmployeeUsers } from '@/api/hr';
import HRLayout from '@/components/hr/HRLayout';
import { IdentityRequestDialog } from '@/components/hr/IdentityRequestDialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useHRLevel } from '@/hooks/useHRLevel';
import { errorDetail } from '@/lib/apiError';

const STATUS_LABEL: Record<IdentityRequestStatus | 'all', string> = {
  pending: 'Ожидают',
  applied: 'Применённые',
  rejected: 'Отклонённые',
  all: 'Все',
};

/**
 * Очередь заявок на изменение данных аккаунта.
 *
 * Владелец идентичности — аккаунт, поэтому кадровая правка попадает сюда, а не
 * в карточку сотрудника: применить её может только подтверждающий.
 */
const HRIdentityRequests = () => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { hasPerm } = useHRLevel();
  const canManageApprover = hasPerm('hr.identity.manage');

  const [status, setStatus] = useState<IdentityRequestStatus | 'all'>('pending');
  const [openId, setOpenId] = useState<number | null>(null);

  const { data: requests, isLoading } = useQuery({
    queryKey: ['identity-requests', status],
    queryFn: () => fetchIdentityRequests(status),
  });

  const { data: approver } = useQuery({
    queryKey: ['identity-approver'],
    queryFn: fetchIdentityApprover,
  });

  const { data: users } = useQuery({
    queryKey: ['hr-employee-users'],
    queryFn: () => fetchEmployeeUsers(),
    enabled: canManageApprover,
  });

  const changeApprover = useMutation({
    mutationFn: (userId: number | null) => setIdentityApprover(userId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['identity-approver'] }),
    onError: (err: unknown) => toast.error(
      errorDetail(err) ?? t('hr.pages.identity.approverError', 'Не удалось назначить подтверждающего'),
    ),
  });

  return (
    <HRLayout
      title={t('hr.pages.identity.title', 'Заявки на изменение профиля')}
      subtitle={t(
        'hr.pages.identity.subtitle',
        'Данные аккаунта меняет его владелец; кадровая правка применяется после подтверждения',
      )}
    >
      <div className="mb-4 flex flex-wrap items-end gap-4">
        <div className="grid gap-1">
          <span className="text-xs text-muted-foreground">
            {t('hr.pages.identity.statusFilter', 'Статус')}
          </span>
          <Select value={status} onValueChange={(v) => setStatus(v as IdentityRequestStatus | 'all')}>
            <SelectTrigger className="w-48">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(['pending', 'applied', 'rejected', 'all'] as const).map((key) => (
                <SelectItem key={key} value={key}>{STATUS_LABEL[key]}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {canManageApprover && (
          <div className="grid gap-1">
            <span className="text-xs text-muted-foreground">
              {t('hr.pages.identity.approver', 'Кто подтверждает')}
            </span>
            <Select
              value={approver?.user_id ? String(approver.user_id) : 'none'}
              onValueChange={(v) => changeApprover.mutate(v === 'none' ? null : Number(v))}
            >
              <SelectTrigger className="w-72">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {/* Пустое назначение — не «подтверждать некому»: тогда решает
                    руководитель отдела сотрудника. */}
                <SelectItem value="none">
                  {t('hr.pages.identity.approverDefault', 'Руководитель отдела сотрудника')}
                </SelectItem>
                {(users ?? []).map((u) => (
                  <SelectItem key={u.id} value={String(u.id)}>
                    {u.full_name} ({u.email})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}
      </div>

      <div className="border rounded-lg overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t('hr.pages.identity.fields.employee', 'Сотрудник')}</TableHead>
              <TableHead>{t('hr.pages.identity.fields.source', 'Источник')}</TableHead>
              <TableHead>{t('hr.pages.identity.fields.status', 'Статус')}</TableHead>
              <TableHead>{t('hr.pages.identity.fields.created', 'Создана')}</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading && (
              <TableRow>
                <TableCell colSpan={5}>{t('hr.common.loading')}</TableCell>
              </TableRow>
            )}
            {!isLoading && (requests ?? []).length === 0 && (
              <TableRow>
                <TableCell colSpan={5} className="text-muted-foreground">
                  {t('hr.pages.identity.empty', 'Заявок нет')}
                </TableCell>
              </TableRow>
            )}
            {(requests ?? []).map((row) => (
              <TableRow key={row.id}>
                <TableCell>{row.employee_name}</TableCell>
                <TableCell>
                  {row.source === 'nightly' ? (
                    <Badge variant="outline">
                      {t('hr.pages.identity.sourceNightly', 'Ночная сверка')}
                    </Badge>
                  ) : (
                    <Badge variant="secondary">
                      {t('hr.pages.identity.sourceHr', 'Правка в карточке')}
                    </Badge>
                  )}
                </TableCell>
                <TableCell>{STATUS_LABEL[row.status]}</TableCell>
                <TableCell>{new Date(row.created_at).toLocaleString()}</TableCell>
                <TableCell className="text-right">
                  <Button size="sm" variant="outline" onClick={() => setOpenId(row.id)}>
                    {row.status === 'pending'
                      ? t('hr.pages.identity.open', 'Рассмотреть')
                      : t('hr.pages.identity.view', 'Посмотреть')}
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <IdentityRequestDialog
        requestId={openId}
        onOpenChange={(open) => !open && setOpenId(null)}
      />
    </HRLayout>
  );
};

export default HRIdentityRequests;
