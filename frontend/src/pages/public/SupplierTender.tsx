/**
 * Страница поставщика `/supplier/:token` (T3.5; план этапа 3 §1, §2 T3.5) —
 * публичная, без layout приложения и без входа: поставщик не сотрудник.
 *
 * Поток: промежуточная карточка (`GET`, ничего не пишет) → «Открыть
 * предложение» (`POST bind` — устройство закрепляется cookie) → тендер и
 * предложение. Запросы — отдельным клиентом без JWT
 * (`features/tender/portal/client.ts`).
 *
 * Экраны отказов: 404 — «Ссылка недействительна»; 403/409 `E-TND-06` —
 * «Ссылка открыта на другом устройстве»; 409 `E-TND-05` — «Приём
 * предложений завершён»; 429 — «повторите через N с».
 */
import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';
import { Ban } from 'lucide-react';

import { Skeleton } from '@/components/ui/skeleton';
import { portalApi, portalKeys } from '@/features/tender/portal/client';
import { OfferEditor } from '@/features/tender/portal/OfferEditor';
import { retryAfterOf, screenOf } from '@/features/tender/portal/portalErrors';
import { ErrorScreen, LandingCard, PortalShell } from '@/features/tender/portal/PortalScreens';

/** Отказы портала не повторяются автоматически: 404/403 повтор не исправит, 429 — усугубит. */
const NO_RETRY = { retry: false, refetchOnWindowFocus: false } as const;

function Loading() {
  return (
    <PortalShell>
      <Skeleton className="h-8 w-2/3" />
      <Skeleton className="h-40 w-full" />
      <Skeleton className="h-40 w-full" />
    </PortalShell>
  );
}

function Workspace({ token, onFatal }: { token: string; onFatal: (error: unknown) => void }) {
  const { t } = useTranslation();
  const [declined, setDeclined] = useState(false);
  const tender = useQuery({ queryKey: portalKeys.tender(token), queryFn: () => portalApi.tender(token), ...NO_RETRY });
  const offer = useQuery({ queryKey: portalKeys.offer(token), queryFn: () => portalApi.offer(token), ...NO_RETRY });

  const failure = tender.error ?? offer.error;
  if (failure) {
    return (
      <ErrorScreen
        screen={screenOf(failure)}
        retryAfter={retryAfterOf(failure)}
        onRetry={() => { void tender.refetch(); void offer.refetch(); }}
      />
    );
  }
  if (!tender.data || !offer.data) return <Loading />;

  if (declined || offer.data.invitation_status === 'declined') {
    return (
      <PortalShell>
        <div className="space-y-2 rounded-2xl border bg-card p-6 text-center">
          <Ban className="mx-auto h-10 w-10 text-muted-foreground" />
          <h1 className="text-xl font-semibold">{t('tender.portal.declinedTitle', 'Вы отказались от участия в тендере')}</h1>
          <p className="text-base text-muted-foreground">
            {t('tender.portal.declinedText', 'Заказчик получил вашу причину отказа. Спасибо за ответ.')}
          </p>
        </div>
      </PortalShell>
    );
  }

  return (
    <PortalShell>
      <OfferEditor
        token={token}
        tender={tender.data}
        offer={offer.data}
        onFatal={onFatal}
        onDeclined={() => setDeclined(true)}
      />
    </PortalShell>
  );
}

export default function SupplierTender() {
  const { token = '' } = useParams<{ token: string }>();
  const queryClient = useQueryClient();
  const [opened, setOpened] = useState(false);
  const [binding, setBinding] = useState(false);
  const [fatal, setFatal] = useState<unknown>(null);

  const card = useQuery({
    queryKey: portalKeys.card(token),
    queryFn: () => portalApi.card(token),
    enabled: Boolean(token),
    ...NO_RETRY,
  });

  const retry = () => {
    setFatal(null);
    void queryClient.invalidateQueries({ queryKey: portalKeys.all(token) });
  };

  if (fatal) return <ErrorScreen screen={screenOf(fatal)} retryAfter={retryAfterOf(fatal)} onRetry={retry} />;
  if (card.error) {
    return <ErrorScreen screen={screenOf(card.error)} retryAfter={retryAfterOf(card.error)} onRetry={retry} />;
  }
  if (!card.data) return <Loading />;

  if (!card.data.bound && !opened) {
    const open = async () => {
      setBinding(true);
      try {
        await portalApi.bind(token);
        setOpened(true);
      } catch (error) {
        setFatal(error);
      } finally {
        setBinding(false);
      }
    };
    return <LandingCard card={card.data} pending={binding} onOpen={() => { void open(); }} />;
  }

  return <Workspace token={token} onFatal={setFatal} />;
}
