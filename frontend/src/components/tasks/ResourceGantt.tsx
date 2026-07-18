/* ------------------------------------------------------------------ */
/*  Tasks module — Resource-planning Gantt                             */
/*  Строки = ресурсы (сотрудники / техника), отрезки = их задачи.      */
/*  Шкала фиксирована окном [from, to] (планирование, а не факт).      */
/* ------------------------------------------------------------------ */
import React, { useMemo } from 'react';
import {
  parseISO, isValid, differenceInCalendarDays, addDays, startOfMonth,
  addMonths, format,
} from 'date-fns';
import { ru } from 'date-fns/locale';
import { User, Truck } from 'lucide-react';
import type { ResourceRow, ResourceKind } from '@/types/tasks';

const STATUS_COLORS: Record<string, string> = {
  open: '#64748b', in_progress: '#3b82f6', in_review: '#a855f7',
  done: '#22c55e', closed: '#6b7280',
};
const STATUS_LABELS: Record<string, string> = {
  open: 'Открыта', in_progress: 'В работе', in_review: 'На ревью',
  done: 'Готова', closed: 'Закрыта',
};
const KIND_META: Record<ResourceKind, { label: string; icon: typeof User }> = {
  employee: { label: 'Сотрудники', icon: User },
  equipment: { label: 'Техника', icon: Truck },
};

const LABEL_W = 240;

interface Props {
  resources: ResourceRow[];
  /** Окно таймлайна (YYYY-MM-DD). Шкала строится по нему, не по задачам. */
  rangeFrom: string;
  rangeTo: string;
  onTaskClick?: (taskId: string) => void;
}

function parseDate(s?: string | null): Date | null {
  if (!s) return null;
  const d = parseISO(s);
  return isValid(d) ? d : null;
}

const clamp = (v: number) => Math.max(0, Math.min(100, v));

export const ResourceGantt: React.FC<Props> = ({ resources, rangeFrom, rangeTo, onTaskClick }) => {
  const model = useMemo(() => {
    const start = parseDate(rangeFrom) ?? new Date();
    let end = parseDate(rangeTo) ?? addDays(start, 30);
    if (differenceInCalendarDays(end, start) < 1) end = addDays(start, 1);
    const totalDays = Math.max(1, differenceInCalendarDays(end, start));

    const ticks: { left: number; label: string }[] = [];
    for (let m = startOfMonth(start); m <= end; m = addMonths(m, 1)) {
      const offset = differenceInCalendarDays(m, start);
      if (offset < 0 || offset > totalDays) continue;
      ticks.push({ left: (offset / totalDays) * 100, label: format(m, 'LLL yyyy', { locale: ru }) });
    }

    const todayOffset = differenceInCalendarDays(new Date(), start);
    const todayLeft = todayOffset >= 0 && todayOffset <= totalDays ? (todayOffset / totalDays) * 100 : null;

    const pxPerDay = totalDays <= 31 ? 26 : totalDays <= 92 ? 12 : totalDays <= 366 ? 5 : 2;
    const timelineWidth = Math.max(560, Math.round(totalDays * pxPerDay));

    return { start, totalDays, ticks, todayLeft, timelineWidth };
  }, [rangeFrom, rangeTo]);

  if (resources.length === 0) {
    return (
      <p className="text-muted-foreground text-sm text-center py-12">
        Нет ресурсов с задачами в выбранном периоде. Измените период или фильтры.
      </p>
    );
  }

  const { start, totalDays, ticks, todayLeft, timelineWidth } = model;
  let prevKind: ResourceKind | null = null;

  return (
    <div className="w-full">
      {/* Легенда */}
      <div className="mb-3 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
        {Object.entries(STATUS_LABELS).map(([k, label]) => (
          <span key={k} className="inline-flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-sm" style={{ background: STATUS_COLORS[k] }} />
            {label}
          </span>
        ))}
        <span className="inline-flex items-center gap-1.5 opacity-80">
          <span className="h-2.5 w-2.5 rounded-sm bg-black/25" /> остаток (по прогрессу)
        </span>
      </div>

      <div className="overflow-x-auto rounded-lg border">
        <div style={{ minWidth: LABEL_W + timelineWidth }}>
          {/* Шапка с месяцами */}
          <div className="flex border-b bg-muted/40">
            <div style={{ width: LABEL_W }} className="shrink-0 px-3 py-2 text-xs font-medium text-muted-foreground">
              Ресурс
            </div>
            <div className="relative flex-1 h-9">
              {ticks.map((tk, i) => (
                <div key={i} className="absolute top-0 h-full border-l border-border/60 pl-1 pt-2 text-[11px] text-muted-foreground"
                  style={{ left: `${tk.left}%` }}>
                  {tk.label}
                </div>
              ))}
            </div>
          </div>

          {/* Строки ресурсов с групповыми заголовками */}
          {resources.map((r) => {
            const groupHeader = r.resource_kind !== prevKind;
            prevKind = r.resource_kind;
            const Meta = KIND_META[r.resource_kind];
            const Icon = Meta.icon;
            return (
              <div key={r.resource_id}>
                {groupHeader && (
                  <div className="flex items-center gap-2 border-b bg-muted/60 px-3 py-1.5 text-xs font-semibold uppercase tracking-wide text-foreground">
                    <Icon className="h-3.5 w-3.5" /> {Meta.label}
                  </div>
                )}
                <div className="flex items-center border-b hover:bg-muted/30 transition-colors">
                  <div style={{ width: LABEL_W }} className="shrink-0 px-3 py-2 min-w-0">
                    <div className="truncate text-sm">{r.resource_name}</div>
                    {typeof r.meta?.department === 'string' && (
                      <div className="truncate text-[11px] text-muted-foreground">{r.meta.department as string}</div>
                    )}
                    {typeof r.meta?.inventory_no === 'string' && (
                      <div className="truncate text-[11px] text-muted-foreground">№ {r.meta.inventory_no as string}</div>
                    )}
                  </div>
                  <div className="relative flex-1 h-9">
                    {todayLeft !== null && (
                      <div className="absolute top-0 h-full w-px bg-red-500/60 z-0" style={{ left: `${todayLeft}%` }} />
                    )}
                    {r.allocated_tasks.map((t) => {
                      const s = parseDate(t.start_date);
                      const e = parseDate(t.end_date) ?? s;
                      if (!s || !e) return null;
                      const left = clamp((differenceInCalendarDays(s, start) / totalDays) * 100);
                      const rawW = (Math.max(1, differenceInCalendarDays(e, start)) / totalDays) * 100;
                      const width = Math.max(clamp(rawW) - left, 0.6);
                      const color = STATUS_COLORS[t.status] || '#8884d8';
                      const tooltip =
                        `${t.key} · ${t.title}\n${STATUS_LABELS[t.status] || t.status}\n` +
                        `${format(s, 'dd.MM.yyyy')} — ${format(e, 'dd.MM.yyyy')}`;
                      return (
                        <div
                          key={t.task_id}
                          onClick={() => onTaskClick?.(t.task_id)}
                          title={tooltip}
                          className="absolute top-1/2 -translate-y-1/2 h-5 rounded-md shadow-sm overflow-hidden cursor-pointer z-[1] flex items-center"
                          style={{ left: `${left}%`, width: `${width}%`, background: color, minWidth: 8 }}
                        >
                          <span className="truncate px-1.5 text-[10px] font-medium text-white/95">{t.key}</span>
                          {/* остаток работы по прогрессу */}
                          <span className="absolute right-0 top-0 h-full bg-black/25"
                            style={{ width: `${(1 - t.progress) * 100}%` }} />
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};

export default ResourceGantt;
