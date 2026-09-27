/**
 * Страница документа модуля БЗО по прямой ссылке: `/bpp/requests/:id`,
 * `/bpp/accountable/:id`.
 *
 * Туда ведут ссылки движка согласования и центра уведомлений (колбэк
 * `describe` в `apps/bpp/approval_hooks.py`). Раздел `/bpp` с меню, реестрами
 * и формами строится на каркасе A2.1; до него эта страница — простая рамка
 * вокруг того же тела, что показывает карточка согласования, чтобы ссылка
 * не вела в 404. Каркас заменит её своей.
 */

import { Suspense, lazy } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Footer } from '@/components/Footer';
import { Header } from '@/components/Header';
import { Skeleton } from '@/components/ui/skeleton';

const VIEWS = {
  request: lazy(() => import('./requests/RequestSignoffView')),
  accountable: lazy(() => import('./accountable/AccountableSignoffView')),
};

export function BppDocumentPage({ kind }: { kind: keyof typeof VIEWS }) {
  const { t } = useTranslation();
  const { id = '' } = useParams<{ id: string }>();
  const View = VIEWS[kind];
  return (
    <div className="min-h-screen bg-background flex flex-col">
      <Header />
      <div className="flex-1 container mx-auto px-4 py-8 max-w-5xl">
        <Link
          to="/signoff"
          className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors mb-4"
        >
          <ArrowLeft className="h-4 w-4" />
          {t('bpp.document.toSignoff', 'К согласованиям')}
        </Link>
        <Suspense fallback={<Skeleton className="h-64 w-full" />}>
          <View id={id} />
        </Suspense>
      </div>
      <Footer />
    </div>
  );
}

export const BppRequestPage = () => <BppDocumentPage kind="request" />;
export const BppAccountablePage = () => <BppDocumentPage kind="accountable" />;
