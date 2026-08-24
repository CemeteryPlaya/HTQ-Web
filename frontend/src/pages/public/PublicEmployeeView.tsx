/**
 * Public employee card view — no auth required, accessed via shareable token.
 *
 * Mirrors PublicOrgView but for ``target_type='employee'``. The backend
 * strips PII before returning, and EmployeeCardView with ``mode='public'``
 * additionally hides cross-employee navigation.
 */
import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ChevronLeft } from 'lucide-react';

import type { EmployeeCard } from '@/api/hr';
import { EmployeeCardView } from '@/components/hr/EmployeeCardView';
import { ShareWatermark, type WatermarkPayload } from '@/components/share-link/ShareWatermark';
import { Button } from '@/components/ui/button';
import { useTranslation } from 'react-i18next';
import i18n from '@/i18n';

interface PublicEmployeePayload {
  label: string | null;
  default_language?: 'ru' | 'en';
  generated_at: string | null;
  watermark: WatermarkPayload | null;
  card: EmployeeCard;
}

type ViewState = 'loading' | 'error' | 'gone' | 'ok';

/** Ленивая функция, а не таблица-константа: на момент импорта модуля словарь
 *  i18n ещё не загружен, и строки застыли бы на языке по умолчанию. */
function linkErrorMessage(status: number): string {
  return i18n.t(status === 404 ? 'share.linkNotFound' : 'share.linkExpired');
}

const LOGO_SRC = '/images/logo.webp';

function buildConsumeUrl(token: string): string {
  const raw = (import.meta.env.VITE_API_BASE_URL ?? '/api').toString();
  const base = raw.replace(/\/+$/, '');
  return `${base}/hr/v1/public/employee/${encodeURIComponent(token)}`;
}

function GuestHeader({ label }: { label?: string | null }) {
  const { t } = useTranslation();

  return (
    <header className="shrink-0 border-b bg-card">
      <div className="mx-auto flex h-14 max-w-5xl items-center gap-2 px-3 sm:gap-4 sm:px-6">
        <Link
          to="/"
          className="flex min-w-0 flex-shrink-0 items-center gap-2 text-sm font-semibold text-foreground hover:opacity-80"
        >
          <img src={LOGO_SRC} alt="" className="h-7 w-7 object-contain" />
          <span className="hidden sm:inline">Hi-Tech Group</span>
        </Link>
        <div className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
          <span className="hidden md:inline">{t('share.employee.title')}</span>
          {label ? <span className="truncate md:ml-1 md:inline"> · {label}</span> : null}
        </div>
        <Button
          asChild
          variant="ghost"
          size="sm"
          className="ml-auto h-8 flex-shrink-0 gap-1.5 px-2 sm:px-3"
        >
          <Link to="/">
            <ChevronLeft className="h-4 w-4" />
            <span className="hidden sm:inline">{t('share.backHome')}</span>
          </Link>
        </Button>
      </div>
    </header>
  );
}

const PublicEmployeeView = () => {
  const { t } = useTranslation();
  const { token } = useParams<{ token: string }>();
  const [state, setState] = useState<ViewState>('loading');
  const [data, setData] = useState<PublicEmployeePayload | null>(null);
  const [errorMsg, setErrorMsg] = useState<string>('');

  useEffect(() => {
    if (!token) {
      setErrorMsg(linkErrorMessage(404));
      setState('gone');
      return;
    }

    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(buildConsumeUrl(token), {
          method: 'GET',
          credentials: 'omit',
          headers: { Accept: 'application/json' },
        });
        if (cancelled) return;

        if (res.status === 404 || res.status === 410) {
          setErrorMsg(linkErrorMessage(res.status));
          setState('gone');
          return;
        }
        if (!res.ok) {
          setErrorMsg(t('share.genericError'));
          setState('error');
          return;
        }
        const ct = res.headers.get('content-type') ?? '';
        if (!ct.includes('application/json')) {
          setErrorMsg(t('share.badResponse'));
          setState('error');
          return;
        }
        const json: PublicEmployeePayload = await res.json();
        setData(json);
        setState('ok');
      } catch {
        if (!cancelled) {
          setErrorMsg(t('share.networkError'));
          setState('error');
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [token, t]);

  if (state === 'loading') {
    return (
      <div className="flex min-h-[100dvh] flex-col bg-background">
        <GuestHeader />
        <div className="flex flex-1 items-center justify-center">
          <div className="text-sm text-muted-foreground">{t('share.employee.loading')}</div>
        </div>
      </div>
    );
  }

  if (state === 'gone' || state === 'error') {
    return (
      <div className="flex min-h-[100dvh] flex-col bg-background">
        <GuestHeader />
        <div className="flex flex-1 items-center justify-center p-6">
          <div className="max-w-sm space-y-3 text-center">
            <h1 className="text-lg font-semibold">{t('share.accessDenied')}</h1>
            <p className="text-sm text-muted-foreground">{errorMsg}</p>
            <Button asChild variant="outline" size="sm" className="mt-4">
              <Link to="/">{t('share.backHome')}</Link>
            </Button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-[100dvh] flex-col bg-background">
      <GuestHeader label={data?.label} />

      <main className="flex-1 px-3 py-6 sm:px-6">
        <div className="mx-auto max-w-5xl">
          {data?.card ? (
            <EmployeeCardView card={data.card} mode="public" />
          ) : (
            <div className="rounded-2xl border bg-card p-6 text-center text-muted-foreground">
              {t('share.employee.noData')}
            </div>
          )}
        </div>
      </main>

      <ShareWatermark payload={data?.watermark} />

      <footer className="shrink-0 border-t bg-card px-3 py-2 pb-[calc(0.5rem+env(safe-area-inset-bottom))] text-[11px] text-muted-foreground sm:px-6 sm:text-xs">
        <div className="mx-auto flex max-w-5xl flex-col gap-1 sm:flex-row sm:items-center sm:justify-between sm:gap-2">
          <span>{t('share.restricted')}</span>
          {data?.generated_at && (
            <span>
              {t('share.generatedAt', {
                stamp: new Date(data.generated_at).toLocaleString(i18n.language),
              })}
            </span>
          )}
        </div>
      </footer>
    </div>
  );
};

export default PublicEmployeeView;
