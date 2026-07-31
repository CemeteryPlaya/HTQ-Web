/**
 * Словарь план/факта: пороги SPI, тон отставания, формат прогноза.
 *
 * Пороговые значения продублированы с бэкенда (`plan_fact_service`)
 * сознательно: сервер отдаёт УЖЕ посчитанные флаги, а эти константы нужны
 * фронту только чтобы подписать легенду и покрасить бейдж. Считать по ним
 * заново нельзя — единственный источник вердикта это `node.flags`.
 *
 * Тон расхождения (`varianceTone`, `VARIANCE_CLASS`, `formatDelta`) берётся
 * из `lib/tasks/roadmap.ts`, а не пишется заново: правило «null это не
 * ноль» одно на весь модуль, и второй набор цветов разъехался бы с первым.
 */
import type { TFunction } from 'i18next';

import type { PlanFactNode, SCurvePoint } from '@/types/tasks';
import { VARIANCE_CLASS, varianceTone } from './roadmap';

export const SPI_WARNING = 0.95;
export const SPI_CRITICAL = 0.90;
/** Выше этого опережение считается поводом посмотреть, откуда ресурсы. */
export const SPI_AHEAD = 1.05;

/**
 * Как показать узел. Не то же самое, что `VarianceTone`: там речь про
 * расхождение одного числа, здесь — про состояние работ целиком.
 */
export type PlanFactTone = 'unknown' | 'critical' | 'warning' | 'onTrack'
  | 'ahead';

export interface PlanFactToneMeta {
  badgeClass: string;
  textClass: string;
  labelKey: string;
}

export const PLAN_FACT_TONE: Record<PlanFactTone, PlanFactToneMeta> = {
  unknown: {
    badgeClass: 'bg-muted text-muted-foreground',
    textClass: 'text-muted-foreground',
    labelKey: 'tasks.planFact.tone.unknown',
  },
  critical: {
    badgeClass: 'bg-red-600 text-white',
    textClass: 'text-red-600 dark:text-red-400',
    labelKey: 'tasks.planFact.tone.critical',
  },
  warning: {
    badgeClass: 'bg-amber-500 text-white',
    textClass: 'text-amber-600 dark:text-amber-400',
    labelKey: 'tasks.planFact.tone.warning',
  },
  onTrack: {
    badgeClass: 'bg-green-500 text-white',
    textClass: 'text-green-600 dark:text-green-400',
    labelKey: 'tasks.planFact.tone.onTrack',
  },
  ahead: {
    badgeClass: 'bg-blue-600 text-white',
    textClass: 'text-blue-600 dark:text-blue-400',
    labelKey: 'tasks.planFact.tone.ahead',
  },
};

export const PLAN_FACT_TONE_ORDER: readonly PlanFactTone[] = [
  'critical', 'warning', 'onTrack', 'ahead', 'unknown',
] as const;

/**
 * Тон узла. `null`-SPI — «сравнивать не с чем», и это `unknown`, а не
 * «всё хорошо»: пакет без плана не заслужил зелёного бейджа.
 */
export const spiTone = (spi: number | null | undefined): PlanFactTone => {
  if (spi === null || spi === undefined) return 'unknown';
  if (spi < SPI_CRITICAL) return 'critical';
  if (spi < SPI_WARNING) return 'warning';
  if (spi > SPI_AHEAD) return 'ahead';
  return 'onTrack';
};

export const spiToneMeta = (spi: number | null | undefined): PlanFactToneMeta =>
  PLAN_FACT_TONE[spiTone(spi)];

export const spiLabel = (
  spi: number | null | undefined,
  t: TFunction | ((key: string, fallback?: string) => string),
): string => {
  const tone = spiTone(spi);
  return (t as (key: string, fallback?: string) => string)(
    PLAN_FACT_TONE[tone].labelKey, tone,
  );
};

/** `SPI 0.87` / `SPI —`. Три знака: 0.95 и 0.949 — разные вердикты. */
export const formatSpi = (spi: number | null | undefined): string =>
  spi === null || spi === undefined ? '—' : spi.toFixed(2);

/** `92.3 %` / `—`. Прочерк, когда считать не из чего. */
export const formatPercent = (value: number | null | undefined): string =>
  value === null || value === undefined ? '—' : `${value} %`;

/**
 * Отставание словами: `+29 дн (6.3 %)`. Знак обязателен — без него «29»
 * не читается как отставание, а «6.3 %» без базы вообще ни о чём.
 */
export const formatLag = (
  node: Pick<PlanFactNode, 'lag_days' | 'lag_pct'>,
  t: (key: string, fallback?: string) => string,
): string => {
  if (node.lag_days === null || node.lag_days === undefined) return '—';
  const days = node.lag_days > 0 ? `+${node.lag_days}` : String(node.lag_days);
  const unit = t('tasks.planFact.days', 'дн.');
  if (node.lag_pct === null || node.lag_pct === undefined) {
    return `${days} ${unit}`;
  }
  return `${days} ${unit} (${Math.abs(node.lag_pct)} %)`;
};

/** Класс для колонки отставания — переиспользует общий тон расхождения. */
export const lagClass = (lagDays: number | null | undefined): string =>
  VARIANCE_CLASS[varianceTone(lagDays)];

/** Известные серверные флаги. Незнакомый флаг не ломает вёрстку. */
export const FLAG_LABELS: Record<string, string> = {
  critical: 'tasks.planFact.flags.critical',
  warning: 'tasks.planFact.flags.warning',
  ahead: 'tasks.planFact.flags.ahead',
  stalled: 'tasks.planFact.flags.stalled',
  has_stalled: 'tasks.planFact.flags.hasStalled',
  unrealistic: 'tasks.planFact.flags.unrealistic',
};

export const flagLabel = (
  flag: string,
  t: (key: string, fallback?: string) => string,
): string => t(FLAG_LABELS[flag] ?? flag, flag);

/**
 * Разложить дерево в плоские строки таблицы с уровнем вложенности.
 *
 * Таблица, а не вложенные списки: у проекта площадки, блоки и пакеты, и
 * читать их надо колонками (план | факт | SPI | откл.), а колонки в дереве
 * из `<ul>` не выравниваются.
 */
export interface FlatRow {
  node: PlanFactNode;
  depth: number;
}

export const flattenTree = (root: PlanFactNode, depth = 0): FlatRow[] => [
  { node: root, depth },
  ...root.children.flatMap((child) => flattenTree(child, depth + 1)),
];

/**
 * Точки S-кривой к виду, который ест recharts.
 *
 * `null` сохраняются как `null`, а не превращаются в `0`: recharts рвёт
 * линию на `null`, и это ровно то, что нужно — факта после отчётной даты
 * нет, и продолжать линию по горизонтали значило бы врать.
 */
export const toChartSeries = (series: SCurvePoint[]) =>
  series.map((point) => ({
    date: point.date,
    plan: point.plan_cum,
    fact: point.fact_cum,
  }));
