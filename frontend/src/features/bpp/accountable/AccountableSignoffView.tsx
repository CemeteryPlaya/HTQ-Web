/**
 * Заявка на подотчётные средства — в карточке согласования
 * (`bpp.accountable_funds_request`) и по прямой ссылке.
 *
 * Показывает, на что и сколько просят, по какой статье, и как идёт отчёт:
 * выдано, подтверждено авансовыми отчётами, остаток. Действий нет — решение
 * принимают кнопки карточки процесса.
 */

import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import { Skeleton } from '@/components/ui/skeleton';
import { formatDate, formatMoney } from '@/features/bpp/format';

import { bppAccountableApi } from './api';

interface Props {
  id: string;
  embedded?: boolean;
}

const STATUS: Record<string, string> = {
  draft: 'Черновик',
  on_review: 'На согласовании',
  awaiting_accounting: 'Ожидает выдачи бухгалтерией',
  awaiting_report: 'Ожидает авансовый отчёт',
  closed: 'Закрыта',
};

export default function AccountableSignoffView({ id, embedded = false }: Props) {
  const { t } = useTranslation();
  const { data: card, isLoading, isError } = useQuery({
    queryKey: ['bpp', 'accountable', id],
    queryFn: () => bppAccountableApi.get(id),
  });

  if (isLoading) return <Skeleton className="h-48 w-full" />;
  if (isError || !card) {
    return (
      <p className="rounded-lg border border-dashed p-6 text-sm text-muted-foreground">
        {t('bpp.accountable.loadError', 'Не удалось загрузить заявку на подотчёт.')}
      </p>
    );
  }
  const Heading = embedded ? 'h2' : 'h1';
  const figures: [string, string][] = [
    [t('bpp.accountable.amount', 'Сумма'), card.amount],
    [t('bpp.accountable.reported', 'Подтверждено отчётами'), card.reported_amount],
    [t('bpp.accountable.remaining', 'Остаток'), card.remaining_amount],
  ];
  return (
    <div className="space-y-4">
      <div>
        <Heading className="text-lg font-semibold">
          {t('bpp.accountable.title', 'Подотчёт')} {card.number}
        </Heading>
        <p className="text-sm text-muted-foreground">
          {STATUS[card.status] ?? card.status} · {card.article_name} ·{' '}
          {t('bpp.accountable.created', 'от')} {formatDate(card.created_at)}
        </p>
      </div>
      <dl className="grid grid-cols-3 gap-4 rounded-lg border p-3 text-sm">
        {figures.map(([label, value]) => (
          <div key={label}>
            <dt className="text-xs text-muted-foreground">{label}</dt>
            <dd className="font-medium">{formatMoney(value, card.currency)}</dd>
          </div>
        ))}
      </dl>
      <div className="text-sm">
        <p className="text-xs text-muted-foreground">{t('bpp.accountable.goal', 'Цель')}</p>
        <p className="whitespace-pre-wrap">{card.goal}</p>
      </div>
      {card.reports.length > 0 && (
        <div className="rounded-lg border">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left">{t('bpp.accountable.expense', 'Затраты')}</th>
                <th className="px-3 py-2 text-right">{t('bpp.accountable.reportAmount', 'Сумма')}</th>
                <th className="px-3 py-2 text-left">{t('bpp.accountable.state', 'Согласование')}</th>
              </tr>
            </thead>
            <tbody>
              {card.reports.map((report) => (
                <tr key={report.id} className="border-t">
                  <td className="px-3 py-2">{report.expense_name}</td>
                  <td className="px-3 py-2 text-right whitespace-nowrap">
                    {formatMoney(report.amount, card.currency)}
                  </td>
                  <td className="px-3 py-2">{report.approval_state}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
