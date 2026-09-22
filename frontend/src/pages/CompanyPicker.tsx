import { useEffect, type ReactElement } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useLocation, useNavigate, type Location } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Building2, ChevronRight, Loader2, LogOut } from 'lucide-react';

import api from '@/api/client';
import { PageLoader } from '@/app/components/PageLoader';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { useMyCompanies } from '@/hooks/useMyCompanies';
import { hostLabelOf, switchCompany } from '@/lib/auth/companySwitch';
import { clearAuthStorage } from '@/lib/auth/profileStorage';

const PICKER_PATH = '/companies/choose';

/**
 * Куда вести после выбора: туда, куда человек шёл до редиректа на этот экран
 * (`RequireAuth` кладёт исходное место в `state.from`), иначе на главную.
 *
 * Путь приклеивается к чужому хосту строкой, поэтому берётся только настоящий
 * путь от корня: `//…` браузер прочёл бы как адрес другого хоста. Сам экран
 * выбора как цель тоже отвергается — на поддомене компании он не нужен.
 */
const targetPath = (state: unknown): string => {
  const from = (state as { from?: Partial<Location> } | null)?.from;
  const pathname = from?.pathname;
  if (!pathname || !pathname.startsWith('/') || pathname.startsWith('//') || pathname === PICKER_PATH) {
    return '/';
  }
  return `${pathname}${from.search ?? ''}${from.hash ?? ''}`;
};

/**
 * Приземление с голого домена (блок I.2, S4).
 *
 * Компания определяется поддоменом, а вход и регистрация живут на голом
 * домене. После входа человека надо увести в его компанию: с одной — сразу,
 * с несколькими — по выбору. Без этого на голом домене каждый запрос к
 * данным компании отвечал бы 403: гейт модуля считает уровень в компании, а
 * её там нет.
 */
export default function CompanyPicker() {
  const { t } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { companies, isLoading, isError } = useMyCompanies();
  const target = targetPath(location.state);

  useEffect(() => {
    if (!isLoading && companies.length === 1) switchCompany(companies[0], target);
  }, [isLoading, companies, target]);

  // Тот же выход, что в профиле и настройках (MyProfile/Settings).
  const logout = async () => {
    clearAuthStorage();
    try {
      const client = await (api as unknown as { getClient: () => Promise<typeof api> }).getClient();
      if (client?.defaults?.headers) {
        delete client.defaults.headers.common['Authorization'];
      }
    } catch {
      // ignore — logout must always succeed locally.
    }
    queryClient.clear();
    navigate('/login');
  };

  if (isLoading) return <PageLoader />;

  let body: ReactElement;
  if (isError) {
    body = (
      <>
        <CardHeader>
          <CardTitle>{t('companies.picker.loadError')}</CardTitle>
        </CardHeader>
        <CardContent>
          <Button variant="outline" onClick={() => queryClient.invalidateQueries({ queryKey: ['companies', 'me'] })}>
            {t('common.retry')}
          </Button>
        </CardContent>
      </>
    );
  } else if (companies.length === 0) {
    body = (
      <>
        <CardHeader>
          <CardTitle>{t('companies.picker.none')}</CardTitle>
          <CardDescription>{t('companies.picker.noneHint')}</CardDescription>
        </CardHeader>
        <CardContent>
          <Button variant="outline" onClick={logout} className="gap-2">
            <LogOut className="h-4 w-4" />
            {t('profile.logout')}
          </Button>
        </CardContent>
      </>
    );
  } else if (companies.length === 1) {
    body = (
      <CardContent className="flex items-center gap-3 py-8 text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin text-primary" />
        {t('companies.picker.redirecting')}
      </CardContent>
    );
  } else {
    body = (
      <>
        <CardHeader>
          <CardTitle>{t('companies.picker.title')}</CardTitle>
          <CardDescription>{t('companies.picker.subtitle')}</CardDescription>
        </CardHeader>
        <CardContent>
          <ul className="space-y-2">
            {companies.map((c) => (
              <li key={c.slug}>
                <button
                  type="button"
                  onClick={() => switchCompany(c, target)}
                  className="flex w-full items-center gap-3 rounded-lg border px-4 py-3 text-left transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <Building2 className="h-5 w-5 shrink-0 text-primary" />
                  <span className="flex-1 min-w-0">
                    <span className="block font-medium truncate">{c.name}</span>
                    <span className="block font-mono text-xs text-muted-foreground">{hostLabelOf(c)}</span>
                  </span>
                  {c.is_default && <Badge variant="secondary">{t('companies.picker.default')}</Badge>}
                  <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
                </button>
              </li>
            ))}
          </ul>
        </CardContent>
      </>
    );
  }

  return (
    <div className="min-h-screen bg-background flex items-center justify-center px-4 py-10">
      <Card className="w-full max-w-md">{body}</Card>
    </div>
  );
}
