import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import { companiesApi } from '@/api/companies';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { reportApiError } from '@/lib/apiError';

/** То же множество, что backend `Level`/`AccessLevel` — 'none' сюда не
 * попадает, апи его уже отфильтровало (`permissions_for` не отдаёт нулевые). */
const LEVEL_LABELS: Record<string, string> = { read: 'чтение', write: 'запись', admin: 'администрирование' };

export function CompanyMembersPanel({ slug, canEdit, canRevoke, showExternalHolders }: {
  slug: string; canEdit: boolean; canRevoke: boolean; showExternalHolders: boolean;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [userId, setUserId] = useState('');
  const key = ['companies', slug, 'memberships'];
  const query = useQuery({ queryKey: key, queryFn: async () => (await companiesApi.memberships(slug)).data });
  const invalidate = () => queryClient.invalidateQueries({ queryKey: key });

  const externalHoldersQuery = useQuery({
    queryKey: ['companies', slug, 'external-holders'],
    queryFn: async () => (await companiesApi.externalHolders(slug)).data,
    enabled: showExternalHolders,
  });

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

      {showExternalHolders && (
        <div className="space-y-2 border-t pt-3">
          <h3 className="text-sm font-medium">{t('companies.members.externalHoldersTitle', 'Из холдинга')}</h3>
          <p className="text-xs text-muted-foreground">
            {t('companies.members.externalHoldersHint',
              'Сотрудники вышестоящих компаний, чьи должности несут им права здесь.')}
          </p>
          <ul className="divide-y rounded-lg border">
            {(externalHoldersQuery.data ?? []).map((holder) => (
              // у держателя нет id — состав (компания, ФИО, должность) и есть его ключ
              <li key={`${holder.home_company}:${holder.full_name}:${holder.position}`}
                className="space-y-1 px-3 py-2 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{holder.full_name}</span>
                  <span className="text-muted-foreground">{holder.home_company}</span>
                  <span className="text-xs text-muted-foreground">{holder.position}</span>
                </div>
                <div className="flex flex-wrap gap-1">
                  {holder.modules.map((m) => (
                    <Badge key={m.module} variant="outline" className="text-xs">
                      {m.module}: {LEVEL_LABELS[m.level] ?? m.level}
                    </Badge>
                  ))}
                </div>
              </li>
            ))}
            {externalHoldersQuery.data?.length === 0 && (
              <li className="px-3 py-2 text-sm text-muted-foreground">
                {t('companies.members.externalHoldersEmpty', 'Никто из холдинга правами здесь не пользуется.')}
              </li>
            )}
          </ul>
        </div>
      )}

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
