/**
 * Сводка группы (блок H, задача 5).
 *
 * Сводит две уже готовые ручки-читателя — `hr/v1/holding/headcount` и
 * `tasks/v1/holding/projects` (задачи 3 и 4) — в одну таблицу по компании.
 * Бюджеты (`apps.contracts`) и согласования (`apps.signoff`) в сводку ещё не
 * подключены: их несут плитки-заглушки с явной подписью, чтобы отсутствие
 * данных нельзя было принять за настоящий ноль.
 *
 * Маршрут, права страницы и ссылку в меню подключает следующая задача — этот
 * файл только сам экран.
 *
 * Списки компаний у двух ручек могут не совпадать: компания без единой
 * строки в домене просто не попадает в его сводку. Соединяем их по
 * `company_slug`, недостающее в какой-то из ручек показываем прочерком, а не
 * нулём (ноль означал бы «действительно нуль», а не «ручка не отдала»).
 *
 * 403 и 503 от ЛЮБОЙ из двух ручек — не частичная таблица, а отдельное
 * состояние экрана на всю страницу: цифры по видимой половине без второй
 * ввели бы в заблуждение (проекты без штата и наоборот), а сама причина
 * (нет доступа / сводки пересобираются) относится к сводке целиком.
 */
import type { ReactNode } from 'react';
import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, Building2, CheckSquare, Clock3, ShieldAlert, Users, Wallet } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { holdingApi } from '@/api/holding';
import { BackToProfile } from '@/components/BackToProfile';
import { Footer } from '@/components/Footer';
import { Header } from '@/components/Header';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table, TableBody, TableCell, TableFooter, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { errorStatus, explainedDetail } from '@/lib/apiError';

const DASH = '—';

function formatNumber(value: number | null): string {
  if (value === null) return DASH;
  return new Intl.NumberFormat('ru-RU').format(value);
}

function formatDate(value: string | null): string {
  if (!value) return DASH;
  const parsed = new Date(`${value}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return DASH;
  return new Intl.DateTimeFormat('ru-RU').format(parsed);
}

interface MergedRow {
  slug: string;
  name: string;
  employeesActive: number | null;
  employeesTotal: number | null;
  staffingHeadcount: number | null;
  staffingPayroll: number | null;
  projectsActive: number | null;
  sitesActive: number | null;
  tasksOpen: number | null;
  tasksOverdue: number | null;
  reportsLastDate: string | null;
}

function emptyRow(slug: string, name: string): MergedRow {
  return {
    slug, name,
    employeesActive: null, employeesTotal: null, staffingHeadcount: null, staffingPayroll: null,
    projectsActive: null, sitesActive: null, tasksOpen: null, tasksOverdue: null, reportsLastDate: null,
  };
}

interface TileProps {
  icon: typeof Users;
  title: string;
  children: ReactNode;
}

function Tile({ icon: Icon, title, children }: TileProps) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardDescription className="flex items-center gap-2">
          <Icon className="h-4 w-4" />
          {title}
        </CardDescription>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

function StubTile({ title, stubText }: { title: string; stubText: string }) {
  return (
    <Card className="border-dashed">
      <CardHeader className="pb-3">
        <CardTitle className="text-base font-medium text-muted-foreground">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-sm text-muted-foreground">{stubText}</p>
      </CardContent>
    </Card>
  );
}

const GroupSummary = () => {
  const { t } = useTranslation();

  const headcountQuery = useQuery({
    queryKey: ['holding', 'headcount'],
    queryFn: async () => (await holdingApi.headcount()).data,
  });
  const projectsQuery = useQuery({
    queryKey: ['holding', 'projects'],
    queryFn: async () => (await holdingApi.projects()).data,
  });

  const isLoading = headcountQuery.isLoading || projectsQuery.isLoading;
  const errors = [headcountQuery.error, projectsQuery.error].filter(Boolean);
  // 403 перекрывает 503 — если хоть одна ручка говорит «не с того поддомена»,
  // это и есть причина показать пользователю, даже если другая параллельно
  // ловит пересборку представлений.
  const forbiddenError = errors.find((error) => errorStatus(error) === 403);
  const unavailableError = errors.find((error) => errorStatus(error) === 503);
  const otherError = errors.find((error) => errorStatus(error) !== 403 && errorStatus(error) !== 503);

  const rows = useMemo<MergedRow[]>(() => {
    const bySlug = new Map<string, MergedRow>();
    for (const row of headcountQuery.data?.companies ?? []) {
      const merged = bySlug.get(row.company_slug) ?? emptyRow(row.company_slug, row.company_name);
      merged.employeesActive = row.employees_active;
      merged.employeesTotal = row.employees_total;
      merged.staffingHeadcount = row.staffing_headcount;
      merged.staffingPayroll = row.staffing_payroll;
      bySlug.set(row.company_slug, merged);
    }
    for (const row of projectsQuery.data?.companies ?? []) {
      const merged = bySlug.get(row.company_slug) ?? emptyRow(row.company_slug, row.company_name);
      merged.projectsActive = row.projects_active;
      merged.sitesActive = row.sites_active;
      merged.tasksOpen = row.tasks_open;
      merged.tasksOverdue = row.tasks_overdue;
      merged.reportsLastDate = row.reports_last_date;
      bySlug.set(row.company_slug, merged);
    }
    return [...bySlug.values()].sort((a, b) => a.name.localeCompare(b.name, 'ru'));
  }, [headcountQuery.data, projectsQuery.data]);

  const headcountTotals = headcountQuery.data?.totals ?? null;
  const projectsTotals = projectsQuery.data?.totals ?? null;

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <Header />
      <main className="container mx-auto w-full max-w-6xl flex-1 space-y-6 px-4 py-8">
        <BackToProfile />
        <div>
          <h1 className="text-2xl font-bold">{t('holding.title', 'Сводка группы')}</h1>
          <p className="text-sm text-muted-foreground">
            {t('holding.subtitle',
              'Численность, работы, бюджеты и согласования по всем действующим компаниям группы.')}
          </p>
        </div>

        {isLoading ? (
          <div data-testid="holding-summary-skeleton" className="space-y-6">
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {[0, 1, 2, 3].map((i) => (
                <Card key={i}>
                  <CardHeader className="pb-3"><Skeleton className="h-4 w-24" /></CardHeader>
                  <CardContent><Skeleton className="h-8 w-16" /></CardContent>
                </Card>
              ))}
            </div>
            <Skeleton className="h-64 w-full rounded-xl" />
          </div>
        ) : forbiddenError ? (
          <div data-testid="holding-summary-forbidden"
            className="flex items-start gap-3 rounded-lg border border-amber-300/70 bg-amber-50/70 px-4 py-3 text-sm dark:border-amber-800/70 dark:bg-amber-950/30">
            <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
            <p>{explainedDetail(forbiddenError) ?? t('holding.forbiddenFallback',
              'Сводка по группе доступна только на поддомене холдинга.')}</p>
          </div>
        ) : unavailableError ? (
          <div data-testid="holding-summary-unavailable"
            className="flex items-start gap-3 rounded-lg border bg-muted/40 px-4 py-3 text-sm text-muted-foreground">
            <Clock3 className="mt-0.5 h-4 w-4 shrink-0" />
            <p>{explainedDetail(unavailableError) ?? t('holding.unavailableFallback',
              'Сводки холдинга сейчас пересобираются, повторите позже.')}</p>
          </div>
        ) : otherError ? (
          <div data-testid="holding-summary-error"
            className="flex items-start gap-3 rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <p>{explainedDetail(otherError) ?? t('holding.errorFallback', 'Не удалось загрузить сводку по группе.')}</p>
          </div>
        ) : (
          <>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Tile icon={Users} title={t('holding.tiles.headcount', 'Численность')}>
                <p className="text-2xl font-semibold tabular-nums">
                  {formatNumber(headcountTotals?.employees_active ?? null)}
                </p>
                <p className="text-xs text-muted-foreground">
                  {t('holding.tiles.headcountHint', 'действующих сотрудников по группе')}
                </p>
              </Tile>
              <Tile icon={CheckSquare} title={t('holding.tiles.projects', 'Работы')}>
                <p className="text-2xl font-semibold tabular-nums">
                  {formatNumber(projectsTotals?.projects_active ?? null)}
                </p>
                <p className="text-xs text-muted-foreground">
                  {t('holding.tiles.projectsHint', 'активных проектов по группе')}
                </p>
              </Tile>
              <StubTile
                title={t('holding.tiles.budgets', 'Бюджеты')}
                stubText={t('holding.tiles.stub', 'Данные подключит второй разработчик')}
              />
              <StubTile
                title={t('holding.tiles.approvals', 'Согласования')}
                stubText={t('holding.tiles.stub', 'Данные подключит второй разработчик')}
              />
            </div>

            <section className="rounded-xl border bg-card p-4">
              <Table data-testid="holding-summary-table">
                <TableHeader>
                  <TableRow>
                    <TableHead>{t('holding.table.company', 'Компания')}</TableHead>
                    <TableHead className="text-right">
                      {t('holding.table.employees', 'Сотрудников (действ. / всего)')}
                    </TableHead>
                    <TableHead className="text-right">
                      {t('holding.table.staffingHeadcount', 'Численность по штату')}
                    </TableHead>
                    <TableHead className="text-right">{t('holding.table.staffingPayroll', 'ФОТ')}</TableHead>
                    <TableHead className="text-right">
                      {t('holding.table.projectsActive', 'Активные проекты')}
                    </TableHead>
                    <TableHead className="text-right">{t('holding.table.sitesActive', 'Объекты')}</TableHead>
                    <TableHead className="text-right">{t('holding.table.tasksOpen', 'Открытые задачи')}</TableHead>
                    <TableHead className="text-right">{t('holding.table.tasksOverdue', 'Просроченные')}</TableHead>
                    <TableHead className="text-right">
                      {t('holding.table.reportsLastDate', 'Последний отчёт')}
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((row) => (
                    <TableRow key={row.slug}>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <Building2 className="h-4 w-4 text-muted-foreground" />
                          <span className="font-medium">{row.name}</span>
                        </div>
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {formatNumber(row.employeesActive)} / {formatNumber(row.employeesTotal)}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">{formatNumber(row.staffingHeadcount)}</TableCell>
                      <TableCell className="text-right tabular-nums">{formatNumber(row.staffingPayroll)}</TableCell>
                      <TableCell className="text-right tabular-nums">{formatNumber(row.projectsActive)}</TableCell>
                      <TableCell className="text-right tabular-nums">{formatNumber(row.sitesActive)}</TableCell>
                      <TableCell className="text-right tabular-nums">{formatNumber(row.tasksOpen)}</TableCell>
                      <TableCell className="text-right tabular-nums">
                        {row.tasksOverdue !== null && row.tasksOverdue > 0 ? (
                          <Badge variant="destructive">{formatNumber(row.tasksOverdue)}</Badge>
                        ) : (
                          formatNumber(row.tasksOverdue)
                        )}
                      </TableCell>
                      <TableCell className="text-right">{formatDate(row.reportsLastDate)}</TableCell>
                    </TableRow>
                  ))}
                  {rows.length === 0 && (
                    <TableRow>
                      <TableCell colSpan={9} className="py-8 text-center text-sm text-muted-foreground">
                        {t('holding.table.empty', 'В группе нет ни одной действующей компании со строками сводки.')}
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
                {rows.length > 0 && (
                  <TableFooter>
                    <TableRow>
                      <TableCell className="font-semibold">{t('holding.table.totalsRow', 'Итого по группе')}</TableCell>
                      <TableCell className="text-right font-semibold tabular-nums">
                        {formatNumber(headcountTotals?.employees_active ?? null)} / {formatNumber(headcountTotals?.employees_total ?? null)}
                      </TableCell>
                      <TableCell className="text-right font-semibold tabular-nums">
                        {formatNumber(headcountTotals?.staffing_headcount ?? null)}
                      </TableCell>
                      <TableCell className="text-right font-semibold tabular-nums">
                        {formatNumber(headcountTotals?.staffing_payroll ?? null)}
                      </TableCell>
                      <TableCell className="text-right font-semibold tabular-nums">
                        {formatNumber(projectsTotals?.projects_active ?? null)}
                      </TableCell>
                      <TableCell className="text-right font-semibold tabular-nums">
                        {formatNumber(projectsTotals?.sites_active ?? null)}
                      </TableCell>
                      <TableCell className="text-right font-semibold tabular-nums">
                        {formatNumber(projectsTotals?.tasks_open ?? null)}
                      </TableCell>
                      <TableCell className="text-right font-semibold tabular-nums">
                        {formatNumber(projectsTotals?.tasks_overdue ?? null)}
                      </TableCell>
                      {/* Дату последнего отчёта в totals не складываем — бэкенд её тоже не отдаёт. */}
                      <TableCell className="text-right">{DASH}</TableCell>
                    </TableRow>
                  </TableFooter>
                )}
              </Table>
            </section>
          </>
        )}
      </main>
      <Footer />
    </div>
  );
};

export default GroupSummary;
