/**
 * «Новый контрагент» (ТЗ §18; F-формы справочников §05 п.9). Создавать
 * вправе держатели `bpp.counterparties` `create` — ФД, БУХ, СН и ПМ; без
 * права экран не рисует форму, которую сервер всё равно отвергнет (403).
 */
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';

import { usePermissions } from '@/hooks/usePermissions';

import { COUNTERPARTIES_BASE, counterpartyHref, counterpartyKey } from './api';
import { CounterpartyForm } from './CounterpartyForm';

export function CounterpartyCreatePage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const permissions = usePermissions();

  const back = (
    <Link to={COUNTERPARTIES_BASE} className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
      <ArrowLeft className="h-4 w-4" />
      {t('bpp.counterparties.backToList', 'К списку контрагентов')}
    </Link>
  );

  if (!permissions.can('bpp.counterparties', 'create')) {
    return (
      <div className="space-y-4">
        {back}
        <p className="rounded-2xl border bg-card p-8 text-center text-sm text-muted-foreground">
          {t('bpp.counterparties.noCreate', 'У вашей роли нет права заводить контрагентов.')}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {back}
      <h2 className="text-2xl font-bold tracking-tight">
        {t('bpp.counterparties.newTitle', 'Новый контрагент')}
      </h2>
      <div className="rounded-2xl border bg-card p-4 sm:p-6">
        <CounterpartyForm
          onSaved={(card) => {
            queryClient.setQueryData(counterpartyKey(card.id), card);
            void queryClient.invalidateQueries({ queryKey: ['bpp', 'registry', 'counterparties'] });
            navigate(counterpartyHref(card.id), { replace: true });
          }}
          onCancel={() => navigate(COUNTERPARTIES_BASE)}
        />
      </div>
    </div>
  );
}

export default CounterpartyCreatePage;
