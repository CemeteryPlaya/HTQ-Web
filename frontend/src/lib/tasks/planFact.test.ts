import { describe, expect, it } from 'vitest';

import {
    FLAG_LABELS,
    PLAN_FACT_TONE,
    PLAN_FACT_TONE_ORDER,
    flagLabel,
    flattenTree,
    formatLag,
    formatPercent,
    formatSpi,
    spiTone,
    toChartSeries,
} from './planFact';
import type { PlanFactNode } from '@/types/tasks';

const t = (key: string, fallback?: string) => fallback ?? key;

const node = (over: Partial<PlanFactNode> = {}): PlanFactNode => ({
    kind: 'roadmap', id: 1, name: 'Развозка валов',
    plan_start_date: null, plan_end_date: null,
    plan_pct: null, fact_pct: null, spi: null,
    forecast_end: null, forecast_end_plan_rate: null,
    lag_days: null, lag_pct: null, flags: [],
    weighting: null, children: [], series: [],
    ...over,
});

describe('spiTone', () => {
    it('различает «плана нет» и «всё хорошо»', () => {
        // Пакет без плана не заслужил зелёного бейджа — это отдельный тон.
        expect(spiTone(null)).toBe('unknown');
        expect(spiTone(undefined)).toBe('unknown');
        expect(spiTone(1.0)).toBe('onTrack');
        expect(PLAN_FACT_TONE.unknown.badgeClass)
            .not.toBe(PLAN_FACT_TONE.onTrack.badgeClass);
    });

    it('пороги совпадают с серверными', () => {
        expect(spiTone(0.89)).toBe('critical');
        expect(spiTone(0.90)).toBe('warning');   // ровно порог — ещё не critical
        expect(spiTone(0.94)).toBe('warning');
        expect(spiTone(0.95)).toBe('onTrack');   // ровно порог — уже onTrack
    });

    it('заметное опережение помечается отдельно', () => {
        expect(spiTone(1.05)).toBe('onTrack');
        expect(spiTone(1.2)).toBe('ahead');
    });

    it('на каждый тон есть классы и подпись', () => {
        PLAN_FACT_TONE_ORDER.forEach((tone) => {
            expect(PLAN_FACT_TONE[tone].badgeClass).toBeTruthy();
            expect(PLAN_FACT_TONE[tone].textClass).toBeTruthy();
            expect(PLAN_FACT_TONE[tone].labelKey).toContain('tasks.planFact');
        });
    });

    it('таблица покрывает ровно перечисленные тона', () => {
        expect(Object.keys(PLAN_FACT_TONE).sort())
            .toEqual([...PLAN_FACT_TONE_ORDER].sort());
    });
});

describe('форматирование', () => {
    it('SPI с двумя знаками — 0.95 и 0.949 это разные вердикты', () => {
        expect(formatSpi(0.949)).toBe('0.95');
        expect(formatSpi(1)).toBe('1.00');
        expect(formatSpi(null)).toBe('—');
    });

    it('процент прочерком, когда считать не из чего', () => {
        expect(formatPercent(92.3)).toBe('92.3 %');
        expect(formatPercent(0)).toBe('0 %');       // ноль это НЕ прочерк
        expect(formatPercent(null)).toBe('—');
    });

    it('отставание всегда со знаком и с долей плана', () => {
        expect(formatLag(node({ lag_days: 29, lag_pct: 6.3 }), t))
            .toBe('+29 дн. (6.3 %)');
        expect(formatLag(node({ lag_days: -4, lag_pct: -1.2 }), t))
            .toBe('-4 дн. (1.2 %)');
    });

    it('без доли показывает только дни, без плана — прочерк', () => {
        expect(formatLag(node({ lag_days: 5, lag_pct: null }), t)).toBe('+5 дн.');
        expect(formatLag(node({ lag_days: null, lag_pct: null }), t)).toBe('—');
    });
});

describe('flagLabel', () => {
    it('переводит известные флаги', () => {
        expect(FLAG_LABELS.stalled).toBe('tasks.planFact.flags.stalled');
        expect(flagLabel('stalled', t)).toBe('stalled');
    });

    it('незнакомый флаг с сервера не ломает вёрстку', () => {
        expect(flagLabel('brand_new_flag', t)).toBe('brand_new_flag');
    });
});

describe('flattenTree', () => {
    it('раскладывает дерево в строки с глубиной', () => {
        const tree = node({
            kind: 'project', id: 1, name: 'Проект',
            children: [node({
                kind: 'site', id: 2, name: 'Сазаган',
                children: [node({ kind: 'block', id: 3, name: 'Блок 1' })],
            })],
        });
        expect(flattenTree(tree).map((row) => [row.node.kind, row.depth]))
            .toEqual([['project', 0], ['site', 1], ['block', 2]]);
    });

    it('лист даёт одну строку', () => {
        expect(flattenTree(node())).toHaveLength(1);
    });
});

describe('toChartSeries', () => {
    it('сохраняет null, а не превращает его в ноль', () => {
        // recharts рвёт линию на null — ровно то, что нужно: после
        // отчётной даты факта нет, и тянуть линию горизонтально нельзя.
        const chart = toChartSeries([
            { date: '2026-06-01', plan_cum: 10, fact_cum: 8 },
            { date: '2026-06-30', plan_cum: 100, fact_cum: null },
        ]);
        expect(chart).toEqual([
            { date: '2026-06-01', plan: 10, fact: 8 },
            { date: '2026-06-30', plan: 100, fact: null },
        ]);
    });
});
