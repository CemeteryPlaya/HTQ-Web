/**
 * Записи KPI с отбором ячейки отчёта R-01: отчётные фильтры плюс `buyer_id`,
 * `status`, `own_document` ячейки. Строка ведёт в карточку записи.
 * Сервер отдаёт не больше 200 записей за раз; если их больше, это сказано
 * в заголовке («Показаны первые 200 из N»).
 */
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

import { Skeleton } from '@/components/ui/skeleton';
import {
  Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle,
} from '@/components/ui/sheet';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { errorDetail } from '@/lib/apiError';

import { StatusBadge } from '../core/StatusBadge';
import { formatMoney } from '../format';

import {
  filterParams, kpiApi, kpiKeys, kpiRecordHref, type KpiFilters, type RecordsSelection,
} from './api';

const KZT = 'KZT';
const PAGE = 200;

interface Props {
  filters: KpiFilters;
  selection: RecordsSelection;
  onClose: () => void;
}

export function KpiRecordsDrawer({ filters, selection, onClose }: Props) {
  const { t } = useTranslation();
  const params: Record<string, string> = { ...filterParams(filters), limit: String(PAGE) };
  if (selection.buyer_id) params.buyer_id = selection.buyer_id;
  if (selection.status) params.status = selection.status;
  if (selection.own_document) params.own_document = selection.own_document;

  const records = useQuery({
    queryKey: kpiKeys.records(params),
    queryFn: () => kpiApi.records(params),
    staleTime: 0,
    retry: false,
  });
  const items = records.data?.items ?? [];

  return (
    <Sheet open onOpenChange={(open) => { if (!open) onClose(); }}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-4xl">
        <SheetHeader>
          <SheetTitle>{selection.title}</SheetTitle>
          <SheetDescription>
            {!records.data
              ? t('bpp.kpi.records', 'Записи KPI')
              : records.data.total > items.length
                ? t('bpp.kpi.recordsTruncated', 'Показаны первые {{shown}} из {{n}} — сузьте фильтры', {
                  shown: items.length, n: records.data.total,
                })
                : t('bpp.kpi.recordsTotal', 'Записей: {{n}}', { n: records.data.total })}
          </SheetDescription>
        </SheetHeader>
        {records.isLoading && <Skeleton className="mt-4 h-24 w-full" />}
        {records.isError && (
          <p role="alert" className="mt-4 text-sm text-destructive">
            {errorDetail(records.error) ?? t('bpp.kpi.recordsFailed', 'Не удалось загрузить записи')}
          </p>
        )}
        {records.isSuccess && items.length === 0 && (
          <p className="mt-4 text-sm text-muted-foreground">{t('bpp.kpi.recordsEmpty', 'Записей нет')}</p>
        )}
        {items.length > 0 && (
          <Table className="mt-4">
            <TableHeader>
              <TableRow>
                <TableHead>{t('bpp.kpi.rec.offer', 'Альтернатива')}</TableHead>
                <TableHead>{t('bpp.kpi.rec.buyer', 'Покупатель')}</TableHead>
                <TableHead>{t('bpp.kpi.rec.source', 'Исходный документ')}</TableHead>
                <TableHead className="text-right">{t('bpp.kpi.rec.result', 'Новый документ, KZT')}</TableHead>
                <TableHead className="text-right">{t('bpp.kpi.rec.saving', 'Экономия, KZT')}</TableHead>
                <TableHead>{t('bpp.kpi.rec.status', 'Статус')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((item) => (
                <TableRow key={item.id} data-record={item.id}>
                  <TableCell>
                    <Link className="text-primary hover:underline" to={kpiRecordHref(item.id)}>
                      {item.offer_number}
                    </Link>
                  </TableCell>
                  <TableCell>{item.buyer_name}</TableCell>
                  <TableCell>{item.source_number}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {item.result_amount_kzt === null ? '—' : formatMoney(item.result_amount_kzt, KZT)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {item.saving_amount === null ? '—' : formatMoney(item.saving_amount, KZT)}
                  </TableCell>
                  <TableCell><StatusBadge kind="kpi_record" status={item.status} /></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </SheetContent>
    </Sheet>
  );
}
