/** /requests/my-stats — личная аналитика: что подавал Я.
 *
 *  Счётчики участия («ждут меня», «я в копии») считаются на клиенте по
 *  спискам, которые страница и так держит, а вот сводка по ПОДАННОМУ —
 *  серверная (`stats/mine`): суммы и позиции разбросаны по формам разных
 *  версий, и складывать их в браузере значило бы тянуть туда все заявки.
 *
 *  Чужого здесь нет и быть не может: у `stats/mine` нет параметра «чья
 *  статистика», пользователь берётся из токена. Общие разрезы — отдельная
 *  админская страница /requests/stats. */

import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';

import { requestsApi } from '@/api/requests';
import { RequestsLayout } from '@/features/requests/RequestsLayout';
import { useCc, useInbox, useRequestsStream } from '@/features/requests/hooks';
import type { RequestStatus } from '@/features/requests/types';
import { translatedMap } from '@/lib/i18n/translatedMap';

const STATUS_LABEL: Record<RequestStatus, string> = translatedMap({
  draft: 'requests.statusRu.draft',
  pending: 'requests.statusRu.pending',
  approved: 'requests.statusRu.approved',
  rejected: 'requests.statusRu.rejected',
  cancelled: 'requests.statusRu.cancelled',
  returned: 'requests.statusRu.returned',
});

/** Деньги приходят строкой («300.00») — Decimal с бэкенда, а не число:
 *  через float суммы терять нельзя. Показываем с разделителями и без
 *  копеек, когда их нет. */
function money(raw: string, currency: string): string {
  const value = Number(raw);
  if (!Number.isFinite(value)) return raw;
  const text = value.toLocaleString('ru-RU', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  });
  return currency ? `${text} ${currency}` : text;
}

function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="font-display text-3xl font-semibold text-foreground break-words">
          {value}
        </div>
        <div className="text-sm text-muted-foreground">{label}</div>
        {hint && <div className="mt-1 text-xs text-muted-foreground">{hint}</div>}
      </CardContent>
    </Card>
  );
}

export default function MyStatsPage() {
  const { t } = useTranslation();
  useRequestsStream();
  const inbox = useInbox();
  const cc = useCc();
  const mine = useQuery({
    queryKey: ['requests', 'stats', 'mine'],
    queryFn: () => requestsApi.stats.mine(),
  });

  if (mine.isLoading) {
    return (
      <RequestsLayout title={t('requests.nav.myStats')} subtitle={t('requests.myStats.subtitle')}>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-24" />)}
        </div>
      </RequestsLayout>
    );
  }

  if (mine.isError || !mine.data) {
    return (
      <RequestsLayout title={t('requests.nav.myStats')} subtitle={t('requests.myStats.subtitle')}>
        <p className="text-sm text-muted-foreground">{t('requests.myStats.loadError')}</p>
      </RequestsLayout>
    );
  }

  const data = mine.data;
  const statuses = (Object.keys(STATUS_LABEL) as RequestStatus[])
    .filter((s) => s !== 'draft' && (data.by_status[s]?.count ?? 0) > 0);

  return (
    <RequestsLayout title={t('requests.nav.myStats')} subtitle={t('requests.myStats.subtitle')}>
      <div className="space-y-6">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Tile
            label={t('requests.myStats.sentByMe')}
            value={String(data.submitted)}
            hint={data.drafts > 0
              ? t('requests.myStats.draftsHint', { count: data.drafts })
              : undefined}
          />
          <Tile
            label={t('requests.myStats.totalAmount')}
            value={money(data.amount, data.currency)}
          />
          {/* Эти два — про участие, а не про поданное: их держат списки
              «Ждёт меня» и «Я в копии», которые страница и так читает. */}
          <Tile label={t('requests.myStats.awaitingMe')} value={String(inbox.data?.length ?? 0)} />
          <Tile label={t('requests.myStats.ccMe')} value={String(cc.data?.length ?? 0)} />
        </div>

        {statuses.length > 0 && (
          <Card>
            <CardHeader><CardTitle>{t('requests.myStats.byStatus')}</CardTitle></CardHeader>
            <CardContent>
              <div className="grid gap-4 sm:grid-cols-3 lg:grid-cols-5">
                {statuses.map((s) => (
                  <div key={s} className="rounded-lg border p-3">
                    <div className="text-2xl font-semibold text-foreground">
                      {data.by_status[s].count}
                    </div>
                    <div className="text-xs text-muted-foreground">{STATUS_LABEL[s]}</div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      {money(data.by_status[s].amount, data.currency)}
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        {/* Ради чего страница и затевалась: что человек заказывал и сколько.
            Единицы в отдельной колонке — «5 шт» и «3 кг» не складываются. */}
        <Card>
          <CardHeader><CardTitle>{t('requests.myStats.items')}</CardTitle></CardHeader>
          <CardContent>
            {data.items.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t('requests.myStats.noItems')}</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b text-left text-xs text-muted-foreground">
                      <th className="py-2 pr-4 font-medium">{t('requests.myStats.itemName')}</th>
                      <th className="py-2 pr-4 font-medium text-right">
                        {t('requests.myStats.itemQuantity')}
                      </th>
                      <th className="py-2 pr-4 font-medium">{t('requests.myStats.itemUnit')}</th>
                      <th className="py-2 font-medium text-right">
                        {t('requests.myStats.itemRequests')}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.items.map((item) => (
                      <tr key={`${item.name}|${item.unit}`} className="border-b last:border-0">
                        <td className="py-2 pr-4 break-words">{item.name}</td>
                        <td className="py-2 pr-4 text-right font-medium tabular-nums">
                          {item.quantity}
                        </td>
                        <td className="py-2 pr-4 text-muted-foreground">{item.unit || '—'}</td>
                        <td className="py-2 text-right tabular-nums text-muted-foreground">
                          {item.requests}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>

        {data.by_template.length > 1 && (
          <Card>
            <CardHeader><CardTitle>{t('requests.myStats.byTemplate')}</CardTitle></CardHeader>
            <CardContent>
              <div className="space-y-2">
                {data.by_template.map((row) => (
                  <div
                    key={row.template_id ?? row.name}
                    className="flex flex-wrap items-baseline justify-between gap-2 border-b pb-2 last:border-0"
                  >
                    <span className="break-words">{row.name}</span>
                    <span className="text-sm text-muted-foreground tabular-nums">
                      {t('requests.myStats.templateCount', { count: row.count })}
                      {' · '}
                      {money(row.amount, data.currency)}
                    </span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </RequestsLayout>
  );
}
