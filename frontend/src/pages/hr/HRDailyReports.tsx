import React, { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';
import {
  AlertTriangle, CalendarDays, CheckCircle2, ChevronLeft, ChevronRight,
  ClipboardList, Search, UserCheck, Check
} from 'lucide-react';

import { TasksLayout } from '@/components/tasks/TasksLayout';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Progress } from '@/components/ui/progress';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { createDailyReport, fetchDailyReportBoard } from '@/api/tasks';
import { volumeUnitLabel } from '@/lib/tasks/roadmap';
import { statusBadgeClass, statusLabel } from '@/lib/tasks/status';
import type { DailyReportBoardRow } from '@/types/tasks';

const isoDay = (value: Date) => value.toISOString().slice(0, 10);
const today = () => isoDay(new Date());

const shiftDay = (day: string, days: number): string => {
  const value = new Date(`${day}T00:00:00`);
  value.setDate(value.getDate() + days);
  return isoDay(value);
};

const errorDetail = (err: unknown): string | undefined =>
  (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail as
    string | undefined;

interface Draft {
  volume_type_id: string;
  quantity: string;
  headcount: string;
  comment: string;
}

const emptyDraft = (): Draft => ({
  volume_type_id: '', quantity: '', headcount: '', comment: '',
});

/* ────────────────────────────── Строка ────────────────────────────── */

const BoardRow: React.FC<{
  row: DailyReportBoardRow;
  date: string;
  onSaved: () => void;
}> = ({ row, date, onSaved }) => {
  const { t } = useTranslation();
  const [draft, setDraft] = useState<Draft>(emptyDraft);

  const needsType = row.volumes.length > 1;
  const filedToday = row.reports.reduce((sum, item) => sum + item.quantity, 0);

  const activeVolume = needsType
    ? row.volumes.find((v) => String(v.volume_type_id) === draft.volume_type_id)
    : row.volumes[0];
  const activeUnit = activeVolume?.unit;

  const save = useMutation({
    mutationFn: () => createDailyReport(row.task_id, {
      work_date: date,
      quantity: Number(draft.quantity),
      headcount: draft.headcount === '' ? null : Number(draft.headcount),
      comment: draft.comment,
      ...(draft.volume_type_id
        ? { volume_type_id: Number(draft.volume_type_id) }
        : {}),
    }),
    onSuccess: () => {
      toast.success(t('tasks.dailyReports.saved', 'Отчёт записан'));
      setDraft(emptyDraft());
      onSaved();
    },
    onError: (err) => {
      toast.error(errorDetail(err) || t('tasks.dailyReports.saveError', 'Не удалось отправить отчёт'));
    },
  });

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!draft.quantity || Number(draft.quantity) <= 0) return;
    if (needsType && !draft.volume_type_id) return;
    save.mutate();
  };

  return (
    <div className="rounded-2xl border bg-card/70 p-4 shadow-2xs space-y-3 hover:border-primary/30 transition-colors">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-2">
        <div>
          <div className="flex items-center gap-2 flex-wrap">
            <Link
              to={`/tasks/${row.task_id}`}
              className="font-mono text-xs font-bold text-primary hover:underline"
            >
              {row.task_key}
            </Link>
            <span className="font-semibold text-sm text-foreground">{row.task_summary}</span>
            <Badge className={statusBadgeClass(row.task_status)}>
              {statusLabel(row.task_status, t)}
            </Badge>
          </div>
          <div className="text-xs text-muted-foreground mt-0.5">
            {[row.project_name, row.site_name, row.block_name, row.roadmap_title].filter(Boolean).join(' / ') || 'Без привязки к объекту'}
          </div>
        </div>

        {filedToday > 0 && (
          <Badge variant="secondary" className="gap-1 text-xs self-start md:self-auto rounded-xl">
            <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
            {t('tasks.dailyReports.filedToday', 'Подано за день')}: {filedToday} {volumeUnitLabel(activeUnit, t)}
          </Badge>
        )}
      </div>

      {/* Выполнение по видам работ */}
      <div className="grid gap-2 sm:grid-cols-2 md:grid-cols-3">
        {row.volumes.map((v) => (
          <div key={v.id} className="rounded-xl border bg-muted/20 p-2.5 text-xs space-y-1">
            <div className="font-medium text-foreground flex items-center justify-between">
              <span>{v.volume_type_name}</span>
              <span className="text-muted-foreground">{v.actual_volume} / {v.planned_volume} {volumeUnitLabel(v.unit, t)}</span>
            </div>
            <Progress value={v.planned_volume ? Math.min(100, Math.round((v.actual_volume / v.planned_volume) * 100)) : 0} className="h-1.5 rounded-full" />
          </div>
        ))}
      </div>

      {/* Форма ввода отчёта */}
      <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-3 pt-1 border-t">
        {needsType && (
          <div className="grid gap-1 min-w-[140px]">
            <Label className="text-[11px] text-muted-foreground">{t('tasks.dailyReports.volumeType', 'Вид работ')}</Label>
            <Select value={draft.volume_type_id} onValueChange={(val) => setDraft({ ...draft, volume_type_id: val })}>
              <SelectTrigger className="h-8 text-xs rounded-xl bg-muted/30">
                <SelectValue placeholder="Выберите..." />
              </SelectTrigger>
              <SelectContent className="rounded-2xl">
                {row.volumes.map((v) => (
                  <SelectItem key={v.id} value={String(v.volume_type_id)}>
                    {v.volume_type_name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}

        <div className="grid gap-1 w-32">
          <Label className="text-[11px] text-muted-foreground">
            {t('tasks.dailyReports.quantity', 'Объем')}{activeUnit ? `, ${volumeUnitLabel(activeUnit, t)}` : ''}
          </Label>
          <Input
            type="number"
            step="any"
            placeholder="0"
            className="h-8 text-xs rounded-xl bg-muted/30"
            value={draft.quantity}
            onChange={(e) => setDraft({ ...draft, quantity: e.target.value })}
          />
        </div>

        <div className="grid gap-1 w-28">
          <Label className="text-[11px] text-muted-foreground">{t('tasks.dailyReports.headcount', 'Человек')}</Label>
          <Input
            type="number"
            placeholder="—"
            className="h-8 text-xs rounded-xl bg-muted/30"
            value={draft.headcount}
            onChange={(e) => setDraft({ ...draft, headcount: e.target.value })}
          />
        </div>

        <div className="grid gap-1 flex-1 min-w-[160px]">
          <Label className="text-[11px] text-muted-foreground">{t('tasks.dailyReports.comment', 'Комментарий')}</Label>
          <Input
            placeholder="Примечание..."
            className="h-8 text-xs rounded-xl bg-muted/30"
            value={draft.comment}
            onChange={(e) => setDraft({ ...draft, comment: e.target.value })}
          />
        </div>

        <Button
          type="submit"
          size="sm"
          disabled={!draft.quantity || Number(draft.quantity) <= 0 || (needsType && !draft.volume_type_id) || save.isPending}
          className="h-8 px-4 rounded-xl bg-primary text-primary-foreground font-medium text-xs shadow-2xs"
        >
          {save.isPending ? t('common.saving', 'Сохранение...') : t('common.save', 'Отчитаться')}
        </Button>
      </form>
    </div>
  );
};

/* ────────────────────────────── Главный компонент ────────────────────────────── */

const HRDailyReports: React.FC = () => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [date, setDate] = useState<string>(today());
  const [search, setSearch] = useState('');
  const [place, setPlace] = useState('all');

  const { data: board, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['hr-daily-report-board', date],
    queryFn: () => fetchDailyReportBoard(date),
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['hr-daily-report-board'] });
  };

  const rows = board?.rows ?? [];

  const places = useMemo(() => {
    const set = new Set<string>();
    for (const r of rows) {
      const label = [r.site_name, r.block_name].filter(Boolean).join(' / ');
      if (label) set.add(label);
    }
    return Array.from(set).sort();
  }, [rows]);

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    return rows.filter((r) => {
      const placeLabel = [r.site_name, r.block_name].filter(Boolean).join(' / ');
      if (place !== 'all' && placeLabel !== place) return false;
      if (!q) return true;
      const hay = [r.task_key, r.task_summary, r.project_name, r.site_name, r.block_name, r.roadmap_title]
        .filter(Boolean).join(' ').toLowerCase();
      return hay.includes(q);
    });
  }, [rows, search, place]);

  const groups = useMemo(() => {
    const map = new Map<string, DailyReportBoardRow[]>();
    for (const r of visible) {
      const key = [r.project_name, r.site_name, r.block_name].filter(Boolean).join(' / ') || 'Без привязки к объекту';
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(r);
    }
    return Array.from(map.entries());
  }, [visible]);

  const filed = visible.filter((r) => r.reports.length > 0).length;
  const filtered = search.trim() !== '' || place !== 'all';

  return (
    <TasksLayout
      title={t('tasks.dailyReports.pageTitle', 'Ежедневные отчеты')}
      subtitle={t('tasks.dailyReports.pageSubtitle', 'Быстрая подача отчетов по работам за смену')}
    >
      {/* Переключатель даты */}
      <div className="rounded-3xl border bg-card p-4 shadow-2xs flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-2xl bg-primary/10 flex items-center justify-center text-primary shrink-0">
            <CalendarDays className="h-5 w-5" />
          </div>
          <div className="flex items-center gap-2">
            <Button
              size="icon"
              variant="outline"
              className="h-8 w-8 rounded-xl"
              onClick={() => setDate((prev) => shiftDay(prev, -1))}
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>

            <Input
              type="date"
              className="h-8 text-xs w-36 rounded-xl bg-muted/30 font-medium"
              value={date}
              onChange={(e) => setDate(e.target.value || today())}
            />

            <Button
              size="icon"
              variant="outline"
              className="h-8 w-8 rounded-xl"
              onClick={() => setDate((prev) => shiftDay(prev, 1))}
            >
              <ChevronRight className="h-4 w-4" />
            </Button>

            {date !== today() && (
              <Button size="sm" variant="ghost" className="h-8 text-xs rounded-xl" onClick={() => setDate(today())}>
                Сегодня
              </Button>
            )}
          </div>
        </div>

        <div className="text-xs font-semibold text-muted-foreground bg-muted/30 px-3 py-1.5 rounded-xl border">
          {t('tasks.dailyReports.filedOf', 'Отчитано')}: <span className="text-primary font-bold">{filed}</span> / {visible.length}
        </div>
      </div>

      {/* Поиск и фильтры по участкам */}
      {rows.length > 0 && (
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative flex-1 min-w-[220px]">
            <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              className="h-9 pl-9 text-xs rounded-xl bg-card border-border/60"
              placeholder={t('tasks.dailyReports.search', 'Поиск по номеру, названию или объекту…')}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>

          {places.length > 1 && (
            <Select value={place} onValueChange={setPlace}>
              <SelectTrigger className="h-9 w-[220px] text-xs rounded-xl bg-card">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="rounded-2xl">
                <SelectItem value="all">{t('tasks.dailyReports.allPlaces', 'Все участки')}</SelectItem>
                {places.map((name) => (
                  <SelectItem key={name} value={name}>{name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}

          {filtered && (
            <Button size="sm" variant="ghost" className="h-9 text-xs rounded-xl" onClick={() => { setSearch(''); setPlace('all'); }}>
              {t('common.reset', 'Сбросить')}
            </Button>
          )}
        </div>
      )}

      {/* Данные отчетов */}
      {isLoading ? (
        <div className="py-12 text-center text-xs text-muted-foreground">{t('common.loading', 'Загрузка задач…')}</div>
      ) : isError ? (
        <div className="rounded-3xl border border-destructive/30 bg-destructive/10 p-8 text-center space-y-3">
          <AlertTriangle className="h-8 w-8 text-destructive mx-auto" />
          <p className="text-sm font-semibold text-destructive">{t('tasks.dailyReports.boardError', 'Не удалось получить сводку за день')}</p>
          <Button size="sm" variant="outline" className="rounded-xl" onClick={() => refetch()}>
            {t('common.retry', 'Повторить')}
          </Button>
        </div>
      ) : visible.length === 0 ? (
        <div className="rounded-3xl border bg-card p-12 text-center space-y-2">
          <ClipboardList className="h-8 w-8 text-muted-foreground mx-auto" />
          <p className="text-xs text-muted-foreground">
            {rows.length > 0
              ? t('tasks.dailyReports.nothingMatches', 'Под фильтр ничего не подошло — измените выбор.')
              : t('tasks.dailyReports.boardEmpty', 'Нет задач, по которым требуется отчитаться на эту дату.')}
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {groups.map(([name, groupRows]) => (
            <div key={name} className="rounded-3xl border bg-card p-4 shadow-2xs space-y-3">
              <div className="flex items-center justify-between border-b pb-3">
                <h3 className="text-sm font-bold text-foreground flex items-center gap-2">
                  {name}
                  <Badge variant="outline" className="rounded-md font-mono text-[10px]">{groupRows.length}</Badge>
                </h3>
              </div>
              <div className="space-y-3">
                {groupRows.map((row) => (
                  <BoardRow
                    key={row.task_id}
                    row={row}
                    date={date}
                    onSaved={invalidate}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </TasksLayout>
  );
};

export default HRDailyReports;
