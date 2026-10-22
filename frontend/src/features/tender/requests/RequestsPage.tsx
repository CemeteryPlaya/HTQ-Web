/**
 * Реестр заявок на тендер (`/tender/requests`, T1.4; план §3.4): свои
 * заявки, с узлом `tender.requests.all` — все (выборку режет сервер).
 * Фильтры — статус и поиск по номеру или наименованию (`q`); «Создать
 * заявку» — по узлу `tender.requests` `create`.
 */
import { useDeferredValue, useState } from 'react';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Plus, Search } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { formatDate } from '@/features/bpp/format';
import { usePermissions } from '@/hooks/usePermissions';

import { TenderStatusBadge } from '../core/TenderStatusBadge';
import { TENDER_REQUEST_STATUSES } from '../core/statuses';
import {
  TENDER_REQUESTS_BASE, tenderRequestHref, tenderRequestKeys, tenderRequestsApi,
} from './api';
import { PURCHASE_TYPE_LABELS, STATUS_FILTER } from './labels';

const ALL = '__all__';

export function RequestsPage() {
  const { t } = useTranslation();
  const permissions = usePermissions();
  const canCreate = permissions.can('tender.requests', 'create');
  const [status, setStatus] = useState('');
  const [search, setSearch] = useState('');
  const q = useDeferredValue(search.trim());
  const params = { status, q };

  const { data, isLoading, isError } = useQuery({
    queryKey: tenderRequestKeys.list(params),
    queryFn: () => tenderRequestsApi.list(params),
    // Пока идёт поиск по новому слову, строки прежнего ответа остаются на месте.
    placeholderData: keepPreviousData,
  });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-xl font-semibold">{t('tender.requests.title', 'Заявки на тендер')}</h2>
        {canCreate && (
          <Button asChild>
            <Link to={`${TENDER_REQUESTS_BASE}/new`}>
              <Plus className="mr-1.5 h-4 w-4" />
              {t('tender.requests.create', 'Создать заявку')}
            </Link>
          </Button>
        )}
      </div>

      <div className="flex flex-wrap gap-2">
        <div className="relative min-w-64 flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            type="search"
            className="pl-8"
            value={search}
            placeholder={t('tender.requests.searchHint', 'Номер или наименование позиции')}
            aria-label={t('tender.requests.search', 'Поиск')}
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>
        <Select value={status || ALL} onValueChange={(value) => setStatus(value === ALL ? '' : value)}>
          <SelectTrigger className="w-56" aria-label={t('tender.requests.status', 'Статус')}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>{t('tender.requests.allStatuses', 'Все статусы')}</SelectItem>
            {STATUS_FILTER.map((code) => (
              <SelectItem key={code} value={code}>
                {t(TENDER_REQUEST_STATUSES[code].labelKey, TENDER_REQUEST_STATUSES[code].label)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {isLoading ? (
        <Skeleton className="h-40 w-full" />
      ) : isError ? (
        <p className="text-sm text-destructive">
          {t('tender.requests.listFailed', 'Не удалось загрузить заявки.')}
        </p>
      ) : (data ?? []).length === 0 ? (
        <div className="rounded-2xl border bg-card p-10 text-center text-sm text-muted-foreground">
          {t('tender.requests.empty', 'Заявок пока нет')}
        </div>
      ) : (
        <div className="overflow-x-auto rounded-2xl border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t('tender.requests.number', 'Номер')}</TableHead>
                <TableHead>{t('tender.requests.createdAt', 'Дата')}</TableHead>
                <TableHead>{t('tender.requests.author', 'Автор')}</TableHead>
                <TableHead>{t('tender.requests.project', 'Проект')}</TableHead>
                <TableHead>{t('tender.requests.purchaseType', 'Вид закупки')}</TableHead>
                <TableHead>{t('tender.requests.needDate', 'Потребность к дате')}</TableHead>
                <TableHead>{t('tender.requests.status', 'Статус')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(data ?? []).map((row) => {
                const type = row.purchase_type ? PURCHASE_TYPE_LABELS[row.purchase_type] : undefined;
                return (
                  <TableRow key={row.id}>
                    <TableCell className="font-medium">
                      <Link to={tenderRequestHref(row.id)} className="text-primary hover:underline">
                        {row.number}
                      </Link>
                    </TableCell>
                    <TableCell>{formatDate(row.created_at ?? null)}</TableCell>
                    <TableCell>{row.author_name || '—'}</TableCell>
                    <TableCell title={row.project_name || undefined}>{row.project_code || '—'}</TableCell>
                    <TableCell>{type ? t(type.key, type.fallback) : '—'}</TableCell>
                    <TableCell>{formatDate(row.need_date ?? null)}</TableCell>
                    <TableCell><TenderStatusBadge status={row.status} /></TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}

export default RequestsPage;
