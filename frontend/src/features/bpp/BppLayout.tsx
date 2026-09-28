/**
 * Раздел «Закупки и оплаты» (`/bpp/*`) — одностраничное приложение модуля
 * БЗО с левым меню (ТЗ §05).
 *
 * Меню и маршруты раздел не перечисляет сам: их приносят подмодули
 * (`features/bpp/<модуль>/module.tsx`, сборка — `modules.ts`). Раздел лишь
 * решает, что показать по правам:
 * - пункт меню подмодуля с `visible(permissions) === false` не рисуется;
 * - его маршруты отвечают экраном «Нет доступа», а не 404 и не пустой
 *   страницей: по прямой ссылке из письма человек должен понять, что дело в
 *   правах, а не в сломанной ссылке. Сервер всё равно проверяет права
 *   сам — экран лишь не зовёт ручки, которые ответят 403.
 *
 * Вход в раздел целиком закрыт гейтом маршрута `bpp:read`
 * (`app/routing/routeDefinitions.ts`). Образец раскладки — `HRLayout`.
 */
import { Suspense, useMemo, type ComponentType } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { ChevronRight, ShieldOff } from 'lucide-react';

import { BackToProfile } from '@/components/BackToProfile';
import { Footer } from '@/components/Footer';
import { Header } from '@/components/Header';
import { Skeleton } from '@/components/ui/skeleton';
import { usePermissions } from '@/hooks/usePermissions';
import { cn } from '@/lib/utils';

import { moduleVisible } from './core/moduleAccess';
import { bppModules, type BppModule } from './modules';

/** Базовый путь раздела — пункты меню подмодулей относительны ему. */
export const BPP_BASE = '/bpp';

const menuHref = (path: string) => `${BPP_BASE}/${path.replace(/^\/+/, '')}`;

function NoAccess() {
  const { t } = useTranslation();
  return (
    <div className="rounded-2xl border bg-card p-10 text-center">
      <ShieldOff className="mx-auto mb-3 h-8 w-8 text-muted-foreground" />
      <h2 className="text-lg font-semibold">{t('bpp.layout.noAccess', 'Нет доступа')}</h2>
      <p className="mt-1 text-sm text-muted-foreground">
        {t(
          'bpp.layout.noAccessHint',
          'У вашей роли нет прав на этот раздел. Если они нужны для работы, обратитесь к администратору.',
        )}
      </p>
    </div>
  );
}

function SectionNotFound() {
  const { t } = useTranslation();
  return (
    <div className="rounded-2xl border bg-card p-10 text-center text-sm text-muted-foreground">
      {t('bpp.layout.notFound', 'Такой страницы в разделе нет')}
    </div>
  );
}

function PageSkeleton() {
  return <Skeleton className="h-64 w-full" />;
}

/** Экран подмодуля — или «Нет доступа», если подмодуль закрыт правами. */
function GatedScreen({ module, screen: Screen }: { module: BppModule; screen: ComponentType }) {
  const permissions = usePermissions();
  // Пока права не пришли, «Нет доступа» было бы неправдой на полсекунды.
  if (permissions.isLoading) return <PageSkeleton />;
  return moduleVisible(module, permissions) ? <Screen /> : <NoAccess />;
}

interface Props {
  /** Подмодули раздела; параметр — для тестов, в приложении — `bppModules`. */
  modules?: BppModule[];
}

export function BppLayout({ modules = bppModules }: Props) {
  const { t } = useTranslation();
  const location = useLocation();
  const permissions = usePermissions();

  const menu = useMemo(
    () => modules
      .filter((module) => module.menu && moduleVisible(module, permissions))
      .map((module) => ({ key: module.key, ...module.menu!, href: menuHref(module.menu!.path) })),
    [modules, permissions],
  );

  const isActive = (href: string) =>
    location.pathname === href || location.pathname.startsWith(`${href}/`);

  const renderLink = (item: (typeof menu)[number], variant: 'side' | 'strip') => {
    const active = isActive(item.href);
    const Icon = item.icon;
    return (
      <Link
        key={item.key}
        to={item.href}
        aria-current={active ? 'page' : undefined}
        className={cn(
          variant === 'side'
            ? 'group flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-all duration-150 text-muted-foreground hover:bg-accent/80 hover:text-foreground'
            : 'flex min-h-[44px] items-center gap-2 rounded-xl px-3.5 py-2 text-xs font-semibold whitespace-nowrap transition-all text-muted-foreground hover:bg-muted hover:text-foreground',
          active && (variant === 'side'
            ? 'bg-primary/10 text-primary font-semibold border-l-2 border-primary pl-2.5 shadow-2xs'
            : 'bg-primary text-primary-foreground shadow-2xs hover:bg-primary hover:text-primary-foreground'),
        )}
      >
        {Icon && <Icon className="h-4 w-4 shrink-0" />}
        <span className="flex-1 truncate">{t(item.labelKey, item.labelFallback)}</span>
        {variant === 'side' && active && <ChevronRight className="h-3.5 w-3.5 opacity-60 shrink-0" />}
      </Link>
    );
  };

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <Header />
      <main className="flex-1">
        <div className="mx-auto w-full max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
          <div className="mb-6 flex flex-col gap-3">
            <BackToProfile className="mb-0 text-xs" />
            <h1 className="text-3xl font-extrabold tracking-tight text-foreground">
              {t('bpp.nav.title', 'Закупки и оплаты')}
            </h1>
          </div>

          {menu.length > 0 && (
            <nav
              aria-label={t('bpp.layout.menu', 'Меню раздела')}
              className="mb-6 flex items-center gap-1.5 overflow-x-auto rounded-2xl border bg-card/80 p-2 shadow-2xs lg:hidden scrollbar-none"
            >
              {menu.map((item) => renderLink(item, 'strip'))}
            </nav>
          )}

          <div className={cn('grid gap-8', menu.length > 0 && 'lg:grid-cols-[260px_1fr]')}>
            {menu.length > 0 && (
              <aside className="hidden lg:block">
                <nav
                  aria-label={t('bpp.layout.menu', 'Меню раздела')}
                  className="sticky top-20 flex flex-col gap-0.5 rounded-2xl border bg-card p-3.5 shadow-2xs"
                >
                  {menu.map((item) => renderLink(item, 'side'))}
                </nav>
              </aside>
            )}

            <div className="min-w-0 space-y-6">
              <Suspense fallback={<PageSkeleton />}>
                <Routes>
                  <Route
                    index
                    element={permissions.isLoading
                      ? <PageSkeleton />
                      : menu.length > 0
                        ? <Navigate to={menu[0].href} replace />
                        : <NoAccess />}
                  />
                  {modules.flatMap((module) => module.routes.map((route) => (
                    <Route
                      key={`${module.key}:${route.path}`}
                      path={route.path}
                      element={<GatedScreen module={module} screen={route.element} />}
                    />
                  )))}
                  <Route path="*" element={<SectionNotFound />} />
                </Routes>
              </Suspense>
            </div>
          </div>
        </div>
      </main>
      <Footer />
    </div>
  );
}

export default BppLayout;
