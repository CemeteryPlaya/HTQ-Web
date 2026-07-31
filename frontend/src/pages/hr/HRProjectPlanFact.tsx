/**
 * HRProjectPlanFact — дашборд план/факта проекта.
 *
 * Отвечает на четыре вопроса руководителя: где мы против плана, когда
 * закончим при нынешнем темпе, на сколько отстаём и по каким узлам.
 *
 * Отчётная дата (`?date=`) — не украшение, а параметр расчёта: прогноз и
 * проценты на 5 июня и на 20 июня это разные ответы. По умолчанию сегодня.
 *
 * Круговых диаграмм здесь нет намеренно (SPEC §6): доля выполненного во
 * времени читается кривой, а не сектором, а сравнение узлов — таблицей с
 * колонками, которые можно выровнять и отсортировать глазом.
 */
import React, { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  Area, AreaChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip,
  XAxis, YAxis,
} from 'recharts';
import { AlertCircle, ArrowLeft, CalendarClock, Gauge, TrendingDown } from 'lucide-react';

import { TasksLayout } from '@/components/tasks/TasksLayout';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { fetchProjectPlanFact } from '@/api/tasks';
import {
  flagLabel, flattenTree, formatLag, formatPercent, formatSpi, lagClass,
  spiToneMeta, toChartSeries,
} from '@/lib/tasks/planFact';
import type { PlanFactNode } from '@/types/tasks';

/** Цвета те же, что у «Создано vs Решено» в отчётах — один язык графиков. */
const PLAN_COLOR = '#3b82f6';
const FACT_COLOR = '#22c55e';

const SummaryCard: React.FC<{
  icon: React.ReactNode; label: string; value: string; hint?: string;
  tone?: string;
}> = ({ icon, label, value, hint, tone }) => (
  <Card>
    <CardContent className="p-4">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        {icon}{label}
      </div>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${tone ?? ''}`}>
        {value}
      </p>
      {hint && <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>}
    </CardContent>
  </Card>
);

const HRProjectPlanFact: React.FC = () => {
  const { t } = useTranslation();
  const { id } = useParams<{ id: string }>();
  const projectId = Number(id);

  // Пустая строка = «сегодня»: сервер подставит текущую дату сам, и
  // хардкодить её на клиенте значило бы разъехаться с ним на часовых поясах.
  const [dataDate, setDataDate] = useState('');

  const { data: root, isLoading, error } = useQuery({
    queryKey: ['plan-fact', 'project', projectId, dataDate],
    queryFn: () => fetchProjectPlanFact(projectId,
                                        dataDate ? { date: dataDate } : undefined),
    enabled: Number.isFinite(projectId),
  });

  const rows = useMemo(
    () => (root ? flattenTree(root).slice(1) : []),   // без самого проекта
    [root],
  );
  const chart = useMemo(() => toChartSeries(root?.series ?? []), [root]);

  if (isLoading) {
    return (
      <TasksLayout title={t('tasks.planFact.title', 'План и факт')}>
        <p className="text-center text-muted-foreground py-10">
          {t('common.loading', 'Загрузка...')}
        </p>
      </TasksLayout>
    );
  }

  if (error || !root) {
    return (
      <TasksLayout title={t('tasks.planFact.title', 'План и факт')}>
        <div className="flex items-center gap-2 justify-center text-red-500 py-10">
          <AlertCircle className="h-5 w-5" />
          {t('tasks.projects.loadError', 'Не удалось загрузить проекты')}
        </div>
      </TasksLayout>
    );
  }

  const tone = spiToneMeta(root.spi);

  return (
    <TasksLayout title={root.name}
                 subtitle={t('tasks.planFact.title', 'План и факт')}>
      <div className="flex flex-wrap items-end justify-between gap-3 mb-4">
        <Button asChild variant="ghost" size="sm">
          <Link to="/manage/projects">
            <ArrowLeft className="h-4 w-4 mr-1" />
            {t('tasks.nav.projects', 'Проекты')}
          </Link>
        </Button>
        <div>
          <Label htmlFor="data-date" className="text-xs text-muted-foreground">
            {t('tasks.planFact.dataDate', 'Отчётная дата')}
          </Label>
          <Input
            id="data-date" type="date" className="h-9 w-[170px]"
            value={dataDate}
            onChange={(event) => setDataDate(event.target.value)}
          />
        </div>
      </div>

      {/* Четыре числа, ради которых страницу открывают */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <SummaryCard
          icon={<Gauge className="h-3.5 w-3.5" />}
          label={t('tasks.planFact.fact', 'Факт')}
          value={formatPercent(root.fact_pct)}
          hint={`${t('tasks.planFact.plan', 'План')}: ${formatPercent(root.plan_pct)}`}
        />
        <SummaryCard
          icon={<Badge className={tone.badgeClass} variant="secondary">SPI</Badge>}
          label={t('tasks.planFact.spi', 'SPI')}
          value={formatSpi(root.spi)}
          tone={tone.textClass}
        />
        <SummaryCard
          icon={<CalendarClock className="h-3.5 w-3.5" />}
          label={t('tasks.planFact.forecast', 'Прогноз')}
          value={root.forecast_end ?? '—'}
          hint={root.plan_end_date
            ? `${t('tasks.planFact.plan', 'План')}: ${root.plan_end_date}`
            : undefined}
        />
        <SummaryCard
          icon={<TrendingDown className="h-3.5 w-3.5" />}
          label={t('tasks.planFact.lag', 'Отклонение')}
          value={formatLag(root, t)}
          tone={lagClass(root.lag_days)}
        />
      </div>

      {root.flags.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {root.flags.map((flag) => (
            <Badge key={flag} variant="outline">{flagLabel(flag, t)}</Badge>
          ))}
        </div>
      )}

      {/* S-кривая */}
      <Card className="mt-4">
        <CardHeader>
          <CardTitle className="text-base">
            {t('tasks.planFact.sCurve', 'S-кривая')}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {chart.length === 0 ? (
            <p className="text-sm text-muted-foreground py-8 text-center">
              {t('tasks.dailyReports.empty', 'Отчётов пока нет')}
            </p>
          ) : (
            <ResponsiveContainer width="100%" height={320}>
              <AreaChart data={chart}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" fontSize={11} />
                <YAxis />
                <Tooltip />
                <Legend />
                <Area
                  type="monotone" dataKey="plan"
                  name={t('tasks.planFact.plan', 'План')}
                  stroke={PLAN_COLOR} fill={`${PLAN_COLOR}30`} strokeWidth={2}
                  // Линия плана известна до конца срока и не должна рваться
                  // на днях без отчётов.
                  connectNulls
                />
                <Area
                  type="monotone" dataKey="fact"
                  name={t('tasks.planFact.fact', 'Факт')}
                  stroke={FACT_COLOR} fill={`${FACT_COLOR}40`} strokeWidth={2}
                  // А факт рвётся намеренно: после отчётной даты его нет, и
                  // тянуть линию горизонтально значило бы врать.
                  connectNulls={false}
                />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </CardContent>
      </Card>

      {/* Разбивка по уровням */}
      <Card className="mt-4">
        <CardHeader>
          <CardTitle className="text-base">
            {t('tasks.pages.roadmaps.title', 'Роудмапы')}
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-0">
          {rows.length === 0 ? (
            <p className="text-sm text-muted-foreground py-2">
              {t('tasks.pages.roadmaps.empty', 'Роудмапов пока нет')}
            </p>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t('tasks.pages.roadmaps.name', 'Название')}</TableHead>
                    <TableHead className="text-right">
                      {t('tasks.planFact.plan', 'План')}
                    </TableHead>
                    <TableHead className="text-right">
                      {t('tasks.planFact.fact', 'Факт')}
                    </TableHead>
                    <TableHead className="text-right">SPI</TableHead>
                    <TableHead className="text-right">
                      {t('tasks.planFact.forecast', 'Прогноз')}
                    </TableHead>
                    <TableHead className="text-right">
                      {t('tasks.planFact.lag', 'Отклонение')}
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map(({ node, depth }) => (
                    <PlanFactRow key={`${node.kind}-${node.id}`} node={node}
                                 depth={depth} t={t} />
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </TasksLayout>
  );
};

/** Значок уровня: площадка / блок / пакет работ. */
const KIND_MARK: Record<string, string> = {
  site: '◈', block: '▣', roadmap: '▸',
};

const PlanFactRow: React.FC<{
  node: PlanFactNode; depth: number;
  t: (key: string, fallback?: string) => string;
}> = ({ node, depth, t }) => {
  const tone = spiToneMeta(node.spi);
  return (
    <TableRow>
      <TableCell>
        <span className="inline-flex items-center gap-2"
              style={{ paddingLeft: `${(depth - 1) * 16}px` }}>
          <span className="text-xs text-muted-foreground">
            {KIND_MARK[node.kind] ?? '·'}
          </span>
          {/* Ссылка только у роудмапа: своя карточка с задачами и «по дням»
              есть у него одного. Кликабельная строка целиком потребовала бы
              таблицы внутри ячейки — за читаемость разметки платить этим
              не стоит. */}
          {node.kind === 'roadmap' ? (
            <Link to={`/tasks/roadmaps/${node.id}`}
                  className="text-primary hover:underline">
              {node.name}
            </Link>
          ) : node.name}
          {node.task_count ? (
            <span className="text-xs text-muted-foreground">
              · {node.task_count}
            </span>
          ) : null}
        </span>
      </TableCell>
      <TableCell className="text-right tabular-nums">
        {formatPercent(node.plan_pct)}
      </TableCell>
      <TableCell className="text-right tabular-nums font-medium">
        {formatPercent(node.fact_pct)}
      </TableCell>
      <TableCell className={`text-right tabular-nums ${tone.textClass}`}>
        {formatSpi(node.spi)}
      </TableCell>
      <TableCell className="text-right tabular-nums text-xs">
        {node.forecast_end ?? '—'}
      </TableCell>
      <TableCell className={`text-right tabular-nums ${lagClass(node.lag_days)}`}>
        {formatLag(node, t)}
      </TableCell>
    </TableRow>
  );
};

export default HRProjectPlanFact;
