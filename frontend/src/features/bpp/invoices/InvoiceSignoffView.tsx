/**
 * Счёт на оплату внутри карточки согласования (`bpp.invoice`) — решение ФД
 * (D-12). ФД видит основание и договор с остатком, сумму в KZT и порог
 * 1000 МРП для счёта без договора, строки с планом, значок «Возможное
 * дробление» (D-17) и заблокированного контрагента. Действий нет: решение —
 * кнопки карточки процесса (или «Оплатить» на форме счёта).
 */
import type { ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { AlertTriangle } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';

import { StatusBadge } from '../core/StatusBadge';
import { formatDate, formatMoney } from '../format';
import { shownQty } from '../plan/planSelection';

import { invoiceApi, invoiceKey } from './api';

interface Props {
  id: string;
  embedded?: boolean;
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="text-sm font-medium">{children}</dd>
    </div>
  );
}

export default function InvoiceSignoffView({ id, embedded = false }: Props) {
  const { t } = useTranslation();
  const { data: card, isLoading, isError } = useQuery({
    queryKey: invoiceKey(id),
    queryFn: () => invoiceApi.get(id),
  });

  if (isLoading) return <Skeleton className="h-48 w-full" />;
  if (isError || !card) {
    return (
      <p className="text-sm text-muted-foreground">
        {t('bpp.invoices.loadFailed', 'Не удалось загрузить счёт.')}
      </p>
    );
  }
  const currency = card.currency_code;

  return (
    <div className="space-y-4">
      {!embedded && (
        <div className="flex items-center gap-2">
          <h2 className="text-xl font-semibold">{card.number}</h2>
          <StatusBadge kind="invoice" status={card.status} />
        </div>
      )}
      {(card.possible_split || card.counterparty?.status === 'blocked') && (
        <div className="flex flex-wrap gap-2">
          {card.possible_split && (
            <Badge variant="outline" className="border-amber-300 text-amber-800">
              <AlertTriangle className="mr-1 h-3 w-3" />
              {t('bpp.invoices.possibleSplit', 'Возможное дробление')}
            </Badge>
          )}
          {card.counterparty?.status === 'blocked' && (
            <Badge variant="destructive">
              {t('bpp.invoices.counterpartyBlocked', 'Контрагент заблокирован')}
            </Badge>
          )}
        </div>
      )}
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-4">
        <Row label={t('bpp.invoices.counterparty', 'Контрагент')}>
          {card.counterparty
            ? `${card.counterparty.short_name || card.counterparty.name} (${card.counterparty.reg_number})`
            : '—'}
        </Row>
        <Row label={t('bpp.invoices.extNumber', 'Счёт контрагента')}>
          № {card.ext_number || '—'} {card.ext_date ? `от ${formatDate(card.ext_date)}` : ''}
        </Row>
        <Row label={t('bpp.invoices.basis', 'Основание')}>
          {card.agreement
            ? t('bpp.invoices.byAgreement', 'Договор {{n}}', { n: card.agreement.number })
            : t('bpp.invoices.noAgreement', 'Без договора')}
        </Row>
        <Row label={t('bpp.invoices.project', 'Проект / статья')}>
          {card.project.code} / {card.article.name}
        </Row>
        <Row label={t('bpp.invoices.amount', 'Сумма счёта')}>
          {formatMoney(card.amount, currency)}
          {currency !== 'KZT' && card.amount_kzt && (
            <span className="block text-xs text-muted-foreground">
              {formatMoney(card.amount_kzt, 'KZT')} {t('bpp.invoices.byRate', 'по курсу')} {card.rate}
            </span>
          )}
        </Row>
        {card.threshold && (
          <Row label={t('bpp.invoices.threshold', 'Порог 1000 МРП')}>
            <span className={card.over_threshold ? 'text-destructive' : undefined}>
              {formatMoney(card.threshold, 'KZT')}
            </span>
          </Row>
        )}
        {card.agreement && card.agreement.remaining !== null && (
          <Row label={t('bpp.invoices.agreementRemaining', 'Остаток по договору')}>
            {formatMoney(card.agreement.remaining, currency)}
          </Row>
        )}
        <Row label={t('bpp.invoices.dueDate', 'Срок оплаты')}>{formatDate(card.due_date)}</Row>
      </dl>
      {card.author_comment && (
        <p className="rounded-md bg-muted p-2 text-sm">{card.author_comment}</p>
      )}
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-left text-xs text-muted-foreground">
            <th className="py-1">{t('bpp.invoices.item', 'Позиция')}</th>
            <th className="py-1">{t('bpp.invoices.itemName', 'Наименование')}</th>
            <th className="py-1 text-right">{t('bpp.invoices.qty', 'Кол-во')}</th>
            <th className="py-1 text-right">{t('bpp.invoices.planAmount', 'План')}</th>
            <th className="py-1 text-right">{t('bpp.invoices.lineAmount', 'В счёте')}</th>
          </tr>
        </thead>
        <tbody>
          {card.lines.map((line) => (
            <tr key={line.id} className="border-b last:border-0">
              <td className="py-1">{line.sys_number}</td>
              <td className="py-1">{line.name}</td>
              <td className="py-1 text-right">{shownQty(line.qty)}</td>
              <td className="py-1 text-right">{formatMoney(line.plan_amount)}</td>
              <td className="py-1 text-right">{formatMoney(line.amount)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
