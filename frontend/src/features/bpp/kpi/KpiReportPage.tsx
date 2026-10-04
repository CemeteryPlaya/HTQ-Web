/**
 * Отчёт R-01 «KPI снабжения» (ТЗ §12.5–12.6; план этапа 5 A, задача 7).
 *
 * - Фильтры — период по дате выбора, покупатель, проект, статья — в адресе
 *   страницы; смена перечитывает отчёт. Пустой список выбора не молчит:
 *   рядом `PrerequisiteNotice`. Неверная дата или «по» раньше «с» — ошибка
 *   под полями, запроса нет (как у дашборда оплат).
 * - Доля `null` — «—» (подано ноль); деньги — `formatMoney` над строкой
 *   сервера, без `Number`.
 * - Ячейки «Выбрано», «Подтверждено», «Экономия», «Удорожание», «К своему
 *   документу» — кнопки: открывают `KpiRecordsDrawer` с отбором ячейки
 *   (покупатель, статус, «к своему документу»). «Экономия» и «Удорожание»
 *   открывают подтверждённые записи целиком — фильтра по знаку экономии у
 *   ручки нет, поэтому заголовок панели так и говорит. «Подано» — по АП, не
 *   по записям KPI, поэтому без перехода.
 * - Список покупателей — из отчёта без фильтра по покупателю: отдельного
 *   справочника СН/ПМ у роли ФД нет (`hr` ей закрыт). Ключ тот же, что у
 *   отчёта без покупателя, — при пустом фильтре запрос один.
 * - «Экспорт xlsx» — сервер отдаёт файл по тем же фильтрам.
 */
import { useEffect, useState } from 'react';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useSearchParams } from 'react-router-dom';
import { Download, Loader2 } from 'lucide-react';
import { toast } from 'sonner';

import { PrerequisiteNotice } from '@/components/common/PrerequisiteNotice';
import { Button } from '@/components/ui/button';
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

import { formatMoney } from '../format';
import { projectApi, projectKeys } from '../projects/api';
import { refdataApi, refdataKeys } from '../refdata/api';

import {
  filtersFromSearch, FILTER_KEYS, kpiApi, kpiKeys, type KpiFilters, type KpiReportRow,
  type RecordsSelection,
} from './api';
import { KpiRecordsDrawer } from './KpiRecordsDrawer';

const ANY = 'all';
const KZT = 'KZT';

const formatShare = (share: string | null): string =>
  share === null ? '—' : `${share.replace('.', ',')} %`;

interface CellProps {
  value: string;
  label: string;
  onOpen: () => void;
}

function CellButton({ value, label, onOpen }: CellProps) {
  return (
    <button type="button" aria-label={label} onClick={onOpen}
      className="rounded px-1 tabular-nums text-primary hover:underline focus-visible:ring-2 focus-visible:ring-ring">
      {value}
    </button>
  );
}

export function KpiReportPage() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const filters = filtersFromSearch(searchParams);
  const [selection, setSelection] = useState<RecordsSelection | null>(null);
  const [exporting, setExporting] = useState(false);
  const periodInvalid = Boolean(filters.period_from && filters.period_to
    && filters.period_from > filters.period_to);
  const [typedInvalid, setTypedInvalid] = useState({ from: false, to: false });
  const fromInvalid = typedInvalid.from && !filters.period_from;
  const toInvalid = typedInvalid.to && !filters.period_to;
  const dateInvalid = fromInvalid || toInvalid;
  const filtersInvalid = periodInvalid || dateInvalid;
  const [resetCount, setResetCount] = useState(0);

  const setFilter = (key: keyof KpiFilters, value: string) => {
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

  const report = useQuery({
    queryKey: kpiKeys.report(filters),
    queryFn: () => kpiApi.report(filters),
    enabled: !filtersInvalid,
    staleTime: 0,
    refetchOnMount: 'always',
    retry: false,
    placeholderData: keepPreviousData,
  });
  const reportError = report.error;
  useEffect(() => {
    if (reportError) reportApiError(reportError, t('bpp.kpi.loadFailed', 'Не удалось загрузить отчёт'));
  }, [reportError, t]);

  // Покупатели — из отчёта без отбора по покупателю (иначе выбор сузил бы список до себя).
  const buyers = useQuery({
    queryKey: kpiKeys.report({ ...filters, buyer_id: '' }),
    queryFn: () => kpiApi.report({ ...filters, buyer_id: '' }),
    enabled: !filtersInvalid,
    placeholderData: keepPreviousData,
    retry: false,
  });
  const projects = useQuery({
    queryKey: projectKeys.list('', false),
    queryFn: () => projectApi.list('', false),
    staleTime: 5 * 60 * 1000,
  });
  const articles = useQuery({
    queryKey: refdataKeys.list('articles'),
    queryFn: () => refdataApi.articles.list(),
    staleTime: 5 * 60 * 1000,
  });

  const data = filtersInvalid ? undefined : report.data;
  const refreshing = Boolean(data) && report.isFetching && report.isPlaceholderData;
  const buyerOptions = (buyers.data?.rows ?? []).filter((row) => row.buyer_id !== null);

  const runExport = async () => {
    setExporting(true);
    try {
      const outcome = await kpiApi.exportReport(filters);
      if (outcome.kind === 'queued') toast.info(outcome.detail);
    } catch (error) {
      reportApiError(error, t('bpp.kpi.exportFailed', 'Не удалось выгрузить отчёт'));
    } finally {
      setExporting(false);
    }
  };

  const open = (row: KpiReportRow, patch: Omit<RecordsSelection, 'title' | 'buyer_id'>, what: string) =>
    setSelection({
      title: `${row.name ?? t('bpp.kpi.total', 'Итого')} — ${what}`,
      ...(row.buyer_id !== null ? { buyer_id: String(row.buyer_id) } : {}),
      ...patch,
    });

  const renderRow = (row: KpiReportRow, isTotal: boolean) => {
    const name = isTotal ? t('bpp.kpi.total', 'Итого') : (row.name ?? `№${row.buyer_id}`);
    const rowKey = isTotal ? 'total' : String(row.buyer_id);
    const selected = t('bpp.kpi.col.selected', 'Выбрано');
    const confirmed = t('bpp.kpi.col.confirmed', 'Подтверждено');
    const saving = t('bpp.kpi.col.saving', 'Экономия');
    const overspend = t('bpp.kpi.col.overspend', 'Удорожание');
    const confirmedOnly = (what: string) =>
      t('bpp.kpi.confirmedRecords', '{{what}}: подтверждённые записи', { what });
    const own = t('bpp.kpi.col.own', 'К своему документу');
    return (
      <TableRow key={rowKey} data-row={rowKey} className={cn(isTotal && 'bg-muted/50 font-semibold')}>
        <TableCell>{name}</TableCell>
        <TableCell>{isTotal ? '' : row.role_label}</TableCell>
        <TableCell className="text-right tabular-nums">{row.submitted}</TableCell>
        <TableCell className="text-right">
          <CellButton value={String(row.selected)} label={`${name}: ${selected}`}
            onOpen={() => open(row, {}, selected)} />
        </TableCell>
        <TableCell className="text-right">
          <CellButton value={String(row.confirmed)} label={`${name}: ${confirmed}`}
            onOpen={() => open(row, { status: 'confirmed' }, confirmed)} />
        </TableCell>
        <TableCell className="text-right tabular-nums">{formatShare(row.share_pct)}</TableCell>
        <TableCell className="text-right">
          <CellButton value={formatMoney(row.saving, KZT)} label={`${name}: ${saving}`}
            onOpen={() => open(row, { status: 'confirmed' }, confirmedOnly(saving))} />
        </TableCell>
        <TableCell className="text-right">
          <CellButton value={formatMoney(row.overspend, KZT)} label={`${name}: ${overspend}`}
            onOpen={() => open(row, { status: 'confirmed' }, confirmedOnly(overspend))} />
        </TableCell>
        <TableCell className="text-right">
          <CellButton value={String(row.own_document_count)} label={`${name}: ${own}`}
            onOpen={() => open(row, { own_document: '1' }, own)} />
        </TableCell>
      </TableRow>
    );
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-2xl font-bold tracking-tight">{t('bpp.kpi.title', 'KPI снабжения')}</h2>
        <Button type="button" variant="outline" disabled={exporting || filtersInvalid} onClick={runExport}>
          {exporting ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <Download className="mr-1.5 h-4 w-4" />}
          {t('bpp.kpi.export', 'Экспорт xlsx')}
        </Button>
      </div>

      <section aria-label={t('bpp.kpi.filters', 'Фильтры')} className="space-y-2">
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label className="mb-1 block text-xs text-muted-foreground" htmlFor="kpi-from">
              {t('bpp.kpi.periodFrom', 'Выбор с')}
            </label>
            <DateInput key={`from-${resetCount}`} id="kpi-from" aria-label={t('bpp.kpi.periodFrom', 'Выбор с')}
              value={filters.period_from} invalid={fromInvalid}
              onValidityChange={(invalid) => setTypedInvalid((c) => ({ ...c, from: invalid }))}
              onChange={(value) => setFilter('period_from', value)} />
          </div>
          <div>
            <label className="mb-1 block text-xs text-muted-foreground" htmlFor="kpi-to">
              {t('bpp.kpi.periodTo', 'Выбор по')}
            </label>
            <DateInput key={`to-${resetCount}`} id="kpi-to" aria-label={t('bpp.kpi.periodTo', 'Выбор по')}
              value={filters.period_to} invalid={toInvalid}
              onValidityChange={(invalid) => setTypedInvalid((c) => ({ ...c, to: invalid }))}
              onChange={(value) => setFilter('period_to', value)} />
          </div>

          <div className="min-w-48">
            <label className="mb-1 block text-xs text-muted-foreground" htmlFor="kpi-buyer">
              {t('bpp.kpi.buyer', 'Снабженец')}
            </label>
            <Select value={filters.buyer_id || ANY} onValueChange={(value) => setFilter('buyer_id', value)}>
              <SelectTrigger id="kpi-buyer" aria-label={t('bpp.kpi.buyer', 'Снабженец')}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ANY}>{t('bpp.kpi.allBuyers', 'Все')}</SelectItem>
                {filters.buyer_id && !buyerOptions.some((row) => String(row.buyer_id) === filters.buyer_id) && (
                  <SelectItem value={filters.buyer_id}>{`№${filters.buyer_id}`}</SelectItem>
                )}
                {buyerOptions.map((row) => (
                  <SelectItem key={row.buyer_id} value={String(row.buyer_id)}>
                    {row.name ?? `№${row.buyer_id}`}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <PrerequisiteNotice variant="inline" items={[{
              when: buyers.isSuccess && buyerOptions.length === 0,
              text: t('bpp.kpi.noBuyers', 'За период нет записей и поданных альтернатив — выбирать некого'),
            }, {
              when: buyers.isError,
              text: t('bpp.kpi.buyersFailed', 'Не удалось загрузить список — фильтр по снабженцу недоступен'),
            }]} />
          </div>

          <div className="min-w-48">
            <label className="mb-1 block text-xs text-muted-foreground" htmlFor="kpi-project">
              {t('bpp.kpi.project', 'Проект')}
            </label>
            <Select value={filters.project_id || ANY} onValueChange={(value) => setFilter('project_id', value)}>
              <SelectTrigger id="kpi-project" aria-label={t('bpp.kpi.project', 'Проект')}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ANY}>{t('bpp.kpi.allProjects', 'Все проекты')}</SelectItem>
                {(projects.data ?? []).map((project) => (
                  <SelectItem key={project.id} value={project.id}>{`${project.code} — ${project.name}`}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <PrerequisiteNotice variant="inline" items={[{
              when: projects.isSuccess && projects.data.length === 0,
              text: t('bpp.kpi.noProjects', 'Доступных проектов нет —'),
              to: '/bpp/projects',
              linkText: t('bpp.kpi.toProjects', 'перейти в реестр проектов'),
            }, {
              when: projects.isError,
              text: t('bpp.kpi.projectsFailed', 'Не удалось загрузить проекты — фильтр по проекту недоступен'),
            }]} />
          </div>

          <div className="min-w-48">
            <label className="mb-1 block text-xs text-muted-foreground" htmlFor="kpi-article">
              {t('bpp.kpi.article', 'Статья')}
            </label>
            <Select value={filters.article_id || ANY} onValueChange={(value) => setFilter('article_id', value)}>
              <SelectTrigger id="kpi-article" aria-label={t('bpp.kpi.article', 'Статья')}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ANY}>{t('bpp.kpi.allArticles', 'Все статьи')}</SelectItem>
                {(articles.data ?? []).map((article) => (
                  <SelectItem key={article.id} value={article.id}>{`${article.code} — ${article.name}`}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <PrerequisiteNotice variant="inline" items={[{
              when: articles.isSuccess && articles.data.length === 0,
              text: t('bpp.kpi.noArticles', 'Справочник статей пуст —'),
              to: '/bpp/refdata',
              linkText: t('bpp.kpi.toRefdata', 'перейти в справочники'),
            }, {
              when: articles.isError,
              text: t('bpp.kpi.articlesFailed', 'Не удалось загрузить статьи — фильтр по статье недоступен'),
            }]} />
          </div>

          {hasFilters && (
            <Button type="button" variant="ghost" onClick={resetFilters}>
              {t('bpp.kpi.reset', 'Сбросить')}
            </Button>
          )}
        </div>
        {periodInvalid && (
          <p role="alert" className="text-sm text-destructive">
            {t('bpp.kpi.periodOrder', 'Дата «по» раньше даты «с»')}
          </p>
        )}
        {dateInvalid && !periodInvalid && (
          <p role="alert" className="text-sm text-destructive">
            {t('bpp.kpi.dateInvalid', 'Дата введена неверно — отчёт не обновлён')}
          </p>
        )}
      </section>

      {!data && report.isLoading && <Skeleton className="h-40 w-full" />}
      {data && (
        <div className={cn('overflow-x-auto', refreshing && 'opacity-60')} aria-busy={refreshing}>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t('bpp.kpi.col.name', 'Покупатель')}</TableHead>
                <TableHead>{t('bpp.kpi.col.role', 'Роль')}</TableHead>
                <TableHead className="text-right">{t('bpp.kpi.col.submitted', 'Подано')}</TableHead>
                <TableHead className="text-right">{t('bpp.kpi.col.selected', 'Выбрано')}</TableHead>
                <TableHead className="text-right">{t('bpp.kpi.col.confirmed', 'Подтверждено')}</TableHead>
                <TableHead className="text-right">{t('bpp.kpi.col.share', 'Доля')}</TableHead>
                <TableHead className="text-right">{t('bpp.kpi.col.saving', 'Экономия')}</TableHead>
                <TableHead className="text-right">{t('bpp.kpi.col.overspend', 'Удорожание')}</TableHead>
                <TableHead className="text-right">{t('bpp.kpi.col.own', 'К своему документу')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.rows.length === 0 && (
                <TableRow>
                  <TableCell colSpan={9} className="text-center text-muted-foreground">
                    {t('bpp.kpi.empty', 'За период данных нет')}
                  </TableCell>
                </TableRow>
              )}
              {data.rows.map((row) => renderRow(row, false))}
              {renderRow(data.total, true)}
            </TableBody>
          </Table>
        </div>
      )}

      {selection && (
        <KpiRecordsDrawer filters={filters} selection={selection} onClose={() => setSelection(null)} />
      )}
    </div>
  );
}

export default KpiReportPage;
