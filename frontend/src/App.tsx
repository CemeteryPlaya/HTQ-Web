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
import { ConferenceNotifier } from '@/components/ConferenceNotifier';
import { ServiceUnavailableListener } from '@/components/ServiceUnavailableListener';
import { BodyPointerEventsGuard } from '@/components/BodyPointerEventsGuard';

registerRoutePrefetch();

const queryClient = new QueryClient();
const MailboxPasswordPrompt = lazy(() =>
  import('@/components/mail/MailboxPasswordPrompt')
    .then((m) => ({ default: m.MailboxPasswordPrompt })),
);

const DeferredToaster = lazyPages.Toaster;
const DeferredSonner = lazyPages.Sonner;

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
      <RequireAuth requires={route.requires}>{content}</RequireAuth>
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
