/**
 * «Мои согласования» раздела «Закупки и оплаты» (ТЗ §05 п.3, L-03; D-34).
 *
 * Своей очереди у модуля нет: согласует единый движок `apps.signoff`, и его
 * очередь «Ждёт меня» — единственный источник правды о том, что ждёт решения
 * этого человека. Экран показывает из неё только документы модуля
 * (`subject_type` вида `bpp.*`); решение принимается в карточке процесса
 * signoff, куда ведёт строка, — там и документ, и кнопки.
 *
 * Очередь — по всем компаниям человека (`signoffApi.inboxAll`, B8.1):
 * директора в штате холдинга, а документы дочерних согласуются в их схемах.
 * Документ другой компании открывается там или решается прямо отсюда, если
 * маршрут это разрешает (`InboxRowActions`).
 *
 * Ключ запроса — тот же, что у общей очереди (`['signoff', 'inbox', 'all']`):
 * решение в карточке процесса сбрасывает этот кеш, и оба списка обновляются
 * вместе.
 */
import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import { signoffApi } from '@/api/signoff';
import { InboxCompany, InboxRowActions } from '@/components/signoff/InboxRowActions';
import { isForeign } from '@/components/signoff/crossCompany';
import { SubjectLink } from '@/components/signoff/SubjectLink';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import type { InboxAllItem } from '@/types/signoff';

import { formatDateTime } from '../format';

/** Документ модуля БЗО — тип предмета signoff с префиксом `bpp.`. */
const isBppSubject = (item: Pick<InboxAllItem, 'subject_type'>): boolean =>
  item.subject_type.startsWith('bpp.');

export default function MyApprovalsPage() {
  const { t } = useTranslation();
  const { data = [], isLoading, isError } = useQuery({
    queryKey: ['signoff', 'inbox', 'all'],
    queryFn: () => signoffApi.inboxAll().then((r) => r.data),
  });
  const items = useMemo(() => data.filter(isBppSubject), [data]);
  const showCompany = items.some(isForeign);

  return (
    <section className="space-y-4">
      <div className="flex items-center gap-3">
        <div>
          <h2 className="text-2xl font-bold">{t('bpp.approvals.title', 'Мои согласования')}</h2>
          <p className="text-sm text-muted-foreground">
            {t('bpp.approvals.subtitle', 'Документы закупок и оплат, которые ждут вашего решения')}
          </p>
        </div>
        {items.length > 0 && (
          <Badge className="ml-auto text-base px-3 py-1">{items.length}</Badge>
        )}
      </div>

      <div className="bg-card rounded-lg border overflow-x-auto">
        {isLoading ? (
          <div className="p-6 space-y-3">
            {[0, 1, 2].map((row) => <Skeleton key={row} className="h-10 w-full" />)}
          </div>
        ) : isError ? (
          <p className="p-6 text-sm text-destructive">
            {t('bpp.approvals.loadError', 'Не удалось загрузить очередь согласований')}
          </p>
        ) : items.length === 0 ? (
          <p className="p-10 text-center text-muted-foreground">
            {t('bpp.approvals.empty', 'Нет документов, ожидающих вашего решения')}
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t('bpp.approvals.document', 'Документ')}</TableHead>
                {showCompany && <TableHead>{t('bpp.approvals.company', 'Компания')}</TableHead>}
                <TableHead>{t('bpp.approvals.stage', 'Этап')}</TableHead>
                <TableHead>{t('bpp.approvals.received', 'Поступил')}</TableHead>
                <TableHead className="text-right" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((item) => (
                <TableRow key={`${item.company?.slug ?? ''}:${item.task_id}`}>
                  <TableCell>
                    {isForeign(item) ? (
                      <span className="font-medium">
                        {item.subject_title ?? `${item.subject_type} #${item.subject_id}`}
                      </span>
                    ) : (
                      <SubjectLink
                        title={item.subject_title}
                        url={item.subject_url}
                        subjectType={item.subject_type}
                        subjectId={item.subject_id}
                        processId={item.process_id}
                      />
                    )}
                  </TableCell>
                  {showCompany && (
                    <TableCell><InboxCompany item={item} /></TableCell>
                  )}
                  <TableCell>
                    <div>{item.stage_name}</div>
                    {item.stage_count > 1 && (
                      <div className="text-xs text-muted-foreground">
                        {t('bpp.approvals.stepOf', 'Этап {{n}} из {{total}}', {
                          n: item.stage_order,
                          total: item.stage_count,
                        })}
                      </div>
                    )}
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground whitespace-nowrap">
                    {formatDateTime(item.created_at)}
                  </TableCell>
                  <TableCell>
                    <div className="flex justify-end">
                      <InboxRowActions item={item} openLabel={t('bpp.approvals.open', 'Открыть')} />
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>
    </section>
  );
}
