import React, { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import api from '@/api/client';
import HRLayout from '@/components/hr/HRLayout';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useHRLevel } from '@/hooks/useHRLevel';
import { reportApiError } from '@/lib/apiError';
import i18next from '@/i18n';

/**
 * Запись табеля так, как её отдаёт `GET /api/hr/v1/time-tracking/`
 * (`apps.hr.services.time_service.serialize`) — отработанные часы за день.
 *
 * Страница раньше была написана под другую предметную область: отпуска и
 * отсутствия (`leave_type`, `start_date`/`end_date`, `duration_days`,
 * статусы pending/approved и кнопки одобрения). Ни таких полей, ни
 * эндпойнтов одобрения в домене нет и не было — записи табеля не
 * согласуются, поэтому UI приведён к тому, что реально есть.
 */
interface TimeEntry {
  id: number;
  employee_id: number;
  date: string;
  start_time: string;
  end_time: string;
  break_minutes: number;
  description: string | null;
  project: string | null;
  task: string | null;
  created_at: string;
  updated_at: string;
}

interface EmployeeOption {
  id: number;
  first_name: string;
  last_name: string;
  middle_name?: string | null;
  email?: string | null;
}

interface MonthlyReport {
  employee_id: number;
  year: number;
  month: number;
  total_minutes: number;
  weekly?: Array<{ week_start: string; total_minutes: number }>;
}

const employeeName = (emp?: EmployeeOption): string => {
  if (!emp) return '';
  const full = [emp.last_name, emp.first_name, emp.middle_name].filter(Boolean).join(' ').trim();
  return full || emp.email || `#${emp.id}`;
};

/** «7 ч 30 мин» из минут — и для строки таблицы, и для итогов отчёта. */
const formatMinutes = (minutes: number): string => {
  const safe = Math.max(0, Math.round(minutes || 0));
  const hours = Math.floor(safe / 60);
  const rest = safe % 60;
  return rest
    ? i18next.t('hr.timeTracking.hoursMinutes', { hours, minutes: rest })
    : i18next.t('hr.timeTracking.hours', { hours });
};

/** Отработано за запись: конец − начало − перерыв (та же формула, что в
 * `time_service._minutes`, чтобы строка и отчёт не расходились). */
const workedMinutes = (entry: TimeEntry): number => {
  const [startH, startM] = (entry.start_time || '0:0').split(':').map(Number);
  const [endH, endM] = (entry.end_time || '0:0').split(':').map(Number);
  const total = (endH * 60 + endM) - (startH * 60 + startM) - (entry.break_minutes || 0);
  return Math.max(0, total);
};

const hhmm = (value: string | null | undefined): string => (value || '').slice(0, 5);

const emptyForm = {
  employee: 'none',
  date: '',
  start_time: '09:00',
  end_time: '18:00',
  break_minutes: '60',
  project: '',
  task: '',
  description: '',
};

const HRTimeTracking = () => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { isSenior } = useHRLevel();

  const { data: entries, isLoading, error } = useQuery({
    queryKey: ['hr-timetracking'],
    queryFn: async () => {
      const res = await api.get<TimeEntry[]>('hr/v1/time-tracking/');
      return res.data;
    },
  });

  const { data: employees } = useQuery({
    queryKey: ['hr-employees'],
    queryFn: async () => {
      const res = await api.get<EmployeeOption[]>('hr/v1/employees/');
      return res.data;
    },
  });

  const employeeById = useMemo(() => {
    const map = new Map<number, EmployeeOption>();
    (employees || []).forEach((emp) => map.set(emp.id, emp));
    return map;
  }, [employees]);

  // ── Месячный итог по сотруднику (reports/monthly) ──
  const now = new Date();
  const [reportEmployee, setReportEmployee] = useState('none');
  const [reportMonth, setReportMonth] = useState(
    `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`,
  );

  const { data: monthlyReport, isFetching: reportLoading } = useQuery({
    queryKey: ['hr-timetracking-monthly', reportEmployee, reportMonth],
    enabled: reportEmployee !== 'none' && Boolean(reportMonth),
    queryFn: async () => {
      const [year, month] = reportMonth.split('-');
      const res = await api.get<MonthlyReport>('hr/v1/time-tracking/reports/monthly', {
        params: { employee_id: Number(reportEmployee), year: Number(year), month: Number(month) },
      });
      return res.data;
    },
  });

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<TimeEntry | null>(null);
  const [form, setForm] = useState(emptyForm);

  const saveMutation = useMutation({
    mutationFn: async () => {
      const payload = {
        employee_id: Number(form.employee),
        date: form.date,
        start_time: form.start_time,
        end_time: form.end_time,
        break_minutes: Number(form.break_minutes) || 0,
        project: form.project || null,
        task: form.task || null,
        description: form.description || null,
      };
      if (editing) {
        // Записи живут под /entries/ — корень раздела только читает.
        const { employee_id, ...patch } = payload;
        const res = await api.patch(`hr/v1/time-tracking/entries/${editing.id}/`, patch);
        return res.data;
      }
      const res = await api.post('hr/v1/time-tracking/entries/', payload);
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hr-timetracking'] });
      queryClient.invalidateQueries({ queryKey: ['hr-timetracking-monthly'] });
      setDialogOpen(false);
      setEditing(null);
      setForm(emptyForm);
    },
    onError: (err) => reportApiError(err, t('hr.common.unknownError')),
  });

  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`hr/v1/time-tracking/entries/${id}/`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hr-timetracking'] });
      queryClient.invalidateQueries({ queryKey: ['hr-timetracking-monthly'] });
    },
    onError: (err) => reportApiError(err, t('hr.common.unknownError')),
  });

  const startCreate = () => {
    setEditing(null);
    setForm({ ...emptyForm, date: new Date().toISOString().slice(0, 10) });
    setDialogOpen(true);
  };

  const startEdit = (entry: TimeEntry) => {
    setEditing(entry);
    setForm({
      employee: String(entry.employee_id),
      date: entry.date || '',
      start_time: hhmm(entry.start_time),
      end_time: hhmm(entry.end_time),
      break_minutes: String(entry.break_minutes ?? 0),
      project: entry.project || '',
      task: entry.task || '',
      description: entry.description || '',
    });
    setDialogOpen(true);
  };

  if (isLoading) {
    return (
      <HRLayout title={t('hr.pages.timeTracking.title')} subtitle={t('hr.pages.timeTracking.subtitle')}>
        <div className="rounded-2xl border bg-card/70 p-8 text-center">{t('hr.common.loading')}</div>
      </HRLayout>
    );
  }
  if (error) {
    return (
      <HRLayout title={t('hr.pages.timeTracking.title')} subtitle={t('hr.pages.timeTracking.subtitle')}>
        <div className="rounded-2xl border bg-card/70 p-8 text-center text-red-500">
          {t('hr.pages.timeTracking.error')}
        </div>
      </HRLayout>
    );
  }

  const isValid =
    form.employee !== 'none' && Boolean(form.date) && Boolean(form.start_time) && Boolean(form.end_time);

  return (
    <HRLayout title={t('hr.pages.timeTracking.title')} subtitle={t('hr.pages.timeTracking.subtitle')}>
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div className="text-sm text-muted-foreground">{t('hr.common.total')}: {entries?.length || 0}</div>
        <Dialog
          open={dialogOpen}
          onOpenChange={(open) => {
            setDialogOpen(open);
            if (!open) {
              setEditing(null);
              setForm(emptyForm);
            }
          }}
        >
          <DialogTrigger asChild>
            <Button onClick={startCreate}>{t('hr.pages.timeTracking.add')}</Button>
          </DialogTrigger>
          <DialogContent className="max-w-2xl">
            <DialogHeader>
              <DialogTitle>{editing ? t('hr.pages.timeTracking.edit') : t('hr.pages.timeTracking.new')}</DialogTitle>
              <DialogDescription>{t('hr.pages.timeTracking.subtitle')}</DialogDescription>
            </DialogHeader>
            <div className="grid gap-4">
              <label className="grid gap-2 text-sm">
                {t('hr.pages.timeTracking.fields.employee')}
                <Select
                  value={form.employee}
                  disabled={Boolean(editing)}
                  onValueChange={(value) => setForm({ ...form, employee: value })}
                >
                  <SelectTrigger>
                    <SelectValue placeholder={t('hr.pages.timeTracking.placeholders.selectEmployee')} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">{t('hr.pages.timeTracking.placeholders.selectEmployee')}</SelectItem>
                    {employees?.map((emp) => (
                      <SelectItem key={emp.id} value={String(emp.id)}>
                        {employeeName(emp)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </label>

              <div className="grid gap-4 md:grid-cols-4">
                <label className="grid gap-2 text-sm">
                  {t('hr.pages.timeTracking.fields.date')}
                  <Input type="date" value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} />
                </label>
                <label className="grid gap-2 text-sm">
                  {t('hr.pages.timeTracking.fields.startTime')}
                  <Input type="time" value={form.start_time} onChange={(e) => setForm({ ...form, start_time: e.target.value })} />
                </label>
                <label className="grid gap-2 text-sm">
                  {t('hr.pages.timeTracking.fields.endTime')}
                  <Input type="time" value={form.end_time} onChange={(e) => setForm({ ...form, end_time: e.target.value })} />
                </label>
                <label className="grid gap-2 text-sm">
                  {t('hr.pages.timeTracking.fields.breakMinutes')}
                  <Input
                    type="number"
                    min={0}
                    value={form.break_minutes}
                    onChange={(e) => setForm({ ...form, break_minutes: e.target.value })}
                  />
                </label>
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <label className="grid gap-2 text-sm">
                  {t('hr.pages.timeTracking.fields.project')}
                  <Input value={form.project} onChange={(e) => setForm({ ...form, project: e.target.value })} />
                </label>
                <label className="grid gap-2 text-sm">
                  {t('hr.pages.timeTracking.fields.task')}
                  <Input value={form.task} onChange={(e) => setForm({ ...form, task: e.target.value })} />
                </label>
              </div>

              <label className="grid gap-2 text-sm">
                {t('hr.pages.timeTracking.fields.description')}
                <Textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
              </label>

              <div className="flex justify-end gap-2">
                <Button variant="outline" onClick={() => setDialogOpen(false)}>{t('hr.common.cancel')}</Button>
                <Button onClick={() => saveMutation.mutate()} disabled={!isValid || saveMutation.isPending}>
                  {saveMutation.isPending ? t('hr.common.saving') : t('hr.common.save')}
                </Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>
      </div>

      {/* Месячный итог — reports/monthly */}
      <div className="rounded-2xl border bg-card p-4">
        <div className="grid gap-3 md:grid-cols-3 items-end">
          <label className="grid gap-2 text-sm">
            {t('hr.pages.timeTracking.report.employee')}
            <Select value={reportEmployee} onValueChange={setReportEmployee}>
              <SelectTrigger>
                <SelectValue placeholder={t('hr.pages.timeTracking.placeholders.selectEmployee')} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">{t('hr.pages.timeTracking.placeholders.selectEmployee')}</SelectItem>
                {employees?.map((emp) => (
                  <SelectItem key={emp.id} value={String(emp.id)}>
                    {employeeName(emp)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </label>
          <label className="grid gap-2 text-sm">
            {t('hr.pages.timeTracking.report.month')}
            <Input type="month" value={reportMonth} onChange={(e) => setReportMonth(e.target.value)} />
          </label>
          <div className="text-sm">
            <div className="text-muted-foreground">{t('hr.pages.timeTracking.report.total')}</div>
            <div className="text-lg font-semibold">
              {reportEmployee === 'none'
                ? '—'
                : reportLoading
                  ? t('hr.common.loading')
                  : formatMinutes(monthlyReport?.total_minutes || 0)}
            </div>
          </div>
        </div>
      </div>

      <div className="bg-card rounded-2xl border overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t('hr.pages.timeTracking.table.employee')}</TableHead>
              <TableHead>{t('hr.pages.timeTracking.table.date')}</TableHead>
              <TableHead>{t('hr.pages.timeTracking.table.interval')}</TableHead>
              <TableHead>{t('hr.pages.timeTracking.table.break')}</TableHead>
              <TableHead>{t('hr.pages.timeTracking.table.worked')}</TableHead>
              <TableHead>{t('hr.pages.timeTracking.table.projectTask')}</TableHead>
              <TableHead className="text-right">{t('hr.pages.timeTracking.table.actions')}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(entries?.length || 0) === 0 && (
              <TableRow>
                <TableCell colSpan={7} className="text-center text-muted-foreground py-8">
                  {t('hr.pages.timeTracking.empty')}
                </TableCell>
              </TableRow>
            )}
            {entries?.map((entry) => (
              <TableRow key={entry.id}>
                <TableCell className="font-medium">
                  {employeeName(employeeById.get(entry.employee_id)) || `#${entry.employee_id}`}
                </TableCell>
                <TableCell>{new Date(entry.date).toLocaleDateString()}</TableCell>
                <TableCell>{hhmm(entry.start_time)} — {hhmm(entry.end_time)}</TableCell>
                <TableCell>{entry.break_minutes || 0}</TableCell>
                <TableCell>{formatMinutes(workedMinutes(entry))}</TableCell>
                <TableCell>
                  <div>{entry.project || '—'}</div>
                  {entry.task && <div className="text-xs text-muted-foreground">{entry.task}</div>}
                </TableCell>
                <TableCell className="text-right">
                  <div className="flex justify-end gap-2">
                    <Button size="sm" variant="outline" onClick={() => startEdit(entry)}>{t('hr.common.edit')}</Button>
                    {isSenior && (
                      <Button
                        size="sm"
                        variant="destructive"
                        onClick={() => {
                          if (confirm(t('hr.pages.timeTracking.deleteConfirm'))) {
                            deleteMutation.mutate(entry.id);
                          }
                        }}
                      >
                        {t('hr.common.delete')}
                      </Button>
                    )}
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </HRLayout>
  );
};

export default HRTimeTracking;
