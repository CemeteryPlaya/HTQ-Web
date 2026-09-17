import { Suspense, lazy, type ReactNode, useEffect, useState } from 'react';
import { BrowserRouter, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import Index from '@/pages/Index';

import { AppErrorBoundary } from '@/app/components/AppErrorBoundary';
import { PageLoader } from '@/app/components/PageLoader';
import { ScrollToTop } from '@/app/components/ScrollToTop';
import { lazyPages } from '@/app/routing/lazyPages';
import { registerRoutePrefetch } from '@/app/routing/prefetch';
import { protectedRoutes, publicRoutes } from '@/app/routing/routeDefinitions';
import type { RouteConfig } from '@/app/routing/types';
import { getAccessToken } from '@/lib/auth/profileStorage';
import { useActiveProfile } from '@/hooks/useActiveProfile';
import { ConferenceNotifier } from '@/components/ConferenceNotifier';
import { ServiceUnavailableListener } from '@/components/ServiceUnavailableListener';
import { BodyPointerEventsGuard } from '@/components/BodyPointerEventsGuard';

registerRoutePrefetch();

/**
 * Ответ 4xx не повторяется.
 *
 * По умолчанию react-query повторяет неудачный запрос трижды. Для 5xx и обрыва
 * связи это правильно, для 4xx — нет: 403 «нет прав» и 404 «не найдено» от
 * повтора не меняются. Хуже того, перехватчик в `api/client.ts` на каждый 401
 * и 403 обновляет токен, поэтому ОДИН запрещённый запрос превращался в восемь
 * обращений к серверу и столько же обновлений токена. Именно так карточка
 * согласования расшатывала сессию согласующему без прав на HR.
 *
 * 408 и 429 — исключения: это «попробуй ещё раз», а не отказ.
 */
const RETRYABLE_4XX = new Set([408, 429]);

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (failureCount, error) => {
        const status = (error as { status?: number; response?: { status?: number } })
          ?.status ?? (error as { response?: { status?: number } })?.response?.status;
        if (status !== undefined && status >= 400 && status < 500
            && !RETRYABLE_4XX.has(status)) {
          return false;
        }
        return failureCount < 3;
      },
    },
  },
});
const MailboxPasswordPrompt = lazy(() =>
  import('@/components/mail/MailboxPasswordPrompt')
    .then((m) => ({ default: m.MailboxPasswordPrompt })),
);

const DeferredToaster = lazyPages.Toaster;
const DeferredSonner = lazyPages.Sonner;
// Показ уведомлений (карточка в правом нижнем углу, звук, уведомление ОС).
// Отдельным чанком: тянет за собой api/tasks и синтез звука, которым на первом
// экране делать нечего.
const NotificationToasts = lazy(() =>
  import('@/components/NotificationToasts')
    .then((m) => ({ default: m.NotificationToasts })),
);

/**
 * Включатель показа уведомлений.
 *
 * Отдельный компонент, а не флаг `hasAccessToken` ниже: тот читается ОДИН раз
 * при монтировании App, а вход в систему — переход внутри SPA, без перезагрузки.
 * По флагу уведомления начинали бы приходить только со следующего открытия
 * страницы. Здесь же вопрос «вошёл ли» задаётся на каждом рендере, а рендер
 * случится: `useActiveProfile` подписан на тот же запрос профиля, который после
 * входа выполняет шапка.
 *
 * Пока человек не вошёл, чанк с показом уведомлений не загружается вовсе.
 */
const NotificationsChrome = () => {
  const { isLoggedIn } = useActiveProfile({ staleTime: 5 * 60 * 1000 });
  if (!isLoggedIn) return null;
  return (
    <Suspense fallback={null}>
      <NotificationToasts />
    </Suspense>
  );
};

const SuspensePage = ({ children }: { children: ReactNode }) => (
  <Suspense fallback={<PageLoader />}>{children}</Suspense>
);

const RouteElement = ({ route }: { route: RouteConfig }) => {
  const Component = route.component;
  const content = <Component />;

  if (!route.requiresAuth) {
    return <SuspensePage>{content}</SuspensePage>;
  }

  const RequireAuth = lazyPages.RequireAuth;
  return (
    <SuspensePage>
      <RequireAuth requiredRole={route.requiresRole}>{content}</RequireAuth>
    </SuspensePage>
  );
};

const AppRoutes = () => (
  <Routes>
    <Route path="/" element={<Index />} />

    {publicRoutes.map((route) => (
      <Route key={route.path} path={route.path} element={<RouteElement route={route} />} />
    ))}

    {protectedRoutes.map((route) => (
      <Route key={route.path} path={route.path} element={<RouteElement route={route} />} />
    ))}

    <Route path="*" element={<SuspensePage><lazyPages.NotFound /></SuspensePage>} />
  </Routes>
);

const App = () => {
  const hasAccessToken = Boolean(getAccessToken());
  const BottomNav = lazyPages.BottomNav;
  const [showDeferredUi, setShowDeferredUi] = useState(false);

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      setShowDeferredUi(true);
    }, 1500);

    return () => window.clearTimeout(timeoutId);
  }, []);

  // bfcache safeguard: when the user navigates to an external non-SPA page
  // (e.g. /django-admin/, /grafana/) and presses Back, some browsers restore
  // the cached SPA with stale internal state — react-router can desync from
  // window.history and throw "useLocation() may be used only in the context
  // of a <Router>".
  // Force a clean reload on persisted pageshow to dodge that whole class of
  // bugs. Fresh navigations have event.persisted=false and are unaffected.
  useEffect(() => {
    const onPageShow = (event: PageTransitionEvent) => {
      if (event.persisted) {
        window.location.reload();
      }
    };
    window.addEventListener('pageshow', onPageShow);
    return () => window.removeEventListener('pageshow', onPageShow);
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      <AppErrorBoundary>
        <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
          <ScrollToTop />
          <BodyPointerEventsGuard />
          {showDeferredUi && (
            <Suspense fallback={null}>
              <DeferredToaster />
              <DeferredSonner />
              {/* Рядом с приёмником тостов, а не в блоке ниже: уведомления
                  должны приходить на ЛЮБОЙ странице, в том числе на тех, где
                  нет шапки с колокольчиком (файлы отдела). */}
              <NotificationsChrome />
            </Suspense>
          )}
          <AppRoutes />
          <ServiceUnavailableListener />
          {hasAccessToken && (
            <Suspense fallback={null}>
              <BottomNav />
              <ConferenceNotifier />
              {/* Найденный корпоративный ящик, который платформа не смогла
                  открыть сама, ждёт пароля от сотрудника. Молчит, пока
                  ждать нечего. */}
              <MailboxPasswordPrompt variant="banner" />
            </Suspense>
          )}
        </BrowserRouter>
      </AppErrorBoundary>
    </QueryClientProvider>
  );
};

export default App;
