/* ------------------------------------------------------------------ */
/*  Tasks module — Gantt chart                                         */
/*  Лёгкая диаграмма Ганта на div + date-fns (без внешних библиотек).  */
/*  Переиспользуется: график работ по сотрудникам (группировка) и      */
/*  Гантт в отчётах (выбранные задачи).                                */
/* ------------------------------------------------------------------ */
import React, { useMemo } from 'react';
import {
  parseISO, isValid, differenceInCalendarDays, addDays, startOfMonth,
  addMonths, format, max as maxDate, min as minDate,
} from 'date-fns';
import { ru } from 'date-fns/locale';
import { Check } from 'lucide-react';
import type { Task } from '@/types/tasks';

/* ---- Status palette (синхронно с HRReports) ---- */
const STATUS_COLORS: Record<string, string> = {
  open: '#64748b', in_progress: '#3b82f6', in_review: '#a855f7',
  done: '#22c55e', closed: '#6b7280',
};
const STATUS_LABELS: Record<string, string> = {
  open: 'Открыта', in_progress: 'В работе', in_review: 'На ревью',
  done: 'Готова', closed: 'Закрыта',
};

export type GanttGroupBy = 'none' | 'assignee' | 'department';

interface GanttChartProps {
  tasks: Task[];
  groupBy?: GanttGroupBy;
  onTaskClick?: (task: Task) => void;
}

const LABEL_W = 260; // ширина левой колонки с подписями

function parseDate(s?: string | null): Date | null {
  if (!s) return null;
  const d = parseISO(s);
  return isValid(d) ? d : null;
}

/** Разрешить даты начала/конца полосы для задачи. */
function resolveSpan(t: Task): { start: Date; end: Date } | null {
  const start =
    parseDate(t.start_date) ??
    parseDate(t.effective_start_date) ??
    parseDate(t.created_at);
  // Для завершённых задач конец — фактическая дата выполнения (ключевое для отчётов).
  const isDone = t.status === 'done' || t.status === 'closed';
  const end =
    (isDone ? parseDate(t.completed_at) : null) ??
    parseDate(t.due_date) ??
    parseDate(t.effective_due_date) ??
    (isDone ? parseDate(t.completed_at) : null) ??
    start;
  if (!start || !end) return null;
  // Гарантируем end >= start.
  return end < start ? { start, end: start } : { start, end };
}

function groupLabel(t: Task, by: GanttGroupBy): string {
  if (by === 'assignee') return t.assignee_name || 'Без исполнителя';
  if (by === 'department') return t.department_name || 'Без отдела';
  return '';
}

type Row =
  | { kind: 'group'; key: string; label: string }
  | { kind: 'task'; key: string; task: Task; start: Date; end: Date };

export const GanttChart: React.FC<GanttChartProps> = ({ tasks, groupBy = 'none', onTaskClick }) => {
  const model = useMemo(() => {
    const spans = tasks
      .map((t) => ({ t, span: resolveSpan(t) }))
      .filter((x): x is { t: Task; span: { start: Date; end: Date } } => x.span !== null);

    if (spans.length === 0) return null;

    // Глобальный диапазон + отступы.
    let rangeStart = minDate(spans.map((s) => s.span.start));
    let rangeEnd = maxDate(spans.map((s) => s.span.end));
    if (differenceInCalendarDays(rangeEnd, rangeStart) < 1) {
      rangeStart = addDays(rangeStart, -3);
      rangeEnd = addDays(rangeEnd, 3);
    } else {
      rangeStart = addDays(rangeStart, -2);
      rangeEnd = addDays(rangeEnd, 2);
    }
    const totalDays = Math.max(1, differenceInCalendarDays(rangeEnd, rangeStart));

    // Строки: при группировке — заголовок группы + задачи под ним.
    const rows: Row[] = [];
    const sorted = [...spans].sort((a, b) => {
      if (groupBy !== 'none') {
        const ga = groupLabel(a.t, groupBy);
        const gb = groupLabel(b.t, groupBy);
        if (ga !== gb) return ga.localeCompare(gb, 'ru');
      }
      return a.span.start.getTime() - b.span.start.getTime();
    });

    let currentGroup: string | null = null;
    sorted.forEach(({ t, span }) => {
      if (groupBy !== 'none') {
        const g = groupLabel(t, groupBy);
        if (g !== currentGroup) {
          currentGroup = g;
          rows.push({ kind: 'group', key: `g-${g}`, label: g });
        }
      }
      rows.push({ kind: 'task', key: `t-${t.id}`, task: t, start: span.start, end: span.end });
    });

    // Месячные засечки для шапки.
    const ticks: { left: number; label: string }[] = [];
    for (let m = startOfMonth(rangeStart); m <= rangeEnd; m = addMonths(m, 1)) {
      const offset = differenceInCalendarDays(m, rangeStart);
      if (offset < 0 || offset > totalDays) continue;
      ticks.push({ left: (offset / totalDays) * 100, label: format(m, 'LLL yyyy', { locale: ru }) });
    }

    // Линия «сегодня».
    const today = new Date();
    const todayOffset = differenceInCalendarDays(today, rangeStart);
    const todayLeft = todayOffset >= 0 && todayOffset <= totalDays ? (todayOffset / totalDays) * 100 : null;

    const pxPerDay = totalDays <= 31 ? 26 : totalDays <= 92 ? 12 : totalDays <= 366 ? 5 : 2;
    const timelineWidth = Math.max(560, Math.round(totalDays * pxPerDay));

    return { rows, rangeStart, totalDays, ticks, todayLeft, timelineWidth };
  }, [tasks, groupBy]);

  if (!model) {
    return (
      <p className="text-muted-foreground text-sm text-center py-12">
        Нет задач с датами для построения диаграммы. Выберите задачи и убедитесь, что у них заданы даты начала/срока.
      </p>
    );
  }

  const { rows, rangeStart, totalDays, ticks, todayLeft, timelineWidth } = model;

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
        <span className="inline-flex items-center gap-1.5">
          <Check className="h-3 w-3 text-green-600" /> выполнена
        </span>
      </div>

      <div className="overflow-x-auto rounded-lg border">
        <div style={{ minWidth: LABEL_W + timelineWidth }}>
          {/* Шапка с месяцами */}
          <div className="flex border-b bg-muted/40 sticky top-0 z-10">
            <div style={{ width: LABEL_W }} className="shrink-0 px-3 py-2 text-xs font-medium text-muted-foreground">
              Задача
            </div>
            <div className="relative flex-1 h-9">
              {ticks.map((tk, i) => (
                <div
                  key={i}
                  className="absolute top-0 h-full border-l border-border/60 pl-1 pt-2 text-[11px] text-muted-foreground"
                  style={{ left: `${tk.left}%` }}
                >
                  {tk.label}
                </div>
              ))}
            </div>
          </div>

          {/* Строки */}
          <div className="relative">
            {rows.map((row) => {
              if (row.kind === 'group') {
                return (
                  <div key={row.key} className="flex border-b bg-muted/30">
                    <div
                      style={{ width: LABEL_W }}
                      className="shrink-0 px-3 py-1.5 text-xs font-semibold text-foreground truncate"
                      title={row.label}
                    >
                      {row.label}
                    </div>
                    <div className="flex-1" />
                  </div>
                );
              }

              const { task, start, end } = row;
              const left = (differenceInCalendarDays(start, rangeStart) / totalDays) * 100;
              const width = Math.max(
                (Math.max(1, differenceInCalendarDays(end, start)) / totalDays) * 100,
                0.6,
              );
              const color = STATUS_COLORS[task.status] || '#8884d8';
              const isDone = task.status === 'done' || task.status === 'closed';
              const tooltip =
                `${task.key} · ${task.summary}\n` +
                `${STATUS_LABELS[task.status] || task.status}` +
                (task.assignee_name ? ` · ${task.assignee_name}` : '') +
                `\n${format(start, 'dd.MM.yyyy')} — ${format(end, 'dd.MM.yyyy')}`;

              return (
                <div
                  key={row.key}
                  className="flex items-center border-b hover:bg-muted/40 transition-colors cursor-pointer"
                  onClick={() => onTaskClick?.(task)}
                >
                  <div style={{ width: LABEL_W }} className="shrink-0 px-3 py-1.5 min-w-0">
                    <div className="flex items-center gap-1.5 min-w-0">
                      <span className="font-mono text-xs font-medium text-primary shrink-0">{task.key}</span>
                      <span className="truncate text-sm">{task.summary}</span>
                    </div>
                    {groupBy !== 'assignee' && task.assignee_name && (
                      <div className="truncate text-[11px] text-muted-foreground">{task.assignee_name}</div>
                    )}
                  </div>
                  <div className="relative flex-1 h-9">
                    {/* линия «сегодня» */}
                    {todayLeft !== null && (
                      <div
                        className="absolute top-0 h-full w-px bg-red-500/60 z-0"
                        style={{ left: `${todayLeft}%` }}
                      />
                    )}
                    {/* полоса задачи */}
                    <div
                      className="absolute top-1/2 -translate-y-1/2 h-5 rounded-md shadow-sm flex items-center justify-end px-1 z-[1]"
                      style={{ left: `${left}%`, width: `${width}%`, background: color, minWidth: 8 }}
                      title={tooltip}
                    >
                      {isDone && <Check className="h-3 w-3 text-white" />}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
};

export default GanttChart;
