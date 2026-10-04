/**
 * Действие строки очереди «Ждёт меня» по всем компаниям (мастер-план БЗО, B8.1).
 *
 * Задача своей компании открывается, как раньше, карточкой процесса. Задача
 * другой компании (документ дочерней, этап на должности холдинга):
 *
 * - «Решить здесь» — маршрут разрешает решение из вышестоящей компании
 *   (`direct_allowed`): карточка процесса дочерней со сводкой документа
 *   открывается прямо на этом адресе;
 * - «Открыть в <компании>» — есть членство в ней (`can_enter`): переход на её
 *   адрес, к обычной карточке процесса;
 * - ни того ни другого — подсказка, почему решить нельзя: членство и права
 *   директоров в дочерних заводит администратор (A8.1).
 */
import { Link } from 'react-router-dom';
import { ArrowRight, Building2, Lock } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { switchCompany } from '@/lib/auth/companySwitch';
import type { InboxAllItem } from '@/types/signoff';
import { isForeign } from '@/components/signoff/crossCompany';

/** Компания строки — бейджем, если она не текущая. */
export function InboxCompany({ item }: { item: InboxAllItem }) {
  if (!item.company) return null;
  return isForeign(item)
    ? <Badge variant="outline" className="whitespace-nowrap">{item.company.name}</Badge>
    : <span className="text-sm text-muted-foreground">{item.company.name}</span>;
}

export function InboxRowActions({ item, openLabel }: { item: InboxAllItem; openLabel: string }) {
  const { t } = useTranslation();
  if (!isForeign(item)) {
    return (
      <Button asChild size="sm" variant="outline">
        <Link to={`/signoff/processes/${item.process_id}`}>
          {openLabel}
          <ArrowRight className="ml-1.5 h-4 w-4 opacity-70" />
        </Link>
      </Button>
    );
  }
  const company = item.company!;
  return (
    <div className="flex flex-col items-end gap-1.5">
      <div className="flex flex-wrap justify-end gap-2">
        {item.direct_allowed && (
          <Button asChild size="sm">
            <Link to={`/signoff/companies/${company.slug}/processes/${item.process_id}`}>
              {t('signoff.inbox.decideHere', 'Решить здесь')}
              <ArrowRight className="ml-1.5 h-4 w-4 opacity-70" />
            </Link>
          </Button>
        )}
        {item.can_enter && (
          <Button size="sm" variant="outline"
            onClick={() => switchCompany(company, `/signoff/processes/${item.process_id}`)}>
            <Building2 className="mr-1.5 h-4 w-4 opacity-70" />
            {t('signoff.inbox.openIn', 'Открыть в {{company}}', { company: company.name })}
          </Button>
        )}
      </div>
      {!item.direct_allowed && !item.can_enter && (
        <p className="flex max-w-xs items-start gap-1 text-right text-xs text-muted-foreground">
          <Lock className="mt-0.5 h-3 w-3 shrink-0" />
          {t('signoff.inbox.noAccess',
            'Нет доступа к компании «{{company}}» — попросите администратора выдать его.',
            { company: company.name })}
        </p>
      )}
      {!item.direct_allowed && item.direct_blocker && (
        <p className="max-w-xs text-right text-xs text-muted-foreground">{item.direct_blocker}</p>
      )}
    </div>
  );
}
