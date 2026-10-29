/**
 * Реестр тендеров (`/tender/tenders`, T2.3; план §4.3): свои тендеры, с
 * узлом `tender.tenders.all` — все (выборку режет сервер). Тендер
 * объявляется с карточки утверждённой заявки, отдельной кнопки здесь нет.
 */
import { useDeferredValue, useState } from 'react';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Search } from 'lucide-react';

import { Input } from '@/components/ui/input';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { formatDateTime } from '@/features/bpp/format';

import { TenderStatusBadge } from '../core/TenderStatusBadge';
import { TENDER_STATUSES } from '../core/statuses';
import { tenderRequestHref } from '../requests/api';
import { tenderHref, tenderKeys, tendersApi } from './api';

const ALL = '__all__';

export function TendersPage() {
  const { t } = useTranslation();
  const [status, setStatus] = useState('');
  const [search, setSearch] = useState('');
  const q = useDeferredValue(search.trim());
  const params = { status, q };

  const { data, isLoading, isError } = useQuery({
    queryKey: tenderKeys.list(params),
    queryFn: () => tendersApi.list(params),
    placeholderData: keepPreviousData,
  });

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold">{t('tender.tenders.title', 'Тендеры')}</h2>

      <div className="flex flex-wrap gap-2">
        <div className="relative min-w-64 flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            type="search" className="pl-8" value={search}
            placeholder={t('tender.tenders.searchHint', 'Номер тендера или заявки')}
            aria-label={t('tender.tenders.search', 'Поиск')}
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>
        <Select value={status || ALL} onValueChange={(value) => setStatus(value === ALL ? '' : value)}>
          <SelectTrigger className="w-56" aria-label={t('tender.tenders.status', 'Статус')}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>{t('tender.tenders.allStatuses', 'Все статусы')}</SelectItem>
            {Object.entries(TENDER_STATUSES).map(([code, def]) => (
              <SelectItem key={code} value={code}>{t(def.labelKey, def.label)}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {isLoading ? (
        <Skeleton className="h-40 w-full" />
      ) : isError ? (
        <p className="text-sm text-destructive">{t('tender.tenders.listFailed', 'Не удалось загрузить тендеры.')}</p>
      ) : (data ?? []).length === 0 ? (
        <div className="rounded-2xl border bg-card p-10 text-center text-sm text-muted-foreground">
          {t('tender.tenders.empty',
            'Тендеров пока нет. Тендер объявляется с карточки утверждённой заявки — кнопкой «Объявить тендер».')}
        </div>
      ) : (
        <div className="overflow-x-auto rounded-2xl border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t('tender.tenders.number', 'Номер')}</TableHead>
                <TableHead>{t('tender.tenders.request', 'Заявка')}</TableHead>
                <TableHead>{t('tender.tenders.deadline', 'Срок приёма предложений')}</TableHead>
                <TableHead title={t('tender.tenders.countersHint', 'Отправлено / открыто / подано')}>
                  {t('tender.tenders.counters', 'Участники')}
                </TableHead>
                <TableHead>{t('tender.tenders.status', 'Статус')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(data ?? []).map((row) => (
                <TableRow key={row.id}>
                  <TableCell className="font-medium">
                    <Link to={tenderHref(row.id)} className="text-primary hover:underline">{row.number}</Link>
                  </TableCell>
                  <TableCell>
                    <Link to={tenderRequestHref(row.request_id)} className="hover:underline">{row.request_number}</Link>
                  </TableCell>
                  <TableCell>{formatDateTime(row.deadline_at)}</TableCell>
                  <TableCell>
                    {row.counters ? `${row.counters.sent} / ${row.counters.opened} / ${row.counters.submitted}` : '—'}
                  </TableCell>
                  <TableCell><TenderStatusBadge kind="tender" status={row.status} /></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}

export default TendersPage;
