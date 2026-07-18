import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { Activity, Server, AlertTriangle, CheckCircle2, ExternalLink } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { grafanaSsoUrl } from '@/lib/monitoring';

/**
 * MonitoringWidget — виджет быстрого доступа к мониторингу.
 * Отображает статус Prometheus targets (UP/DOWN) и ссылки на Grafana/Prometheus.
 * Показывается только админам на странице MyProfile.
 */

interface PrometheusTarget {
    labels: Record<string, string>;
    health: 'up' | 'down' | 'unknown';
    lastScrape: string;
    lastScrapeDuration: number;
}

interface TargetGroup {
    activeTargets: PrometheusTarget[];
}

export const MonitoringWidget: React.FC = () => {
    const { data: targets, isLoading, error } = useQuery<PrometheusTarget[]>({
        queryKey: ['prometheus-targets'],
        queryFn: async () => {
            const res = await fetch('/prometheus/api/v1/targets');
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const json = await res.json();
            return (json.data as TargetGroup)?.activeTargets ?? [];
        },
        retry: 1,
        refetchInterval: 30_000, // обновляем каждые 30 секунд
        staleTime: 15_000,
    });

    const upCount = targets?.filter(t => t.health === 'up').length ?? 0;
    const downCount = targets?.filter(t => t.health === 'down').length ?? 0;
    const totalCount = targets?.length ?? 0;

    return (
        <div className="bg-card rounded-3xl border p-6 shadow-sm">
            {/* Header */}
            <div className="flex items-center justify-between mb-5">
                <div className="flex items-center gap-2.5">
                    <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10">
                        <Activity className="h-4.5 w-4.5 text-primary" />
                    </div>
                    <h3 className="text-xl font-bold">Мониторинг</h3>
                </div>
                <div className="flex gap-2">
                    <a
                        href={grafanaSsoUrl()}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-accent hover:text-accent-foreground"
                    >
                        Grafana
                        <ExternalLink className="h-3 w-3" />
                    </a>
                    <a
                        href="/prometheus"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-accent hover:text-accent-foreground"
                    >
                        Prometheus
                        <ExternalLink className="h-3 w-3" />
                    </a>
                </div>
            </div>

            {/* Status summary */}
            {isLoading && (
                <div className="flex items-center gap-2 text-sm text-muted-foreground py-4">
                    <div className="h-4 w-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
                    Загрузка статуса сервисов…
                </div>
            )}

            {error && (
                <div className="flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
                    <AlertTriangle className="h-4 w-4 shrink-0" />
                    <span>
                        Prometheus недоступен. Убедитесь, что мониторинг запущен.
                    </span>
                </div>
            )}

            {targets && !error && (
                <>
                    {/* Summary badges */}
                    <div className="flex gap-3 mb-4">
                        <div className="flex items-center gap-1.5 rounded-lg border bg-background px-3 py-2">
                            <Server className="h-4 w-4 text-muted-foreground" />
                            <span className="text-sm font-medium">{totalCount}</span>
                            <span className="text-xs text-muted-foreground">таргетов</span>
                        </div>
                        <div className="flex items-center gap-1.5 rounded-lg border bg-background px-3 py-2">
                            <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                            <span className="text-sm font-medium">{upCount}</span>
                            <span className="text-xs text-muted-foreground">UP</span>
                        </div>
                        {downCount > 0 && (
                            <div className="flex items-center gap-1.5 rounded-lg border border-red-200 bg-red-50 px-3 py-2 dark:border-red-900 dark:bg-red-950/30">
                                <AlertTriangle className="h-4 w-4 text-red-500" />
                                <span className="text-sm font-medium text-red-700 dark:text-red-300">{downCount}</span>
                                <span className="text-xs text-red-600 dark:text-red-400">DOWN</span>
                            </div>
                        )}
                    </div>

                    {/* Target list */}
                    <div className="space-y-1.5">
                        {targets.map((target, i) => (
                            <div
                                key={`${target.labels.job}-${target.labels.instance}-${i}`}
                                className="flex items-center gap-3 rounded-lg border bg-background px-4 py-2.5"
                            >
                                <div
                                    className={`h-2 w-2 rounded-full shrink-0 ${
                                        target.health === 'up'
                                            ? 'bg-emerald-500 shadow-[0_0_6px_rgba(16,185,129,0.4)]'
                                            : 'bg-red-500 shadow-[0_0_6px_rgba(239,68,68,0.4)]'
                                    }`}
                                />
                                <div className="min-w-0 flex-1">
                                    <p className="truncate text-sm font-medium">
                                        {target.labels.app_name || target.labels.job}
                                    </p>
                                    <p className="truncate text-xs text-muted-foreground">
                                        {target.labels.instance}
                                    </p>
                                </div>
                                <Badge
                                    variant={target.health === 'up' ? 'outline' : 'destructive'}
                                    className="text-[10px] shrink-0"
                                >
                                    {target.health.toUpperCase()}
                                </Badge>
                                <span className="text-[10px] text-muted-foreground tabular-nums shrink-0">
                                    {(target.lastScrapeDuration * 1000).toFixed(0)}ms
                                </span>
                            </div>
                        ))}
                    </div>
                </>
            )}
        </div>
    );
};

export default MonitoringWidget;
