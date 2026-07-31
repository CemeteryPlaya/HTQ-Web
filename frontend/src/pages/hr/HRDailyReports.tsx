/**
 * HRDailyReports — «Ежедневка»: одна страница, чтобы закрыть день.
 *
 * До неё отчитаться можно было только по одной задаче за раз — открыть
 * карточку, нажать «Отчитаться», закрыть, открыть следующую. Прораб с
 * четырьмя порциями на блоке делал это четыре раза. Здесь дата задаётся
 * один раз сверху, а строки заполняются подряд.
 *
 * Показываются ТОЛЬКО те задачи, куда сохранение пройдёт: сервер отбирает
 * их тем же правилом, что проверяет запись (``soft_edit_q``). Строка,
 * которую нельзя сохранить, хуже отсутствующей.
 *
 * Ввод всегда СОЗДАЁТ новый отчёт, а не правит вчерашний: за день бывает
 * несколько смен, и они складываются — ``UNIQUE(task, work_date)`` в модели
 * нет намеренно. Уже поданные за эту дату отчёты показаны рядом со строкой,
 * править их — через карточку задачи, где есть история версий.
 */
import React, { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';
import {
  AlertTriangle, CalendarDays, CheckCircle2, ChevronLeft, ChevronRight,
  ClipboardList, Search,
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

  // Вид работ спрашиваем только когда их несколько: при одном сервер
  // подставит его сам (resolve_volume_type), и лишний селект в каждой
  // строке — клик впустую на каждую смену.
  const needsType = row.volumes.length > 1;
  const filedToday = row.reports.reduce((sum, item) => sum + item.quantity, 0);

  // Единица берётся у выбранного вида работ и подставляется в подпись поля:
  // «Выполнено за день, шт» отвечает на вопрос «сколько чего» само, без
  // сверки со строкой плана выше.
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
      toast.success(t('tasks.dailyReports.created', 'Отчёт добавлен'));
      setDraft(emptyDraft());
      onSaved();
    },
    onError: (err) => toast.error(
      errorDetail(err) || t('tasks.dailyReports.saveError',
        'Не удалось сохранить отчёт'),
    ),
  });

  const canSave = draft.quantity !== '' && Number(draft.quantity) >= 0
    && (!needsType || draft.volume_type_id !== '');

  return (
    <div className="space-y-2 rounded-lg border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Link
          to={`/tasks/${row.task_id}`}
          className="font-mono text-sm text-primary hover:underline"
        >
          {row.key}
        </Link>
        <span className="flex-1 truncate text-sm font-medium">{row.summary}</span>
        {filedToday > 0 && (
          <Badge variant="outline" className="gap-1 text-[10px] text-emerald-600">
            <CheckCircle2 className="h-3 w-3" />
            {t('tasks.dailyReports.filedToday', 'за день')}: {filedToday}
          </Badge>
        )}
        <Badge className={statusBadgeClass(row.status)} variant="secondary">
          {statusLabel(row.status, t)}
        </Badge>
      </div>

      {row.roadmap_name && (
        <p className="text-xs text-muted-foreground">
          {row.roadmap_name}
          {row.due_date && ` · ${t('tasks.projects.end', 'Завершение')}: ${row.due_date}`}
        </p>
      )}

      {/* План/факт — чтобы не считать в уме, сколько осталось. */}
      <div className="space-y-1">
        {row.volumes.map((volume) => {
          const percent = volume.planned_quantity > 0
            ? Math.min(volume.completed_quantity / volume.planned_quantity * 100, 100)
            : null;
          const left = volume.planned_quantity - volume.completed_quantity;
          return (
            <div key={volume.volume_type_id} className="flex items-center gap-2">
              <span className="w-44 truncate text-xs text-muted-foreground">
                {volume.volume_type_name}
              </span>
              <span className="tabular-nums text-xs">
                {volume.completed_quantity} / {volume.planned_quantity}{' '}
                {volumeUnitLabel(volume.unit)}
              </span>
              <div className="w-24">
                <Progress value={percent ?? 0} className="h-1.5" />
              </div>
              {left > 0 && (
                <span className="text-xs text-muted-foreground">
                  {t('tasks.dailyReports.left', 'осталось')}{' '}
                  {Math.round(left * 100) / 100} {volumeUnitLabel(volume.unit)}
                </span>
              )}
            </div>
          );
        })}
      </div>

      {/* Поля с подписями, а не с одними подсказками внутри: «Сделано» и
          «чел.» без единицы и пояснения читаются как загадка, а заполняет
          их прораб на телефоне между делом. */}
      <div className="flex flex-wrap items-end gap-2 border-t pt-2">
        {needsType && (
          <div className="space-y-1">
            <Label className="text-xs text-muted-foreground">
              {t('tasks.volumes.type', 'Вид работ')}
            </Label>
            <Select
              value={draft.volume_type_id}
              onValueChange={(value) => setDraft((prev) => ({
                ...prev, volume_type_id: value,
              }))}
            >
              <SelectTrigger className="h-9 w-52">
                <SelectValue placeholder={t('tasks.dailyReports.pickType',
                  'Выберите вид работ')} />
              </SelectTrigger>
              <SelectContent>
                {row.volumes.map((volume) => (
                  <SelectItem key={volume.volume_type_id}
                              value={String(volume.volume_type_id)}>
                    {volume.volume_type_name} ({volumeUnitLabel(volume.unit)})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}
        <div className="space-y-1">
          <Label htmlFor={`qty-${row.task_id}`} className="text-xs text-muted-foreground">
            {t('tasks.dailyReports.doneLabel', 'Выполнено за день')}
            {activeUnit && `, ${volumeUnitLabel(activeUnit)}`}
          </Label>
          <Input
            id={`qty-${row.task_id}`}
            type="number" min="0" step="any" className="h-9 w-32 tabular-nums"
            placeholder="0"
            value={draft.quantity}
            onChange={(event) => setDraft((prev) => ({
              ...prev, quantity: event.target.value,
            }))}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor={`crew-${row.task_id}`} className="text-xs text-muted-foreground">
            {t('tasks.dailyReports.crewLabel', 'Человек на смене')}
          </Label>
          <Input
            id={`crew-${row.task_id}`}
            type="number" min="0" step="1" className="h-9 w-32 tabular-nums"
            placeholder="—"
            value={draft.headcount}
            onChange={(event) => setDraft((prev) => ({
              ...prev, headcount: event.target.value,
            }))}
          />
        </div>
        <div className="min-w-[12rem] flex-1 space-y-1">
          <Label htmlFor={`note-${row.task_id}`} className="text-xs text-muted-foreground">
            {t('tasks.dailyReports.commentLabel', 'Комментарий (необязательно)')}
          </Label>
          <Input
            id={`note-${row.task_id}`}
            className="h-9"
            placeholder={t('tasks.dailyReports.commentHint',
              'Например: одна кара в ремонте')}
            value={draft.comment}
            onChange={(event) => setDraft((prev) => ({
              ...prev, comment: event.target.value,
            }))}
          />
        </div>
        <Button
          size="sm"
          className="h-9"
          disabled={!canSave || save.isPending}
          title={canSave ? undefined : t('tasks.dailyReports.needQuantity',
            'Укажите, сколько выполнено за этот день')}
          onClick={() => save.mutate()}
        >
          {save.isPending
            ? t('common.saving', 'Сохранение...')
            : t('tasks.dailyReports.write', 'Записать')}
        </Button>
      </div>

      {row.reports.length > 0 && (
        <div className="space-y-0.5 border-t pt-2">
          {row.reports.map((report) => (
            <p key={report.id} className="text-xs text-muted-foreground">
              {report.quantity} {volumeUnitLabel(report.unit)}
              {' · '}{report.volume_type_name}
              {report.headcount !== null
                && ` · ${report.headcount} ${t('tasks.dailyReports.people', 'чел.')}`}
              {report.author_name && ` · ${report.author_name}`}
              {report.comment && ` — ${report.comment}`}
            </p>
          ))}
        </div>
      )}
    </div>
  );
};

/* ────────────────────────────── Страница ────────────────────────────── */

const HRDailyReports: React.FC = () => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [date, setDate] = useState(today);
  const [search, setSearch] = useState('');
  const [place, setPlace] = useState('all');

  const { data: rows = [], isLoading, isError, error, refetch } = useQuery({
    queryKey: ['daily-report-board', date],
    queryFn: () => fetchDailyReportBoard(date),
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['daily-report-board'] });
    // Отчёт меняет факт везде, где он считается свёрткой.
    queryClient.invalidateQueries({ queryKey: ['task-daily-reports'] });
    queryClient.invalidateQueries({ queryKey: ['roadmap-metrics'] });
    queryClient.invalidateQueries({ queryKey: ['plan-fact'] });
    queryClient.invalidateQueries({ queryKey: ['block-progress'] });
  };

  /** Подпись места — она же ключ группировки и значение фильтра. */
  const placeOf = React.useCallback((row: DailyReportBoardRow) => (
    [row.site_name, row.site_block_name].filter(Boolean).join(' · ')
    || t('tasks.dailyReports.noBlock', 'Вне объектов')
  ), [t]);

  const places = useMemo(
    () => [...new Set(rows.map(placeOf))].sort((a, b) => a.localeCompare(b)),
    [rows, placeOf],
  );

  /**
   * Поиск и фильтр по участку — на клиенте, а не запросом: сводка за день
   * это десятки строк, они уже здесь, и лишний круг к серверу на каждую
   * букву сделал бы поле медленнее бумаги.
   */
  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return rows.filter((row) => {
      if (place !== 'all' && placeOf(row) !== place) return false;
      if (!needle) return true;
      return `${row.key} ${row.summary} ${row.roadmap_name ?? ''}`
        .toLowerCase().includes(needle);
    });
  }, [rows, search, place, placeOf]);

  /** Группировка по блоку: бригада работает на участке, не по всей стройке. */
  const groups = useMemo(() => {
    const byBlock = new Map<string, DailyReportBoardRow[]>();
    visible.forEach((row) => {
      const key = placeOf(row);
      if (!byBlock.has(key)) byBlock.set(key, []);
      byBlock.get(key)!.push(row);
    });
    return [...byBlock.entries()];
  }, [visible, placeOf]);

  const filed = visible.filter((row) => row.reports.length > 0).length;
  const filtered = visible.length !== rows.length;

  return (
    <TasksLayout
      title={t('tasks.nav.daily', 'Ежедневка')}
      subtitle={t('tasks.dailyReports.subtitle',
        'Отчёт о выполненном за смену — по дате выполнения работ')}
    >
      <Card className="mb-4">
        <CardContent className="flex flex-wrap items-center gap-3 p-4">
          <CalendarDays className="h-5 w-5 text-muted-foreground" />
          <span className="text-sm font-medium">
            {t('tasks.dailyReports.workDate', 'Дата выполнения работ')}
          </span>
          <Button size="icon" variant="outline" className="h-9 w-9"
                  aria-label={t('tasks.dailyReports.prevDay', 'Предыдущий день')}
                  onClick={() => setDate((prev) => shiftDay(prev, -1))}>
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <Input
            type="date" className="h-9 w-40"
            value={date}
            onChange={(event) => setDate(event.target.value || today())}
          />
          <Button size="icon" variant="outline" className="h-9 w-9"
                  aria-label={t('tasks.dailyReports.nextDay', 'Следующий день')}
                  onClick={() => setDate((prev) => shiftDay(prev, 1))}>
            <ChevronRight className="h-4 w-4" />
          </Button>
          {date !== today() && (
            <Button size="sm" variant="ghost" onClick={() => setDate(today())}>
              {t('tasks.dailyReports.today', 'Сегодня')}
            </Button>
          )}
          <span className="flex-1" />
          <span className="text-sm text-muted-foreground">
            {t('tasks.dailyReports.filedOf', 'Отчитано')}: {filed} / {visible.length}
          </span>
        </CardContent>
      </Card>

      {/* Поиск и участок — рядом с датой, потому что на большой стройке
          список за день это не десять строк, а сотня. */}
      {rows.length > 0 && (
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <div className="relative min-w-[16rem] flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              className="h-9 pl-9"
              placeholder={t('tasks.dailyReports.search',
                'Поиск по номеру, названию или пакету работ')}
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </div>
          {places.length > 1 && (
            <Select value={place} onValueChange={setPlace}>
              <SelectTrigger className="h-9 w-64">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">
                  {t('tasks.dailyReports.allPlaces', 'Все участки')}
                </SelectItem>
                {places.map((name) => (
                  <SelectItem key={name} value={name}>{name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
          {filtered && (
            <Button size="sm" variant="ghost"
                    onClick={() => { setSearch(''); setPlace('all'); }}>
              {t('common.reset', 'Сбросить')}
            </Button>
          )}
        </div>
      )}

      {isLoading ? (
        <p className="py-8 text-sm text-muted-foreground">
          {t('common.loading', 'Загрузка...')}
        </p>
      ) : isError ? (
        /* Ошибку нельзя показывать как «нет задач»: это разные вещи, и
           первая требует не заводить отчёт, а чинить связь с сервером. */
        <Card className="border-destructive/40">
          <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
            <AlertTriangle className="h-8 w-8 text-destructive" />
            <p className="text-sm font-medium">
              {t('tasks.dailyReports.boardError',
                'Не удалось получить сводку за день')}
            </p>
            <p className="max-w-lg text-xs text-muted-foreground">
              {errorDetail(error)
                || t('tasks.dailyReports.boardErrorHint',
                  'Сервер не ответил на запрос сводки. Если это локальная среда — возможно, бэкенд запущен со старым кодом и его нужно перезапустить.')}
            </p>
            <Button size="sm" variant="outline" onClick={() => refetch()}>
              {t('common.retry', 'Повторить')}
            </Button>
          </CardContent>
        </Card>
      ) : visible.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center gap-2 py-12 text-center">
            <ClipboardList className="h-8 w-8 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">
              {rows.length > 0
                ? t('tasks.dailyReports.nothingMatches',
                  'Под фильтр ничего не подошло — измените поиск или участок.')
                : t('tasks.dailyReports.boardEmpty',
                  'Нет задач, по которым вы можете отчитаться. Отчитываются по задачам с плановым объёмом работ — задайте его на карточке задачи.')}
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {groups.map(([name, groupRows]) => (
            <Card key={name}>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">
                  {name}
                  <span className="ml-2 text-sm font-normal text-muted-foreground">
                    {groupRows.length}
                  </span>
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 pt-0">
                {groupRows.map((row) => (
                  <BoardRow
                    key={row.task_id}
                    row={row}
                    date={date}
                    onSaved={invalidate}
                  />
                ))}
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </TasksLayout>
  );
};

export default HRDailyReports;
