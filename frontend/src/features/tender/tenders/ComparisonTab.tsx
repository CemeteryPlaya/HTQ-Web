/**
 * Вкладка «Сравнение» карточки тендера (TND-020, TND-021; спека этапа 5,
 * §3 T5.1). Появляется после вскрытия — до него сервер отвечает 409
 * `E-TND-07`, и вкладки нет вовсе.
 *
 * - Поставщики — колонками; сводка: валюта и курс на дату вскрытия, НДС,
 *   срок действия (истёк — пометка), схема оплаты, покрытие «N из M»,
 *   итоги «по общему набору» и «полный» в KZT, экономия к плану, файлы КП.
 * - Позиции — строками; самый дешёвый по цене за единицу в KZT
 *   подсвечен; пометки «аналог» и «N из M ед.» (частичное количество).
 * - Доставка и СМР — отдельными строками («в цене» — пометкой).
 * - Нет курса — суммы в KZT пусты, предупреждение называет поставщика.
 * - «Экспорт в xlsx» — тот же набор (TND-021).
 */
import { useState, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Download, Loader2 } from 'lucide-react';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { ComparisonGrid } from '@/features/bpp/core/ComparisonGrid';
import { formatDate, formatMoney } from '@/features/bpp/format';
import { reportApiError } from '@/lib/apiError';

import { tenderKeys, tendersApi } from './api';
import type {
  Comparison, ComparisonExtra, ComparisonItem, ComparisonSupplier,
} from './comparison';
import { describeScheme } from './schemes';

const money = (value: string | null | undefined, currency?: string) =>
  (value === null || value === undefined || value === '' ? '—' : formatMoney(value, currency));

type Row =
  | { type: 'item'; item: ComparisonItem }
  | { type: 'extra'; extra: ComparisonExtra };

interface Props {
  tenderId: string;
  tenderNumber: string;
}

export function ComparisonTab({ tenderId, tenderNumber }: Props) {
  const { t } = useTranslation();
  const [exporting, setExporting] = useState(false);
  const { data, isLoading, error } = useQuery({
    queryKey: tenderKeys.comparison(tenderId),
    queryFn: () => tendersApi.comparison(tenderId),
  });

  if (isLoading) return <Skeleton className="h-48 w-full" />;
  if (error || !data) {
    return (
      <p className="text-sm text-muted-foreground">
        {t('tender.comparison.loadFailed', 'Не удалось загрузить сравнение.')}
      </p>
    );
  }

  const exportXlsx = async () => {
    setExporting(true);
    try {
      await tendersApi.exportComparison(tenderId, `${tenderNumber}-comparison`);
    } catch (failure) {
      reportApiError(failure, t('tender.comparison.exportFailed', 'Не удалось выгрузить сравнение'));
    } finally {
      setExporting(false);
    }
  };

  const openFile = async (supplier: ComparisonSupplier, documentId: string) => {
    // Вкладку открываем сразу — иначе браузер сочтёт её всплывающим окном.
    const tab = window.open('', '_blank');
    if (tab) tab.opener = null;
    try {
      const url = await tendersApi.offerFileLink(tenderId, supplier.offer_id, documentId);
      if (tab) tab.location.href = url;
      else window.location.assign(url);
    } catch (failure) {
      tab?.close();
      reportApiError(failure, t('tender.comparison.fileFailed', 'Не удалось открыть файл'));
    }
  };

  return (
    <section className="space-y-4" data-testid="tender-comparison">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">
          {t('tender.comparison.rateDate', 'Курс НБРК на {{date}}; суммы — к оплате.', {
            date: formatDate(data.rate_date),
          })}
        </p>
        <Button type="button" variant="outline" disabled={exporting} onClick={() => { void exportXlsx(); }}>
          {exporting ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <Download className="mr-1.5 h-4 w-4" />}
          {t('tender.comparison.export', 'Экспорт в xlsx')}
        </Button>
      </div>

      <Warnings data={data} />

      {data.suppliers.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {t('tender.comparison.noOffers', 'Предложений не подано.')}
        </p>
      ) : (
        <div className="space-y-4 overflow-x-auto rounded-2xl border bg-card p-2">
          <SummaryGrid data={data} onOpenFile={(supplier, id) => { void openFile(supplier, id); }} />
          <ItemsGrid data={data} />
        </div>
      )}

      {data.totals.declined.length > 0 && (
        <div className="space-y-1">
          <h4 className="text-sm font-semibold">{t('tender.comparison.declined', 'Отказались участвовать')}</h4>
          <ul className="list-disc pl-5 text-sm">
            {data.totals.declined.map((row) => (
              <li key={row.invitation_id}>
                {row.name}{row.reason ? ` — ${row.reason}` : ''}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function Warnings({ data }: { data: Comparison }) {
  const { t } = useTranslation();
  const name = new Map(data.suppliers.map((row) => [row.invitation_id, row.name]));
  if (data.warnings.length === 0) return null;
  return (
    <Alert data-testid="comparison-warnings">
      <AlertDescription>
        <ul className="space-y-0.5 text-sm">
          {data.warnings.map((warning) => (
            <li key={`${warning.code}:${warning.invitation_id}`}>
              {warning.code === 'no_rate'
                ? t('tender.comparison.noRate',
                  '{{name}}: нет курса {{currency}} на дату вскрытия — суммы в тенге не посчитаны.',
                  { name: name.get(warning.invitation_id) ?? '', currency: warning.currency_code })
                : t('tender.comparison.validExpired', '{{name}}: срок действия предложения истёк {{date}}.',
                  { name: name.get(warning.invitation_id) ?? '', date: formatDate(warning.valid_until) })}
            </li>
          ))}
        </ul>
      </AlertDescription>
    </Alert>
  );
}

interface SummaryRow {
  key: string;
  label: string;
  cell: (supplier: ComparisonSupplier) => ReactNode;
}

function SummaryGrid({ data, onOpenFile }: {
  data: Comparison;
  onOpenFile: (supplier: ComparisonSupplier, documentId: string) => void;
}) {
  const { t } = useTranslation();
  const translate = (key: string, fallback: string, options?: Record<string, unknown>) => t(key, fallback, options);
  const rows: SummaryRow[] = [
    { key: 'currency', label: t('tender.comparison.currency', 'Валюта и курс'),
      cell: (s) => (s.currency_code === 'KZT' ? 'KZT'
        : `${s.currency_code} · ${s.rate ? formatMoney(s.rate) : t('tender.comparison.noRateShort', 'нет курса')}`) },
    { key: 'vat', label: t('tender.comparison.vat', 'НДС'),
      cell: (s) => (s.with_vat ? `${s.vat_rate ?? ''} %` : t('tender.comparison.noVat', 'без НДС')) },
    { key: 'valid', label: t('tender.comparison.validUntil', 'Действует до'),
      cell: (s) => (
        <span className={s.valid_expired ? 'text-destructive' : undefined}>
          {formatDate(s.valid_until)}
          {s.valid_expired && ` · ${t('tender.comparison.expired', 'срок истёк')}`}
        </span>
      ) },
    { key: 'scheme', label: t('tender.comparison.scheme', 'Схема оплаты'),
      cell: (s) => describeScheme(s.payment_scheme, translate) },
    { key: 'coverage', label: t('tender.comparison.coverage', 'Покрытие позиций'),
      cell: (s) => t('tender.comparison.coverageValue', '{{offered}} из {{total}}', s.coverage) },
    { key: 'common', label: t('tender.comparison.totalCommon', 'Итого по общему набору, KZT'),
      cell: (s) => money(s.total_common_kzt) },
    { key: 'full', label: t('tender.comparison.totalFull', 'Итого полное, KZT'),
      cell: (s) => money(s.total_full_kzt) },
    { key: 'saving', label: t('tender.comparison.saving', 'Экономия к плану, KZT'),
      cell: (s) => {
        if (!s.saving_common_kzt) return '—';
        const dearer = s.saving_common_kzt.trim().startsWith('-');
        return (
          <span className={dearer ? 'text-amber-700 dark:text-amber-400' : undefined}>
            {dearer
              ? t('tender.comparison.dearer', 'Дороже на {{amount}}', { amount: formatMoney(s.saving_common_kzt.trim().slice(1)) })
              : formatMoney(s.saving_common_kzt)}
          </span>
        );
      } },
    { key: 'files', label: t('tender.comparison.files', 'КП и документы'),
      cell: (s) => (s.files.length === 0 ? '—' : (
        <ul className="space-y-0.5">
          {s.files.map((file) => (
            <li key={file.id}>
              <button type="button" className="text-left text-primary hover:underline" onClick={() => onOpenFile(s, file.id)}>
                {file.name}
              </button>
            </li>
          ))}
        </ul>
      )) },
    { key: 'terms', label: t('tender.comparison.extraTerms', 'Доп. условия'),
      cell: (s) => <span className="whitespace-pre-wrap">{s.extra_terms || '—'}</span> },
  ];
  return (
    <ComparisonGrid
      testId="comparison-summary"
      columns={data.suppliers}
      columnKey={(s) => s.invitation_id}
      renderColumn={(s) => (
        <>
          <span className="font-semibold text-foreground">{s.name}</span>
          {s.offer_number && <span className="block text-xs font-normal text-muted-foreground">{s.offer_number}</span>}
        </>
      )}
      rows={rows}
      rowKey={(row) => row.key}
      renderRow={(row) => row.label}
      cell={(row, s) => row.cell(s)}
    />
  );
}

function ItemsGrid({ data }: { data: Comparison }) {
  const { t } = useTranslation();
  const rows: Row[] = [
    ...data.items.map((item): Row => ({ type: 'item', item })),
    ...data.extras.map((extra): Row => ({ type: 'extra', extra })),
  ];
  const extraLabel = (kind: string) => (kind === 'delivery'
    ? t('tender.comparison.delivery', 'Доставка')
    : t('tender.comparison.works', 'СМР'));
  return (
    <ComparisonGrid
      testId="comparison-items"
      columns={data.suppliers}
      columnKey={(s) => s.invitation_id}
      renderColumn={(s) => s.name}
      rowHeader={t('tender.comparison.item', 'Позиция')}
      rows={rows}
      rowKey={(row) => (row.type === 'item' ? row.item.item_id : `extra:${row.extra.kind}`)}
      renderRow={(row) => (row.type === 'item' ? (
        <span className="block max-w-xs whitespace-normal">
          {row.item.line_no}. {row.item.name}
          {!row.item.in_common_set && (
            <span className="block text-xs text-muted-foreground">
              {t('tender.comparison.notCommon', 'не все предложили')}
            </span>
          )}
        </span>
      ) : extraLabel(row.extra.kind))}
      leading={[
        { key: 'qty', className: 'text-right whitespace-nowrap', header: t('tender.comparison.qty', 'Кол-во'),
          cell: (row: Row) => (row.type === 'item' ? `${row.item.qty} ${row.item.uom.short_name}` : '') },
        { key: 'plan', className: 'text-right whitespace-nowrap', header: t('tender.comparison.plan', 'План, KZT'),
          cell: (row: Row) => (row.type === 'item' ? money(row.item.plan_amount) : money(row.extra.plan_amount)) },
      ]}
      highlight={(row, s) => {
        const best = row.type === 'item' ? row.item.cheapest_invitation_id : row.extra.cheapest_invitation_id;
        return best === s.invitation_id ? 'cheapest' : null;
      }}
      cell={(row, s) => (row.type === 'item'
        ? <ItemCell item={row.item} supplier={s} />
        : <ExtraCell extra={row.extra} supplier={s} />)}
    />
  );
}

function ItemCell({ item, supplier }: { item: ComparisonItem; supplier: ComparisonSupplier }) {
  const { t } = useTranslation();
  const cell = item.offers[supplier.invitation_id];
  if (!cell?.participates) {
    return <span className="text-muted-foreground">{t('tender.comparison.notOffered', 'не предложено')}</span>;
  }
  return (
    <div className="space-y-0.5 text-right">
      <div>{money(cell.price, supplier.currency_code)}</div>
      <div className="text-xs text-muted-foreground">
        {t('tender.comparison.amount', 'сумма')} {money(cell.amount)}
        {supplier.currency_code !== 'KZT' && cell.amount_kzt && ` · ${money(cell.amount_kzt, 'KZT')}`}
      </div>
      <div className="flex flex-wrap justify-end gap-1">
        {cell.is_analog && (
          <Badge variant="outline" title={cell.analog_note || undefined}>
            {t('tender.comparison.analog', 'аналог')}
          </Badge>
        )}
        {cell.partial_qty && (
          <Badge variant="outline">
            {t('tender.comparison.partialQty', '{{qty}} из {{total}} ед.', { qty: cell.qty, total: item.qty })}
          </Badge>
        )}
      </div>
      {cell.delivery_date && (
        <div className="text-xs text-muted-foreground">
          {t('tender.comparison.deliveryDate', 'поставка {{date}}', { date: formatDate(cell.delivery_date) })}
        </div>
      )}
    </div>
  );
}

function ExtraCell({ extra, supplier }: { extra: ComparisonExtra; supplier: ComparisonSupplier }) {
  const { t } = useTranslation();
  const cell = extra.offers[supplier.invitation_id];
  if (!cell) return <span className="text-muted-foreground">{t('tender.comparison.notOffered', 'не предложено')}</span>;
  if (cell.included_in_price) return <Badge variant="outline">{t('tender.comparison.included', 'в цене')}</Badge>;
  return (
    <div className="text-right">
      {money(cell.amount, supplier.currency_code)}
      {cell.note && <span className="block text-xs text-muted-foreground">{cell.note}</span>}
    </div>
  );
}

export default ComparisonTab;
