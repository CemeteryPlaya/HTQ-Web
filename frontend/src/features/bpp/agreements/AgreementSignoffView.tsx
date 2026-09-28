/**
 * Договор внутри карточки согласования (`bpp.agreement`).
 *
 * ФД, ТД, ОД и ГД решают по тому, что здесь видно (ТЗ §9, §16.1): с кем
 * договор, на какую сумму и с каким НДС, какие позиции плана он закрывает и
 * насколько превышает план (BR-034). Ручная ставка НДС подсвечена (D-14).
 * Действий нет: решение принимают кнопки карточки процесса.
 */
import type { ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';

import { StatusBadge } from '../core/StatusBadge';
import { formatDate, formatMoney } from '../format';

import { agreementApi, agreementKey } from './api';

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

export default function AgreementSignoffView({ id, embedded = false }: Props) {
  const { t } = useTranslation();
  const { data: card, isLoading, isError } = useQuery({
    queryKey: agreementKey(id),
    queryFn: () => agreementApi.get(id),
  });

  if (isLoading) return <Skeleton className="h-48 w-full" />;
  if (isError || !card) {
    return (
      <p className="text-sm text-muted-foreground">
        {t('bpp.agreements.loadFailed', 'Не удалось загрузить договор.')}
      </p>
    );
  }
  const currency = card.currency_code;
  const kind = card.agreement_type === 'goods' ? 'ТМЦ'
    : card.agreement_type === 'works' ? 'Работы и услуги' : '—';

  return (
    <div className="space-y-4">
      {!embedded && (
        <div className="flex items-center gap-2">
          <h2 className="text-xl font-semibold">{card.number}</h2>
          <StatusBadge kind="contract" status={card.status} />
        </div>
      )}
      {card.parent && (
        <p className="text-sm">
          {t('bpp.agreements.supplementTo', 'Дополнительное соглашение к договору {{n}}', {
            n: card.parent.number,
          })}
        </p>
      )}
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-4">
        <Row label={t('bpp.agreements.counterparty', 'Контрагент')}>
          {card.counterparty
            ? `${card.counterparty.short_name || card.counterparty.name} (${card.counterparty.reg_number})`
            : '—'}
        </Row>
        <Row label={t('bpp.agreements.extNumber', 'Номер и дата')}>
          {card.ext_number || '—'} {card.ext_date ? `от ${formatDate(card.ext_date)}` : ''}
        </Row>
        <Row label={t('bpp.agreements.project', 'Проект / статья')}>
          {card.project.code} / {card.article.name}
        </Row>
        <Row label={t('bpp.agreements.type', 'Тип договора')}>{kind}</Row>
        <Row label={t('bpp.agreements.amount', 'Сумма договора')}>
          {card.is_open
            ? t('bpp.agreements.open', 'Открытый договор')
            : formatMoney(card.amount ?? '0', currency)}
        </Row>
        <Row label={t('bpp.agreements.vat', 'НДС')}>
          {card.with_vat ? (
            <span>
              {card.vat_rate}%{card.vat_amount ? `, ${formatMoney(card.vat_amount, currency)}` : ''}
              {card.vat_source === 'manual' && (
                <Badge variant="outline" className="ml-2 border-amber-300 text-amber-800">
                  {t('bpp.agreements.vatManual', 'ставка изменена вручную')}
                </Badge>
              )}
            </span>
          ) : t('bpp.agreements.noVat', 'Без НДС')}
        </Row>
        <Row label={t('bpp.agreements.validTo', 'Срок действия по')}>
          {formatDate(card.valid_to)}
        </Row>
        {card.budget && Number(card.budget.over_plan) > 0 && (
          <Row label={t('bpp.agreements.overPlan', 'Сверх плана / свободно в статье')}>
            {formatMoney(card.budget.over_plan, currency)} /{' '}
            {formatMoney(card.budget.available, currency)}
          </Row>
        )}
      </dl>
      {card.items.length > 0 && (
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-left text-xs text-muted-foreground">
              <th className="py-1">{t('bpp.agreements.item', 'Позиция')}</th>
              <th className="py-1">{t('bpp.agreements.itemName', 'Наименование')}</th>
              <th className="py-1 text-right">{t('bpp.agreements.qty', 'Кол-во')}</th>
              <th className="py-1 text-right">{t('bpp.agreements.planAmount', 'План')}</th>
              <th className="py-1 text-right">{t('bpp.agreements.itemAmount', 'По договору')}</th>
            </tr>
          </thead>
          <tbody>
            {card.items.map((item) => (
              <tr key={item.id} className="border-b last:border-0">
                <td className="py-1">{item.sys_number}</td>
                <td className="py-1">{item.name}</td>
                <td className="py-1 text-right">{item.qty.replace('.', ',')} {item.uom ?? ''}</td>
                <td className="py-1 text-right">{formatMoney(item.plan_amount)}</td>
                <td className="py-1 text-right">
                  {item.amount === null ? '—' : formatMoney(item.amount)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
