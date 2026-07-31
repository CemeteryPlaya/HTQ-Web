/**
 * DailyReportDialog — лента ежедневных отчётов задачи и форма нового.
 *
 * Единственное место, где в систему попадает ФАКТ выполнения. Ключевое
 * поле — «дата выполнения работ»: её ставит человек, и она не то же самое,
 * что дата заполнения. Отчёт за пятницу заполняют в понедельник, и по дням
 * он обязан лечь на пятницу — иначе S-кривая и темп врут.
 *
 * История версий рядом с лентой, а не в отдельном разделе: цифра
 * выполнения — основание для расчётов, и «кто и когда её исправил» должно
 * быть в один клик, а не в трёх экранах отсюда.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { History, Pencil, Plus, Trash2 } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import {
  createDailyReport, deleteDailyReport, fetchDailyReportRevisions,
  fetchTaskDailyReports, fetchTaskVolumes, updateDailyReport,
} from '@/api/tasks';
import { useActiveProfile } from '@/hooks/useActiveProfile';
import { hasElevatedAccess } from '@/lib/auth/roles';
import { canEditDailyReport } from '@/lib/tasks/dailyReport';
import { volumeUnitLabel } from '@/lib/tasks/roadmap';
import type { DailyReport } from '@/types/tasks';

const today = () => new Date().toISOString().slice(0, 10);

const emptyForm = () => ({
  volume_type_id: '', work_date: today(), quantity: '',
  headcount: '', comment: '',
});

/** Что изменилось между соседними версиями — подсветка в истории. */
const changedFields = (
  current: { work_date: string; quantity: number; headcount: number | null;
             comment: string },
  previous?: { work_date: string; quantity: number; headcount: number | null;
               comment: string },
): Set<string> => {
  if (!previous) return new Set();
  const changed = new Set<string>();
  (['work_date', 'quantity', 'headcount', 'comment'] as const)
    .forEach((field) => {
      if (current[field] !== previous[field]) changed.add(field);
    });
  return changed;
};

const RevisionHistory: React.FC<{ reportId: number }> = ({ reportId }) => {
  const { t } = useTranslation();
  const { data: revisions = [], isLoading } = useQuery({
    queryKey: ['daily-report-revisions', reportId],
    queryFn: () => fetchDailyReportRevisions(reportId),
  });

  if (isLoading) {
    return <p className="text-sm text-muted-foreground">
      {t('common.loading', 'Загрузка...')}
    </p>;
  }

  return (
    <div className="space-y-2">
      {revisions.map((revision, index) => {
        const changed = changedFields(revision, revisions[index - 1]);
        const mark = (field: string) =>
          changed.has(field) ? 'font-semibold text-amber-600 dark:text-amber-400'
            : '';
        return (
          <div key={revision.id} className="rounded-md border p-2 text-sm">
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Badge variant="outline">
                {t('tasks.dailyReports.revision', 'Версия')} {revision.revision_no}
              </Badge>
              <span>{revision.edited_at.slice(0, 16).replace('T', ' ')}</span>
              {revision.edited_by_name && <span>· {revision.edited_by_name}</span>}
            </div>
            <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
              <span className={mark('work_date')}>
                {t('tasks.dailyReports.workDate', 'Дата выполнения')}:{' '}
                {revision.work_date}
              </span>
              <span className={mark('quantity')}>
                {t('tasks.dailyReports.quantity', 'Количество')}:{' '}
                {revision.quantity}
              </span>
              {revision.headcount !== null && (
                <span className={mark('headcount')}>
                  {t('tasks.dailyReports.headcount', 'Людей')}:{' '}
                  {revision.headcount}
                </span>
              )}
            </div>
            {revision.comment && (
              <p className={`mt-1 text-xs ${mark('comment')}`}>
                {revision.comment}
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
};

export const DailyReportDialog: React.FC<{
  taskId: number | null;
  taskKey?: string;
  /** Супервайзер задачи — он правит чужие отчёты. Не знаете его — не
   *  передавайте: право будет считаться только по автору и админству. */
  supervisorId?: number | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Вызывается после любой записи: страница задачи сбрасывает свой кэш
   *  (объёмы приезжают в ответе задачи, а ключ у каждой страницы свой). */
  onChanged?: () => void;
}> = ({ taskId, taskKey, supervisorId, open, onOpenChange, onChanged }) => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { activeProfile } = useActiveProfile();
  const elevated = hasElevatedAccess(activeProfile);
  const myId = Number(activeProfile?.id);

  const [form, setForm] = useState(emptyForm);
  const [editing, setEditing] = useState<DailyReport | null>(null);
  const [historyFor, setHistoryFor] = useState<number | null>(null);

  const canEdit = (report: DailyReport) => canEditDailyReport({
    authorId: report.author_id, supervisorId, myId, elevated,
  });

  const { data: reports = [], isLoading } = useQuery({
    queryKey: ['task-daily-reports', taskId],
    queryFn: () => fetchTaskDailyReports(taskId!),
    enabled: open && !!taskId,
  });
  const { data: volumes = [] } = useQuery({
    queryKey: ['task-volumes', taskId],
    queryFn: () => fetchTaskVolumes(taskId!),
    enabled: open && !!taskId,
  });

  // Вид работ спрашиваем только когда их несколько: при одном сервер
  // подставит его сам (resolve_volume_type), и лишний селект в форме —
  // клик на каждую смену впустую.
  const needsVolumeType = volumes.length > 1;

  useEffect(() => {
    if (!open) {
      setForm(emptyForm());
      setEditing(null);
      setHistoryFor(null);
    }
  }, [open]);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['task-daily-reports', taskId] });
    queryClient.invalidateQueries({ queryKey: ['task-volumes', taskId] });
    // План/факт и прогресс блока считаются из отчётов — их тоже сбрасываем,
    // иначе цифры на соседних экранах останутся вчерашними.
    queryClient.invalidateQueries({ queryKey: ['roadmap-metrics'] });
    queryClient.invalidateQueries({ queryKey: ['plan-fact'] });
    queryClient.invalidateQueries({ queryKey: ['block-progress'] });
    onChanged?.();
  };

  const saveMutation = useMutation({
    mutationFn: () => {
      const payload = {
        work_date: form.work_date,
        quantity: Number(form.quantity),
        headcount: form.headcount === '' ? null : Number(form.headcount),
        comment: form.comment,
      };
      if (editing) return updateDailyReport(editing.id, payload);
      return createDailyReport(taskId!, {
        ...payload,
        ...(form.volume_type_id
          ? { volume_type_id: Number(form.volume_type_id) }
          : {}),
      });
    },
    onSuccess: () => {
      toast.success(editing
        ? t('tasks.dailyReports.updated', 'Отчёт обновлён')
        : t('tasks.dailyReports.created', 'Отчёт добавлен'));
      setForm(emptyForm());
      setEditing(null);
      invalidate();
    },
    onError: () => toast.error(
      t('tasks.dailyReports.saveError', 'Не удалось сохранить отчёт')),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteDailyReport(id),
    onSuccess: () => {
      toast.success(t('tasks.dailyReports.deleted', 'Отчёт удалён'));
      invalidate();
    },
    onError: () => toast.error(
      t('tasks.dailyReports.deleteError', 'Не удалось удалить отчёт')),
  });

  const openEdit = (report: DailyReport) => {
    setEditing(report);
    setForm({
      volume_type_id: String(report.volume_type_id),
      work_date: report.work_date,
      quantity: String(report.quantity),
      headcount: report.headcount === null ? '' : String(report.headcount),
      comment: report.comment,
    });
  };

  const total = useMemo(
    () => reports.reduce((sum, row) => sum + row.quantity, 0),
    [reports],
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {t('tasks.dailyReports.title', 'Ежедневные отчёты')}
            {taskKey && <span className="text-muted-foreground"> — {taskKey}</span>}
          </DialogTitle>
        </DialogHeader>

        {/* Лента отчётов */}
        <div className="space-y-2">
          {isLoading ? (
            <p className="text-sm text-muted-foreground">
              {t('common.loading', 'Загрузка...')}
            </p>
          ) : reports.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {t('tasks.dailyReports.empty', 'Отчётов пока нет')}
            </p>
          ) : (
            <>
              {reports.map((report) => (
                <div key={report.id} className="rounded-md border p-2">
                  <div className="flex items-center gap-2 text-sm">
                    <span className="font-medium tabular-nums">
                      {report.work_date}
                    </span>
                    <span className="tabular-nums">
                      {report.quantity} {volumeUnitLabel(report.unit)}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      {report.volume_type_name}
                    </span>
                    {report.headcount !== null && (
                      <span className="text-xs text-muted-foreground">
                        · {report.headcount}{' '}
                        {t('tasks.dailyReports.people', 'чел.')}
                      </span>
                    )}
                    <span className="flex-1" />
                    {report.current_revision > 1 && (
                      <Badge variant="outline" className="text-[10px]">
                        {t('tasks.dailyReports.revision', 'Версия')}{' '}
                        {report.current_revision}
                      </Badge>
                    )}
                    <Button
                      size="icon" variant="ghost" className="h-7 w-7"
                      title={t('tasks.dailyReports.history', 'История версий')}
                      onClick={() => setHistoryFor(
                        historyFor === report.id ? null : report.id)}
                    >
                      <History className="h-4 w-4" />
                    </Button>
                    {/* Правка и удаление — только там, где сервер их
                        разрешит: иначе кнопка гарантированно даёт 403.
                        История версий остаётся всем, кто видит задачу. */}
                    {canEdit(report) && (
                      <>
                        <Button size="icon" variant="ghost" className="h-7 w-7"
                                onClick={() => openEdit(report)}>
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <Button
                          size="icon" variant="ghost"
                          className="h-7 w-7 text-muted-foreground hover:text-destructive"
                          onClick={() => {
                            if (window.confirm(t('tasks.dailyReports.deleteConfirm',
                              'Удалить отчёт?'))) deleteMutation.mutate(report.id);
                          }}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </>
                    )}
                  </div>
                  {report.comment && (
                    <p className="mt-1 text-xs text-muted-foreground">
                      {report.comment}
                    </p>
                  )}
                  {report.author_name && (
                    <p className="mt-0.5 text-[11px] text-muted-foreground">
                      {report.author_name} ·{' '}
                      {t('tasks.dailyReports.filedAt', 'заполнен')}{' '}
                      {report.created_at.slice(0, 10)}
                    </p>
                  )}
                  {historyFor === report.id && (
                    <div className="mt-2 border-t pt-2">
                      <RevisionHistory reportId={report.id} />
                    </div>
                  )}
                </div>
              ))}
              <p className="text-sm text-muted-foreground">
                {t('tasks.dailyReports.total', 'Всего')}:{' '}
                <span className="font-medium tabular-nums">{total}</span>
              </p>
            </>
          )}
        </div>

        {/* Форма */}
        <div className="border-t pt-4 space-y-3">
          <p className="text-sm font-medium">
            {editing
              ? t('tasks.dailyReports.editTitle', 'Правка отчёта')
              : t('tasks.dailyReports.newTitle', 'Новый отчёт')}
          </p>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>{t('tasks.dailyReports.workDate', 'Дата выполнения')}</Label>
              <Input
                type="date" value={form.work_date}
                onChange={(e) => setForm({ ...form, work_date: e.target.value })}
              />
              <p className="mt-1 text-[11px] text-muted-foreground">
                {t('tasks.dailyReports.workDateHint',
                   'Когда работа сделана, а не когда заполняете отчёт.')}
              </p>
            </div>
            <div>
              <Label>{t('tasks.dailyReports.quantity', 'Количество')}</Label>
              <Input
                type="number" min={0} step="0.01" value={form.quantity}
                onChange={(e) => setForm({ ...form, quantity: e.target.value })}
              />
            </div>

            {needsVolumeType && !editing && (
              <div className="col-span-2">
                <Label>{t('tasks.pages.blocks.volumeType', 'Вид работ')}</Label>
                <Select
                  value={form.volume_type_id}
                  onValueChange={(v) => setForm({ ...form, volume_type_id: v })}
                >
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {volumes.map((volume) => (
                      <SelectItem key={volume.volume_type_id}
                                  value={String(volume.volume_type_id)}>
                        {volume.volume_type_name} ({volumeUnitLabel(volume.unit)})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}

            <div>
              <Label>{t('tasks.dailyReports.headcount', 'Людей')}</Label>
              <Input
                type="number" min={0} value={form.headcount}
                onChange={(e) => setForm({ ...form, headcount: e.target.value })}
              />
            </div>
          </div>

          <div>
            <Label>{t('tasks.dailyReports.comment', 'Комментарий')}</Label>
            <Textarea
              value={form.comment} rows={2}
              onChange={(e) => setForm({ ...form, comment: e.target.value })}
            />
          </div>
        </div>

        <DialogFooter>
          {editing && (
            <Button variant="outline"
                    onClick={() => { setEditing(null); setForm(emptyForm()); }}>
              {t('common.cancel', 'Отмена')}
            </Button>
          )}
          <Button
            disabled={!form.quantity || !form.work_date
                      || (needsVolumeType && !editing && !form.volume_type_id)
                      || saveMutation.isPending}
            onClick={() => saveMutation.mutate()}
          >
            {editing
              ? <>{t('common.save', 'Сохранить')}</>
              : <><Plus className="h-4 w-4 mr-1" />
                  {t('tasks.dailyReports.add', 'Добавить отчёт')}</>}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

export default DailyReportDialog;
