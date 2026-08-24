/** /requests/my-stats — personal stats: the user's own requests where they
 *  participated (initiated / awaiting them / acted-on / CC'd). Visible to every
 *  logged-in user, unlike the admin-only general /requests/stats dashboards. */

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';

import { RequestsLayout } from '@/features/requests/RequestsLayout';
import { useCc, useDone, useInbox, useRequestsStream, useSent } from '@/features/requests/hooks';
import type { RequestInstance, RequestStatus } from '@/features/requests/types';
import { useTranslation } from 'react-i18next';
import { translatedMap } from '@/lib/i18n/translatedMap';

const STATUS_LABEL: Record<RequestStatus, string> = translatedMap({
  draft: 'requests.statusRu.draft',
  pending: 'requests.statusRu.pending',
  approved: 'requests.statusRu.approved',
  rejected: 'requests.statusRu.rejected',
  cancelled: 'requests.statusRu.cancelled',
  returned: 'requests.statusRu.returned',
});

function Tile({ label, value }: { label: string; value: number }) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="font-display text-3xl font-semibold text-foreground">{value}</div>
        <div className="text-sm text-muted-foreground">{label}</div>
      </CardContent>
    </Card>
  );
}

export default function MyStatsPage() {
  const { t } = useTranslation();
  useRequestsStream();
  const sent = useSent();
  const inbox = useInbox();
  const done = useDone();
  const cc = useCc();

  const loading = sent.isLoading || inbox.isLoading || done.isLoading || cc.isLoading;

  // Union of every request the user took part in, deduped by id.
  const byId = new Map<number, RequestInstance>();
  for (const list of [sent.data, inbox.data, done.data, cc.data]) {
    for (const r of list ?? []) byId.set(r.id, r);
  }
  const all = [...byId.values()];
  const countStatus = (s: RequestStatus) => all.filter((r) => r.status === s).length;

  return (
    <RequestsLayout title={t('requests.nav.myStats')} subtitle={t('requests.myStats.subtitle')}>
      {loading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-24" />)}
        </div>
      ) : (
        <div className="space-y-6">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Tile label={t('requests.myStats.totalInvolved')} value={all.length} />
            <Tile label={t('requests.myStats.sentByMe')} value={sent.data?.length ?? 0} />
            <Tile label={t('requests.myStats.awaitingMe')} value={inbox.data?.length ?? 0} />
            <Tile label={t('requests.myStats.ccMe')} value={cc.data?.length ?? 0} />
          </div>

          <Card>
            <CardHeader>
              <CardTitle>{t('requests.myStats.byStatus')}</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid gap-4 sm:grid-cols-3 lg:grid-cols-6">
                {(Object.keys(STATUS_LABEL) as RequestStatus[]).map((s) => (
                  <div key={s} className="rounded-lg border p-3">
                    <div className="text-2xl font-semibold text-foreground">{countStatus(s)}</div>
                    <div className="text-xs text-muted-foreground">{STATUS_LABEL[s]}</div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </RequestsLayout>
  );
}
