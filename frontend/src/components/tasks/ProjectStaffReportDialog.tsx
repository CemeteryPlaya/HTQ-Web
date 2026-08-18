/**
 * Ввод и правка отчёта по персоналу блока за день.
 *
 * Почему диалог, а не инлайн-форма как в ежедневке: там строка задачи —
 * одно число, здесь таблица «роль × количество» переменной длины, и на
 * карточке блока она бы её распирала.
 *
 * Один блок × одна дата = ОДИН отчёт (`UNIQUE(project, site_block,
 * work_date)` на бэке). Численность это состояние, а не сумма смен, поэтому
 * при существующем отчёте диалог открывается на правку, а не заводит
 * второй. Каждая правка пишет ревизию — лента внизу.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { History, Loader2, Plus, Trash2, Users } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import {
  createProjectStaffReport, deleteProjectStaffReport, fetchProjectStaffRevisions,
  fetchWorkRoles, updateProjectStaffReport,
} from '@/api/tasks';
import type { ProjectStaffBoardBlock, ProjectStaffReport } from '@/types/tasks';

const errorDetail = (err: unknown): string | undefined =>
  (err as { response?: { data?: { detail?: unknown } } })?.response?.data
    ?.detail as string | undefined;

interface Draft {
  work_role_id: string;
  headcount: string;
}

const emptyRow = (): Draft => ({ work_role_id: '', headcount: '' });

/* ────────────────────────────── Лента версий ────────────────────────────── */

const RevisionHistory: React.FC<{ reportId: number }> = ({ reportId }) => {
  const { t } = useTranslation();
  const { data: revisions = [], isLoading } = useQuery({
    queryKey: ['project-staff-revisions', reportId],
    queryFn: () => fetchProjectStaffRevisions(reportId),
  });

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        {t('tasks.projectStaff.loadingHistory', 'Загрузка истории...')}
      </div>
    );
  }
  if (revisions.length <= 1) return null;

  return (
    <div className="space-y-2 rounded-xl border bg-muted/20 p-3">
      <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
        <History className="h-3.5 w-3.5" />
        {t('tasks.projectStaff.history', 'История правок')}
      </div>
      <div className="space-y-1.5">
        {[...revisions].reverse().map((rev) => (
          <div key={rev.id} className="text-xs">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="secondary" className="rounded-lg text-[10px]">
                v{rev.revision_no}
              </Badge>
              <span className="font-medium text-foreground">
                {rev.total_headcount} {t('tasks.projectStaff.people', 'чел.')}
              </span>
              <span className="text-muted-foreground">
                {rev.edited_by_name || '—'} ·{' '}
                {new Date(rev.edited_at).toLocaleString()}
              </span>
            </div>
            <div className="mt-0.5 text-muted-foreground">
              {rev.lines
                .map((line) => `${line.work_role_name} — ${line.headcount}`)
                .join(', ')}
              {rev.comment ? ` · ${rev.comment}` : ''}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

/* ────────────────────────────── Диалог ────────────────────────────── */

interface Props {
  projectId: number;
  date: string;
  block: ProjectStaffBoardBlock | null;
  /** Уже заведённый отчёт этого блока за дату — тогда диалог на правку. */
  report: ProjectStaffReport | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onChanged?: () => void;
}

export const ProjectStaffReportDialog: React.FC<Props> = ({
  projectId, date, block, report, open, onOpenChange, onChanged,
}) => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [rows, setRows] = useState<Draft[]>([emptyRow()]);
  const [comment, setComment] = useState('');

  const { data: roles = [] } = useQuery({
    queryKey: ['work-roles'],
    queryFn: () => fetchWorkRoles({ active_only: true }),
    enabled: open,
  });

  // Форму наполняем при КАЖДОМ открытии: диалог переиспользуется на всех
  // блоках доски, и остаток прошлого блока читался бы как свои данные.
  useEffect(() => {
    if (!open) return;
    if (report) {
      setRows(report.lines.map((line) => ({
        work_role_id: String(line.work_role_id),
        headcount: String(line.headcount),
      })));
      setComment(report.comment);
    } else {
      setRows([emptyRow()]);
      setComment('');
    }
  }, [open, report]);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['project-staff-board'] });
    if (report) {
      queryClient.invalidateQueries({
        queryKey: ['project-staff-revisions', report.id],
      });
    }
    onChanged?.();
  };

  const payloadLines = useMemo(
    () => rows
      .filter((row) => row.work_role_id && row.headcount !== '')
      .map((row) => ({
        work_role_id: Number(row.work_role_id),
        headcount: Number(row.headcount),
      })),
    [rows],
  );

  const total = payloadLines.reduce((sum, row) => sum + row.headcount, 0);

  const save = useMutation({
    mutationFn: () => (report
      ? updateProjectStaffReport(report.id, { comment, lines: payloadLines })
      : createProjectStaffReport(projectId, {
        site_block_id: block!.site_block_id,
        work_date: date,
        comment,
        lines: payloadLines,
      })),
    onSuccess: () => {
      toast.success(t('tasks.projectStaff.saved', 'Отчёт по персоналу записан'));
      invalidate();
      onOpenChange(false);
    },
    onError: (err) => {
      toast.error(errorDetail(err)
        || t('tasks.projectStaff.saveError', 'Не удалось сохранить отчёт'));
    },
  });

  const remove = useMutation({
    mutationFn: () => deleteProjectStaffReport(report!.id),
    onSuccess: () => {
      toast.success(t('tasks.projectStaff.deleted', 'Отчёт удалён'));
      invalidate();
      onOpenChange(false);
    },
    onError: (err) => {
      toast.error(errorDetail(err)
        || t('tasks.projectStaff.deleteError', 'Не удалось удалить отчёт'));
    },
  });

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    if (payloadLines.length === 0) {
      toast.error(t('tasks.projectStaff.needLine',
        'Укажите хотя бы одну роль и количество людей'));
      return;
    }
    save.mutate();
  };

  const setRow = (index: number, patch: Partial<Draft>) => {
    setRows((prev) => prev.map((row, i) => (i === index
      ? { ...row, ...patch } : row)));
  };

  const busy = save.isPending || remove.isPending;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg rounded-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-base">
            <Users className="h-4 w-4 text-primary" />
            {block?.site_block_name || '—'}
            <span className="text-sm font-normal text-muted-foreground">
              · {block?.site_name} · {date}
            </span>
          </DialogTitle>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            {rows.map((row, index) => {
              // Роль, уже занятую другой строкой, не предлагаем — зеркало
              // uq_staff_report_line_role: иначе форма позволяла бы собрать
              // тело, которое сервер обязан отбить.
              const taken = new Set(rows
                .filter((_, i) => i !== index)
                .map((other) => other.work_role_id)
                .filter(Boolean));
              return (
                <div key={index} className="flex items-end gap-2">
                  <div className="grid flex-1 gap-1">
                    {index === 0 && (
                      <Label className="text-[11px] text-muted-foreground">
                        {t('tasks.projectStaff.role', 'Роль')}
                      </Label>
                    )}
                    <Select
                      value={row.work_role_id}
                      onValueChange={(value) => setRow(index, { work_role_id: value })}
                    >
                      <SelectTrigger className="h-9 rounded-xl text-xs">
                        <SelectValue placeholder={t('tasks.projectStaff.pickRole', 'Выберите роль...')} />
                      </SelectTrigger>
                      <SelectContent className="rounded-2xl">
                        {roles
                          .filter((role) => !taken.has(String(role.id)))
                          .map((role) => (
                            <SelectItem key={role.id} value={String(role.id)}>
                              {role.name}
                            </SelectItem>
                          ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="grid w-24 gap-1">
                    {index === 0 && (
                      <Label className="text-[11px] text-muted-foreground">
                        {t('tasks.projectStaff.headcount', 'Людей')}
                      </Label>
                    )}
                    <Input
                      type="number"
                      min={0}
                      step={1}
                      placeholder="0"
                      value={row.headcount}
                      onChange={(e) => setRow(index, { headcount: e.target.value })}
                      className="h-9 rounded-xl text-xs"
                    />
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="h-9 w-9 shrink-0 text-muted-foreground hover:text-destructive"
                    disabled={rows.length === 1}
                    onClick={() => setRows((prev) => prev.filter((_, i) => i !== index))}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              );
            })}

            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-8 rounded-xl text-xs"
              onClick={() => setRows((prev) => [...prev, emptyRow()])}
            >
              <Plus className="mr-1 h-3.5 w-3.5" />
              {t('tasks.projectStaff.addRow', 'Добавить роль')}
            </Button>
          </div>

          <div className="flex items-center justify-between rounded-xl bg-muted/40 px-3 py-2 text-sm">
            <span className="text-muted-foreground">
              {t('tasks.projectStaff.total', 'Всего людей')}
            </span>
            <span className="font-semibold text-foreground">{total}</span>
          </div>

          <div className="grid gap-1">
            <Label className="text-[11px] text-muted-foreground">
              {t('tasks.projectStaff.comment', 'Комментарий')}
            </Label>
            <Textarea
              rows={2}
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder={t('tasks.projectStaff.commentHint',
                'Например: вторая смена, простой по погоде')}
              className="rounded-xl text-xs"
            />
          </div>

          {report && <RevisionHistory reportId={report.id} />}

          <DialogFooter className="gap-2 sm:justify-between">
            {report ? (
              <Button
                type="button"
                variant="ghost"
                className="rounded-xl text-destructive hover:bg-destructive/10"
                disabled={busy}
                onClick={() => remove.mutate()}
              >
                <Trash2 className="mr-1 h-4 w-4" />
                {t('common.delete', 'Удалить')}
              </Button>
            ) : <span />}
            <div className="flex gap-2">
              <Button
                type="button"
                variant="outline"
                className="rounded-xl"
                disabled={busy}
                onClick={() => onOpenChange(false)}
              >
                {t('common.cancel', 'Отмена')}
              </Button>
              <Button type="submit" className="rounded-xl" disabled={busy}>
                {busy && <Loader2 className="mr-1 h-4 w-4 animate-spin" />}
                {t('common.save', 'Сохранить')}
              </Button>
            </div>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};

export default ProjectStaffReportDialog;
