import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import { companiesApi } from '@/api/companies';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { reportApiError } from '@/lib/apiError';

export function CompanyMembersPanel({ slug, canEdit, canRevoke }: { slug: string; canEdit: boolean; canRevoke: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [userId, setUserId] = useState('');
  const key = ['companies', slug, 'memberships'];
  const query = useQuery({ queryKey: key, queryFn: async () => (await companiesApi.memberships(slug)).data });
  const invalidate = () => queryClient.invalidateQueries({ queryKey: key });

  const grant = useMutation({
    mutationFn: (id: number) => companiesApi.grantMembership(slug, { user_id: id, is_default: false }),
    onSuccess: () => { setUserId(''); invalidate(); },
    onError: (e) => reportApiError(e, t('companies.members.grantFailed', 'Не удалось выдать членство')),
  });
  const revoke = useMutation({
    mutationFn: (id: number) => companiesApi.revokeMembership(slug, id),
    onSuccess: invalidate,
    onError: (e) => reportApiError(e, t('companies.members.revokeFailed', 'Не удалось снять членство')),
  });

  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">
        {t('companies.members.hint', 'Членство — право войти в компанию (токен получает claim company). Права внутри компании выдают роли должности и личные назначения.')}
      </p>
      <ul className="divide-y rounded-lg border">
        {(query.data ?? []).map((m) => (
          <li key={m.user_id} className="flex items-center gap-3 px-3 py-2 text-sm">
            <span className="font-mono">{m.username || `#${m.user_id}`}</span>
            <span className="text-muted-foreground">{m.full_name}</span>
            {m.is_default && <span className="text-xs text-muted-foreground">{t('companies.members.default', 'по умолчанию')}</span>}
            {!m.is_active && <span className="text-xs text-destructive">{t('companies.members.inactive', 'учётка неактивна')}</span>}
            {canRevoke && (
              <Button size="sm" variant="ghost" className="ml-auto" onClick={() => revoke.mutate(m.user_id)} disabled={revoke.isPending}>
                {t('companies.members.revoke', 'Снять')}
              </Button>
            )}
          </li>
        ))}
      </ul>
      {canEdit && (
        <form className="flex items-end gap-2" onSubmit={(e) => { e.preventDefault(); const id = Number(userId); if (id > 0) grant.mutate(id); }}>
          <div>
            <Label htmlFor="cm-user">{t('companies.members.userId', 'id пользователя')}</Label>
            <Input id="cm-user" inputMode="numeric" value={userId} onChange={(e) => setUserId(e.target.value.replace(/\D/g, ''))} className="w-40" />
          </div>
          <Button type="submit" size="sm" disabled={!userId || grant.isPending}>{t('companies.members.grant', 'Выдать')}</Button>
        </form>
      )}
    </div>
  );
}
