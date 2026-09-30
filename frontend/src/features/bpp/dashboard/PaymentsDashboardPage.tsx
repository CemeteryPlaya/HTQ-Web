/**
 * Дашборд D-01 «Оплаты» (ТЗ §11.5, REQ-018; план этапа 4 A, задача 6).
 *
 * - Фильтры — период по дате платежа, проект, статья, контрагент, автор
 *   счёта — живут в адресе страницы (`?period_from=…&project_id=…`): смена
 *   фильтра меняет ключ запроса и перечитывает дашборд, а «Назад» из реестра
 *   возвращает тот же отбор. Пока перечитывается, на экране прежние цифры,
 *   приглушённые (`keepPreviousData`), а не скелетон. Выпадающий список,
 *   наполняемый запросом, пустым не бывает молча — рядом `PrerequisiteNotice`.
 * - Авторы счёта — из ответа дашборда (`authors`: авторы видимых счетов), не
 *   из кадров: у ролей дашборда прав `hr` нет.
 * - Неверная или недописанная дата периода не снимает фильтр молча: ошибка
 *   под полями, запроса нет — как при «по» раньше «с».
 * - Карточка показателя — ссылка на реестр счетов с теми же фильтрами; адрес
 *   собирает сервер (`indicators[].link`), поэтому число на карточке и
 *   `total` реестра совпадают. Ссылки нет (`null` — «Несопоставленные
 *   списания» без права `bpp.bank` view) — карточка без перехода.
 * - Период применяется сервером только к банковским показателям и графикам
 *   (D-S4-6); очереди счетов — на текущий момент. Подпись под фильтрами это
 *   объясняет, иначе «период не влияет на „К оплате“» выглядит ошибкой.
 * - Столбцы «Лимит / Задействовано / Оплачено факт» — по статьям выбранного
 *   проекта; без проекта — подсказка выбрать проект.
 * - Подмодуль счетов, банка или бюджетов выключен у компании (`sections`) —
 *   экран так и пишет, а не «данных нет».
 * - Линия «Оплачено по банку» по неделям и топ-10 контрагентов.
 * - Деньги на экране — только `formatMoney` над строкой сервера
 *   (`chartData.ts`): число recharts — лишь высота столбца.
 * - Свежие цифры при каждом открытии (`staleTime: 0`, `refetchOnMount:
 *   'always'`); экраны сверки после загрузки и своих действий сбрасывают
 *   `DASHBOARD_KEY`.
 */
import { useEffect, useMemo, useState } from 'react';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link, useSearchParams } from 'react-router-dom';
import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';

import { PrerequisiteNotice } from '@/components/common/PrerequisiteNotice';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { DateInput } from '@/components/ui/date-input';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { reportApiError } from '@/lib/apiError';
import { cn } from '@/lib/utils';

import { CounterpartyPicker } from '../counterparties/CounterpartyPicker';
import { formatDateTime, formatMoney } from '../format';
import { projectApi, projectKeys } from '../projects/api';
import { refdataApi, refdataKeys } from '../refdata/api';

import {
  dashboardApi, dashboardKeys, filtersFromSearch, FILTER_KEYS, type DashboardFilters,
  type DashboardIndicator, type DashboardSections,
} from './api';
import { articleBars, axisTick, tooltipText, weekPoints } from './chartData';

/** Значение «фильтр не задан» у выпадающих списков (Radix не берёт `''`). */
const ANY = 'all';
const KZT = 'KZT';

/** Пока ответа нет — подмодули считаются включёнными: подписи «выключено»
 * появляются только по слову сервера. */
const ALL_SECTIONS: DashboardSections = { invoices: true, bank: true, budget: true };

const SERIES_COLORS = {
  limit: '#94a3b8',
  committed: '#f59e0b',
  paid_fact: '#10b981',
  weekly: '#3b82f6',
} as const;

function IndicatorCard({ indicator }: { indicator: DashboardIndicator }) {
  const { t } = useTranslation();
  const label = t(`bpp.dashboard.indicator.${indicator.key}`, indicator.label);
  const body = (
    <Card className={indicator.link ? 'h-full transition-colors hover:border-primary' : 'h-full'}>
      <CardContent className="space-y-1 py-4">
        <div className="text-sm text-muted-foreground">{label}</div>
        <div className="text-2xl font-semibold tabular-nums">
          {t('bpp.dashboard.count', '{{n}} шт.', { n: indicator.count })}
        </div>
        <div className="text-sm tabular-nums">{formatMoney(indicator.amount, KZT)}</div>
      </CardContent>
    </Card>
  );
  if (!indicator.link) return <div data-indicator={indicator.key}>{body}</div>;
  return (
    <Link to={indicator.link} data-indicator={indicator.key}
      className="block rounded-lg focus:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      {body}
    </Link>
  );
}

export function PaymentsDashboardPage() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const filters = useMemo(() => filtersFromSearch(searchParams), [searchParams]);
  const periodInvalid = Boolean(filters.period_from && filters.period_to
    && filters.period_from > filters.period_to);
  // Набрано, но не дата («31.02.2026», недописанное): поле отдаёт `''`, и без
  // этого флага дашборд молча показал бы всё время при видимой дате в поле.
  // Дата в адресе есть — поле её и показывает (пришла снаружи, «Назад»).
  const [typedInvalid, setTypedInvalid] = useState({ from: false, to: false });
  const fromInvalid = typedInvalid.from && !filters.period_from;
  const toInvalid = typedInvalid.to && !filters.period_to;
  const dateInvalid = fromInvalid || toInvalid;
  const filtersInvalid = periodInvalid || dateInvalid;
  // Сброс перерисовывает поля дат: поле с неверным текстом уже отдало `''`
  // и пустое значение снаружи за сброс не примет.
  const [resetCount, setResetCount] = useState(0);

  const setFilter = (key: keyof DashboardFilters, value: string) => {
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      if (value && value !== ANY) next.set(key, value); else next.delete(key);
      return next;
    }, { replace: true });
  };
  const hasFilters = FILTER_KEYS.some((key) => filters[key]) || dateInvalid;
  const resetFilters = () => {
    setTypedInvalid({ from: false, to: false });
    setResetCount((count) => count + 1);
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      FILTER_KEYS.forEach((key) => next.delete(key));
      return next;
    }, { replace: true });
  };

  const dashboard = useQuery({
    queryKey: dashboardKeys.payments(filters),
    queryFn: () => dashboardApi.payments(filters),
    enabled: !filtersInvalid,
    // ТЗ §11.5: «Обновление — при каждом открытии».
    staleTime: 0,
    refetchOnMount: 'always',
    retry: false,
    // Смена фильтра не роняет экран в скелетон: прежние цифры видны
    // приглушёнными, пока не придут новые.
    placeholderData: keepPreviousData,
  });
  const dashboardError = dashboard.error;
  useEffect(() => {
    if (dashboardError) {
      reportApiError(dashboardError, t('bpp.dashboard.loadFailed', 'Не удалось загрузить дашборд оплат'));
    }
  }, [dashboardError, t]);

  const projects = useQuery({
    queryKey: projectKeys.list('', false),
    queryFn: () => projectApi.list('', false),
    staleTime: 5 * 60 * 1000,
  });
  const articles = useQuery({
    // Все статьи, с архивными: у прошлых счетов статья могла уйти в архив.
    queryKey: refdataKeys.list('articles'),
    queryFn: () => refdataApi.articles.list(),
    staleTime: 5 * 60 * 1000,
  });
  const projectsError = projects.error;
  useEffect(() => {
    if (projectsError) {
      reportApiError(projectsError, t('bpp.dashboard.projectsLoadFailed', 'Не удалось загрузить проекты'));
    }
  }, [projectsError, t]);
  const articlesError = articles.error;
  useEffect(() => {
    if (articlesError) {
      reportApiError(articlesError, t('bpp.dashboard.articlesLoadFailed', 'Не удалось загрузить статьи'));
    }
  }, [articlesError, t]);

  // Неверный фильтр — запроса нет, и прежние цифры не выдаются за ответ на него.
  const data = filtersInvalid ? undefined : dashboard.data;
  const refreshing = Boolean(data) && dashboard.isFetching && dashboard.isPlaceholderData;
  const sections = data?.sections ?? ALL_SECTIONS;
  const paymentsOff = !sections.invoices
    ? t('bpp.dashboard.off.paymentsInvoices', 'Счета на оплату у компании выключены — оплат по счетам нет.')
    : !sections.bank
      ? t('bpp.dashboard.off.paymentsBank', 'Сверка с банком у компании выключена — оплат по банку нет.')
      : null;
  const authors = useMemo(() => (data?.authors ?? []).map((author) => ({
    id: String(author.id),
    name: author.name ?? t('bpp.dashboard.authorById', 'Пользователь №{{id}}', { id: author.id }),
  })), [data, t]);
  const bars = useMemo(() => articleBars(data?.article_chart ?? []), [data]);
  const hasPaidFact = bars.some((bar) => bar.paid_fact !== null);
  const weeks = useMemo(() => weekPoints(data?.weekly_paid ?? []), [data]);

  const seriesName: Record<string, string> = {
    limit: t('bpp.dashboard.limit', 'Лимит'),
    committed: t('bpp.dashboard.committed', 'Задействовано'),
    paid_fact: t('bpp.dashboard.paidFact', 'Оплачено факт'),
    amount: t('bpp.dashboard.paidBank', 'Оплачено по банку'),
  };
  const tooltipFormatter = (_value: unknown, name: unknown, item: { dataKey?: unknown; payload?: unknown }) =>
    [tooltipText(item.dataKey, item.payload), seriesName[String(item.dataKey)] ?? String(name)];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-2xl font-bold tracking-tight">{t('bpp.dashboard.title', 'Дашборд оплат')}</h2>
        {data && (
          <span className="text-sm text-muted-foreground">
            {t('bpp.dashboard.asOf', 'Данные на {{at}}', { at: formatDateTime(data.as_of) })}
          </span>
        )}
      </div>

      <section aria-label={t('bpp.dashboard.filters', 'Фильтры')} className="space-y-2">
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label className="mb-1 block text-xs text-muted-foreground" htmlFor="dash-period-from">
              {t('bpp.dashboard.periodFrom', 'Оплата с')}
            </label>
            <DateInput key={`from-${resetCount}`} id="dash-period-from"
              aria-label={t('bpp.dashboard.periodFrom', 'Оплата с')}
              value={filters.period_from} invalid={fromInvalid}
              onValidityChange={(invalid) => setTypedInvalid((current) => ({ ...current, from: invalid }))}
              onChange={(value) => setFilter('period_from', value)} />
          </div>
          <div>
            <label className="mb-1 block text-xs text-muted-foreground" htmlFor="dash-period-to">
              {t('bpp.dashboard.periodTo', 'Оплата по')}
            </label>
            <DateInput key={`to-${resetCount}`} id="dash-period-to"
              aria-label={t('bpp.dashboard.periodTo', 'Оплата по')}
              value={filters.period_to} invalid={toInvalid}
              onValidityChange={(invalid) => setTypedInvalid((current) => ({ ...current, to: invalid }))}
              onChange={(value) => setFilter('period_to', value)} />
          </div>

          <div className="min-w-48">
            <label className="mb-1 block text-xs text-muted-foreground" htmlFor="dash-project">
              {t('bpp.dashboard.project', 'Проект')}
            </label>
            <Select value={filters.project_id || ANY} onValueChange={(value) => setFilter('project_id', value)}>
              <SelectTrigger id="dash-project" aria-label={t('bpp.dashboard.project', 'Проект')}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ANY}>{t('bpp.dashboard.allProjects', 'Все проекты')}</SelectItem>
                {(projects.data ?? []).map((project) => (
                  <SelectItem key={project.id} value={project.id}>{`${project.code} — ${project.name}`}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <PrerequisiteNotice variant="inline" items={[{
              when: projects.isSuccess && projects.data.length === 0,
              text: t('bpp.dashboard.noProjects', 'Доступных проектов нет —'),
              to: '/bpp/projects',
              linkText: t('bpp.dashboard.toProjects', 'перейти в реестр проектов'),
            }, {
              when: projects.isError,
              text: t('bpp.dashboard.projectsFailed', 'Не удалось загрузить проекты — фильтр по проекту недоступен'),
            }]} />
          </div>

          <div className="min-w-48">
            <label className="mb-1 block text-xs text-muted-foreground" htmlFor="dash-article">
              {t('bpp.dashboard.article', 'Статья')}
            </label>
            <Select value={filters.article_id || ANY} onValueChange={(value) => setFilter('article_id', value)}>
              <SelectTrigger id="dash-article" aria-label={t('bpp.dashboard.article', 'Статья')}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ANY}>{t('bpp.dashboard.allArticles', 'Все статьи')}</SelectItem>
                {(articles.data ?? []).map((article) => (
                  <SelectItem key={article.id} value={article.id}>{`${article.code} — ${article.name}`}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <PrerequisiteNotice variant="inline" items={[{
              when: articles.isSuccess && articles.data.length === 0,
              text: t('bpp.dashboard.noArticles', 'Справочник статей пуст —'),
              to: '/bpp/refdata',
              linkText: t('bpp.dashboard.toRefdata', 'перейти в справочники'),
            }, {
              when: articles.isError,
              text: t('bpp.dashboard.articlesFailed', 'Не удалось загрузить статьи — фильтр по статье недоступен'),
            }]} />
          </div>

          <div className="min-w-56">
            <label className="mb-1 block text-xs text-muted-foreground" htmlFor="dash-counterparty">
              {t('bpp.dashboard.counterparty', 'Контрагент')}
            </label>
            <CounterpartyPicker id="dash-counterparty" value={filters.counterparty_id || null}
              onChange={(id) => setFilter('counterparty_id', id ?? '')} />
          </div>

          <div className="min-w-48">
            <label className="mb-1 block text-xs text-muted-foreground" htmlFor="dash-author">
              {t('bpp.dashboard.author', 'Автор счёта')}
            </label>
            <Select value={filters.author_id || ANY} onValueChange={(value) => setFilter('author_id', value)}>
              <SelectTrigger id="dash-author" aria-label={t('bpp.dashboard.author', 'Автор счёта')}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ANY}>{t('bpp.dashboard.allAuthors', 'Все авторы')}</SelectItem>
                {/* Автор из адреса, которого нет в списке, — всё равно пункт: иначе поле пустое при заданном фильтре. */}
                {filters.author_id && !authors.some((author) => author.id === filters.author_id) && (
                  <SelectItem value={filters.author_id}>
                    {t('bpp.dashboard.authorById', 'Пользователь №{{id}}', { id: filters.author_id })}
                  </SelectItem>
                )}
                {authors.map((author) => (
                  <SelectItem key={author.id} value={author.id}>{author.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <PrerequisiteNotice variant="inline" items={[{
              when: Boolean(data) && !sections.invoices,
              text: t('bpp.dashboard.authorsOff',
                'Счета на оплату у компании выключены — фильтр по автору не действует'),
            }, {
              when: Boolean(data) && sections.invoices && authors.length === 0,
              text: t('bpp.dashboard.noAuthors', 'Видимых вам счетов пока нет — выбрать автора не из кого'),
            }, {
              when: dashboard.isError,
              text: t('bpp.dashboard.authorsFailed',
                'Не удалось загрузить авторов счетов — фильтр по автору недоступен'),
            }]} />
          </div>

          {hasFilters && (
            <Button variant="ghost" size="sm" onClick={resetFilters}>
              {t('bpp.dashboard.resetFilters', 'Сбросить фильтры')}
            </Button>
          )}
        </div>
        {dateInvalid ? (
          <p role="alert" className="text-sm text-destructive">
            {t('bpp.dashboard.dateInvalid', 'Дата периода введена неверно — укажите её полностью: ДД.ММ.ГГГГ.')}
          </p>
        ) : periodInvalid ? (
          <p role="alert" className="text-sm text-destructive">
            {t('bpp.dashboard.periodInvalid', 'Дата «по» раньше даты «с».')}
          </p>
        ) : (
          <p className="text-xs text-muted-foreground">
            {t('bpp.dashboard.periodHint',
              'Период — по дате платежа в выписке: он действует на показатели банка и графики. '
              + 'Очереди счетов показаны на текущий момент.')}
          </p>
        )}
      </section>

      {dashboard.isLoading && !filtersInvalid && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }, (_, index) => <Skeleton key={index} className="h-24" />)}
        </div>
      )}
      {dashboard.isError && (
        <p className="text-sm text-destructive">
          {t('bpp.dashboard.loadFailed', 'Не удалось загрузить дашборд оплат')}
        </p>
      )}

      {data && (
        <div aria-busy={refreshing || undefined}
          className={cn('space-y-6 transition-opacity', refreshing && 'opacity-60')}>
          <section aria-label={t('bpp.dashboard.indicators', 'Показатели')} className="space-y-2">
            {data.indicators.length > 0 && (
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {data.indicators.map((indicator) => (
                  <IndicatorCard key={indicator.key} indicator={indicator} />
                ))}
              </div>
            )}
            {/* Показателей выключенного подмодуля в ответе нет — сказать почему. */}
            {!sections.invoices && (
              <p className="text-sm text-muted-foreground">
                {t('bpp.dashboard.off.invoices',
                  'Счета на оплату у компании выключены — показателей по счетам, фильтра по автору и графиков оплат нет.')}
              </p>
            )}
            {!sections.bank && (
              <p className="text-sm text-muted-foreground">
                {t('bpp.dashboard.off.bank',
                  'Сверка с банком у компании выключена — показателей по выписке, «Оплачено факт» и графиков оплат нет.')}
              </p>
            )}
          </section>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">
                {t('bpp.dashboard.articlesChart', 'Лимит / Задействовано / Оплачено факт по статьям')}
              </CardTitle>
            </CardHeader>
            <CardContent>
              {!sections.budget ? (
                <p className="text-sm text-muted-foreground">
                  {t('bpp.dashboard.off.budget', 'Бюджеты у компании выключены — лимитов по статьям нет.')}
                </p>
              ) : !filters.project_id ? (
                <p className="text-sm text-muted-foreground">
                  {t('bpp.dashboard.pickProject', 'Выберите проект, чтобы увидеть лимиты и оплаты по его статьям.')}
                </p>
              ) : bars.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  {t('bpp.dashboard.noBudget', 'У проекта нет действующего бюджета или доступных вам статей.')}
                </p>
              ) : (
                <ResponsiveContainer width="100%" height={Math.max(260, bars.length * 48)}>
                  <BarChart data={bars} layout="vertical" margin={{ left: 24, right: 24 }}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis type="number" tickFormatter={axisTick} />
                    <YAxis type="category" dataKey="name" width={200} />
                    <Tooltip formatter={tooltipFormatter} />
                    <Legend />
                    <Bar dataKey="limit" name={seriesName.limit} fill={SERIES_COLORS.limit} />
                    <Bar dataKey="committed" name={seriesName.committed} fill={SERIES_COLORS.committed} />
                    {hasPaidFact && (
                      <Bar dataKey="paid_fact" name={seriesName.paid_fact} fill={SERIES_COLORS.paid_fact} />
                    )}
                  </BarChart>
                </ResponsiveContainer>
              )}
            </CardContent>
          </Card>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">
                  {t('bpp.dashboard.weeklyChart', 'Оплачено по банку по неделям, KZT')}
                </CardTitle>
              </CardHeader>
              <CardContent>
                {paymentsOff ? (
                  <p className="text-sm text-muted-foreground">{paymentsOff}</p>
                ) : weeks.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    {t('bpp.dashboard.noPayments', 'Платежей по банку за период нет.')}
                  </p>
                ) : (
                  <ResponsiveContainer width="100%" height={260}>
                    <LineChart data={weeks} margin={{ left: 24, right: 24 }}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="week" />
                      <YAxis tickFormatter={axisTick} width={100} />
                      <Tooltip formatter={tooltipFormatter} />
                      <Line type="monotone" dataKey="amount" name={seriesName.amount}
                        stroke={SERIES_COLORS.weekly} strokeWidth={2} dot />
                    </LineChart>
                  </ResponsiveContainer>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-base">
                  {t('bpp.dashboard.topCounterparties', 'Топ-10 контрагентов по оплатам')}
                </CardTitle>
              </CardHeader>
              <CardContent>
                {paymentsOff ? (
                  <p className="text-sm text-muted-foreground">{paymentsOff}</p>
                ) : data.top_counterparties.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    {t('bpp.dashboard.noPayments', 'Платежей по банку за период нет.')}
                  </p>
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="w-10">{t('bpp.dashboard.rank', '№')}</TableHead>
                        <TableHead>{t('bpp.dashboard.counterparty', 'Контрагент')}</TableHead>
                        <TableHead className="text-right">
                          {t('bpp.dashboard.paidBankKzt', 'Оплачено по банку, KZT')}
                        </TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {data.top_counterparties.map((row, index) => (
                        <TableRow key={row.counterparty_id}>
                          <TableCell>{index + 1}</TableCell>
                          <TableCell>{row.name}</TableCell>
                          <TableCell className="text-right tabular-nums">{formatMoney(row.amount)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}

export default PaymentsDashboardPage;
