/**
 * Заявка на закупку внутри карточки согласования (`bpp.purchase_request`).
 *
 * ТД и ОД решают по тому, что здесь видно (ТЗ §16.1): что закупается, на
 * какую сумму, по какой статье и сколько после этого останется. Поэтому
 * рядом с позициями — блок «Бюджет»: лимит статьи, задействовано, доступно и
 * остаток после заявки (пока заявка на согласовании, её сумма уже в
 * «задействовано»). Действий нет: решение принимают кнопки карточки процесса.
 *
 * Сумма и даты — по правилам модуля (`features/bpp/format.ts`).
 */

import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import { Skeleton } from '@/components/ui/skeleton';
import { formatDate, formatMoney } from '@/features/bpp/format';

import { bppRequestsApi, type PurchaseRequestCard } from './api';

interface Props {
  id: string;
  embedded?: boolean;
}

const KIND: Record<string, string> = { goods: 'ТМЦ', works: 'Работы и услуги' };

const STATUS: Record<string, string> = {
  draft: 'Черновик',
  in_approval: 'На согласовании',
  approved: 'Утверждена',
  rework: 'На доработке',
  rejected: 'Отклонена',
  cancelled: 'Отменена',
  closed: 'Закрыта',
};

function BudgetBlock({ card }: { card: PurchaseRequestCard }) {
  const { t } = useTranslation();
  if (!card.budget) return null;
  const { budget, currency_code: currency } = card;
  const rows: [string, string, boolean?][] = [
    [t('bpp.request.limit', 'Лимит статьи'), budget.limit],
    [t('bpp.request.committed', 'Задействовано'), budget.committed],
    [t('bpp.request.available', 'Доступно'), budget.available],
    [
      budget.reserved
        ? t('bpp.request.afterReserved', 'Остаток после заявки (уже в резерве)')
        : t('bpp.request.after', 'Остаток после заявки'),
      budget.after_request,
      true,
    ],
  ];
  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-1 rounded-lg border p-3 text-sm sm:grid-cols-4">
      {rows.map(([label, value, accent]) => (
        <div key={label}>
          <dt className="text-xs text-muted-foreground">{label}</dt>
          <dd
            className={
              accent && Number(value) < 0 ? 'font-medium text-destructive' : 'font-medium'
            }
          >
            {formatMoney(value, currency)}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export default function RequestSignoffView({ id, embedded = false }: Props) {
  const { t } = useTranslation();
  const { data: card, isLoading, isError } = useQuery({
    queryKey: ['bpp', 'request', id],
    queryFn: () => bppRequestsApi.get(id),
  });

  if (isLoading) return <Skeleton className="h-64 w-full" />;
  if (isError || !card) {
    return (
      <p className="rounded-lg border border-dashed p-6 text-sm text-muted-foreground">
        {t('bpp.request.loadError', 'Не удалось загрузить заявку.')}
      </p>
    );
  }
  const Heading = embedded ? 'h2' : 'h1';
  return (
    <div className="space-y-4">
      <div>
        <Heading className="text-lg font-semibold">
          {t('bpp.request.title', 'Заявка на закупку')} {card.number}
          <span className="ml-2 align-middle rounded-full border px-2 py-0.5 text-xs font-normal text-muted-foreground">
            {t(`bpp.request.status.${card.status}`, STATUS[card.status] ?? card.status)}
          </span>
        </Heading>
        <p className="text-sm text-muted-foreground">
          {card.project.code} {card.project.name} ·{' '}
          {card.article?.name ?? t('bpp.request.noArticle', 'статья не выбрана')}
          {card.article?.archived ? ` (${t('bpp.request.archived', 'Архив')})` : ''} ·{' '}
          {KIND[card.purchase_type] ?? '—'} · {t('bpp.request.needBy', 'к')}{' '}
          {formatDate(card.need_date)}
        </p>
        {card.author_name && (
          <p className="text-xs text-muted-foreground">
            {t('bpp.request.author', 'Автор')}: {card.author_name}
          </p>
        )}
      </div>

      {card.rework_comment && (
        <p className="rounded-lg border border-yellow-300 bg-yellow-50 px-3 py-2 text-sm text-yellow-900 dark:border-yellow-700 dark:bg-yellow-950 dark:text-yellow-100">
          {t('bpp.request.reworkComment', 'Возвращена на доработку')}: {card.rework_comment}
        </p>
      )}

      <BudgetBlock card={card} />

      {card.justification && (
        <div className="text-sm">
          <p className="text-xs text-muted-foreground">
            {t('bpp.request.justification', 'Обоснование потребности')}
          </p>
          <p className="whitespace-pre-wrap">{card.justification}</p>
        </div>
      )}

      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full text-sm">
          <thead className="bg-muted/50 text-xs text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left">{t('bpp.request.sysNumber', 'Позиция')}</th>
              <th className="px-3 py-2 text-left">{t('bpp.request.name', 'Наименование')}</th>
              <th className="px-3 py-2 text-right">{t('bpp.request.qty', 'Кол-во')}</th>
              <th className="px-3 py-2 text-right">{t('bpp.request.price', 'Цена')}</th>
              <th className="px-3 py-2 text-right">{t('bpp.request.amount', 'Сумма')}</th>
              <th className="px-3 py-2 text-left">{t('bpp.request.date', 'Дата')}</th>
            </tr>
          </thead>
          <tbody>
            {card.items.map((item) => (
              <tr key={item.id} className="border-t">
                <td className="px-3 py-2 whitespace-nowrap">{item.sys_number}</td>
                <td className="px-3 py-2">
                  {item.name}
                  {item.specs && (
                    <span className="block text-xs text-muted-foreground">{item.specs}</span>
                  )}
                </td>
                <td className="px-3 py-2 text-right whitespace-nowrap">
                  {Number(item.qty).toLocaleString('ru-RU')} {item.uom ?? ''}
                </td>
                <td className="px-3 py-2 text-right whitespace-nowrap">{formatMoney(item.price)}</td>
                <td className="px-3 py-2 text-right whitespace-nowrap">{formatMoney(item.amount)}</td>
                <td className="px-3 py-2 whitespace-nowrap">{formatDate(item.need_date)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="border-t font-medium">
              <td className="px-3 py-2" colSpan={4}>
                {t('bpp.request.total', 'Сумма заявки')}
              </td>
              <td className="px-3 py-2 text-right whitespace-nowrap">
                {formatMoney(card.total_amount, card.currency_code)}
              </td>
              <td />
            </tr>
          </tfoot>
        </table>
      </div>

      {card.files.length > 0 && (
        <p className="text-xs text-muted-foreground">
          {t('bpp.request.files', 'Документы')}:{' '}
          {card.files.map((file) => file.filename).join(', ')}
        </p>
      )}
    </div>
  );
}
