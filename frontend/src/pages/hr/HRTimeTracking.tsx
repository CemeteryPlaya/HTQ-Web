import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import api from '@/api/client';
import HRLayout from '@/components/hr/HRLayout';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useHRLevel } from '@/hooks/useHRLevel';

interface TimeRecord {
  id: number;
  employee: number;
  employee_name: string;
  leave_type: string;
  start_date: string;
  end_date: string;
  duration_days: number;
  status: string;
  comment: string;
  approved_by_name: string | null;
}

interface EmployeeOption {
  id: number;
  full_name: string;
}

const HRTimeTracking = () => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { isSenior } = useHRLevel();
  const { data: records, isLoading, error } = useQuery({
    queryKey: ['hr-timetracking'],
    queryFn: async () => {
      const res = await api.get<TimeRecord[]>('hr/v1/time-tracking/');
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

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<TimeRecord | null>(null);
  const [form, setForm] = useState({
    employee: 'none',
    leave_type: 'vacation',
    start_date: '',
    end_date: '',
    status: 'pending',
    comment: '',
  });

  const saveMutation = useMutation({
    mutationFn: async () => {
      const payload = {
        employee: form.employee === 'none' ? undefined : Number(form.employee),
        leave_type: form.leave_type,
        start_date: form.start_date,
        end_date: form.end_date,
        status: form.status,
        comment: form.comment || '',
      } as any;
      if (editing) {
        const res = await api.put(`hr/v1/time-tracking/${editing.id}/`, payload);
        return res.data;
      }
      const res = await api.post('hr/v1/time-tracking/', payload);
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hr-timetracking'] });
      setDialogOpen(false);
      setEditing(null);
      setForm({
        employee: 'none',
        leave_type: 'vacation',
        start_date: '',
        end_date: '',
        status: 'pending',
        comment: '',
      });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`hr/v1/time-tracking/${id}/`);
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['hr-timetracking'] }),
  });

  const approveMutation = useMutation({
    mutationFn: async (id: number) => {
      const res = await api.post(`hr/v1/time-tracking/${id}/approve/`);
      return res.data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['hr-timetracking'] }),
  });

  const rejectMutation = useMutation({
    mutationFn: async (id: number) => {
      const res = await api.post(`hr/v1/time-tracking/${id}/reject/`);
      return res.data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['hr-timetracking'] }),
  });

  const startCreate = () => {
    setEditing(null);
    setForm({
      employee: 'none',
      leave_type: 'vacation',
      start_date: '',
      end_date: '',
      status: 'pending',
      comment: '',
    });
    setDialogOpen(true);
  };

  const startEdit = (record: TimeRecord) => {
    setEditing(record);
    setForm({
      employee: record.employee ? String(record.employee) : 'none',
      leave_type: record.leave_type || 'vacation',
      start_date: record.start_date || '',
      end_date: record.end_date || '',
      status: record.status || 'pending',
      comment: record.comment || '',
    });
    setDialogOpen(true);
  };

  const leaveTypeLabels: Record<string, string> = {
    vacation: t('hr.pages.timeTracking.leaveTypes.vacation'),
    sick_leave: t('hr.pages.timeTracking.leaveTypes.sickLeave'),
    day_off: t('hr.pages.timeTracking.leaveTypes.dayOff'),
    business_trip: t('hr.pages.timeTracking.leaveTypes.businessTrip'),
    unpaid: t('hr.pages.timeTracking.leaveTypes.unpaid'),
  };

  const statusLabels: Record<string, string> = {
    pending: t('hr.pages.timeTracking.status.pending'),
    approved: t('hr.pages.timeTracking.status.approved'),
    rejected: t('hr.pages.timeTracking.status.rejected'),
    cancelled: t('hr.pages.timeTracking.status.cancelled'),
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

  const statusColors: Record<string, string> = {
    pending: 'bg-yellow-500',
    approved: 'bg-green-500',
    rejected: 'bg-red-500',
    cancelled: 'bg-gray-500',
  };

  return (
    <HRLayout title={t('hr.pages.timeTracking.title')} subtitle={t('hr.pages.timeTracking.subtitle')}>
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div className="text-sm text-muted-foreground">{t('hr.common.total')}: {records?.length || 0}</div>
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>
            <Button onClick={startCreate}>{t('hr.pages.timeTracking.add')}</Button>
          </DialogTrigger>
          <DialogContent className="max-w-2xl">
            <DialogHeader>
              <DialogTitle>{editing ? t('hr.pages.timeTracking.edit') : t('hr.pages.timeTracking.new')}</DialogTitle>
            </DialogHeader>
            <div className="grid gap-4">
              <label className="grid gap-2 text-sm">
                {t('hr.pages.timeTracking.fields.employee')}
                <Select value={form.employee} onValueChange={(value) => setForm({ ...form, employee: value })}>
                  <SelectTrigger>
                    <SelectValue placeholder={t('hr.pages.timeTracking.placeholders.selectEmployee')} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">{t('hr.pages.timeTracking.placeholders.selectEmployee')}</SelectItem>
                    {employees?.map((emp) => (
                      <SelectItem key={emp.id} value={String(emp.id)}>
                        {emp.full_name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </label>

              <div className="grid gap-4 md:grid-cols-2">
                <label className="grid gap-2 text-sm">
                  {t('hr.pages.timeTracking.fields.leaveType')}
                  <Select value={form.leave_type} onValueChange={(value) => setForm({ ...form, leave_type: value })}>
                    <SelectTrigger>
                      <SelectValue placeholder={t('hr.pages.timeTracking.placeholders.selectType')} />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="vacation">{t('hr.pages.timeTracking.leaveTypes.vacation')}</SelectItem>
                      <SelectItem value="sick_leave">{t('hr.pages.timeTracking.leaveTypes.sickLeave')}</SelectItem>
                      <SelectItem value="day_off">{t('hr.pages.timeTracking.leaveTypes.dayOff')}</SelectItem>
                      <SelectItem value="business_trip">{t('hr.pages.timeTracking.leaveTypes.businessTrip')}</SelectItem>
                      <SelectItem value="unpaid">{t('hr.pages.timeTracking.leaveTypes.unpaid')}</SelectItem>
                    </SelectContent>
                  </Select>
                </label>
                <label className="grid gap-2 text-sm">
                  {t('hr.pages.timeTracking.fields.status')}
                  <Select value={form.status} onValueChange={(value) => setForm({ ...form, status: value })}>
                    <SelectTrigger>
                      <SelectValue placeholder={t('hr.pages.timeTracking.placeholders.selectStatus')} />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="pending">{t('hr.pages.timeTracking.status.pending')}</SelectItem>
                      <SelectItem value="approved">{t('hr.pages.timeTracking.status.approved')}</SelectItem>
                      <SelectItem value="rejected">{t('hr.pages.timeTracking.status.rejected')}</SelectItem>
                      <SelectItem value="cancelled">{t('hr.pages.timeTracking.status.cancelled')}</SelectItem>
                    </SelectContent>
                  </Select>
                </label>
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <label className="grid gap-2 text-sm">
                  {t('hr.pages.timeTracking.fields.startDate')}
                  <Input type="date" value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} />
                </label>
                <label className="grid gap-2 text-sm">
                  {t('hr.pages.timeTracking.fields.endDate')}
                  <Input type="date" value={form.end_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })} />
                </label>
              </div>

              <label className="grid gap-2 text-sm">
                {t('hr.pages.timeTracking.fields.comment')}
                <Textarea value={form.comment} onChange={(e) => setForm({ ...form, comment: e.target.value })} />
              </label>

              <div className="flex justify-end gap-2">
                <Button variant="outline" onClick={() => setDialogOpen(false)}>{t('hr.common.cancel')}</Button>
                <Button onClick={() => saveMutation.mutate()} disabled={form.employee === 'none' || !form.start_date || !form.end_date || saveMutation.isPending}>
                  {saveMutation.isPending ? t('hr.common.saving') : t('hr.common.save')}
                </Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>
      </div>

      <div className="bg-card rounded-2xl border overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t('hr.pages.timeTracking.table.employee')}</TableHead>
              <TableHead>{t('hr.pages.timeTracking.table.type')}</TableHead>
              <TableHead>{t('hr.pages.timeTracking.table.period')}</TableHead>
              <TableHead>{t('hr.pages.timeTracking.table.days')}</TableHead>
              <TableHead>{t('hr.pages.timeTracking.table.status')}</TableHead>
              <TableHead>{t('hr.pages.timeTracking.table.approvedBy')}</TableHead>
              <TableHead className="text-right">{t('hr.pages.timeTracking.table.actions')}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {records?.map((record) => (
              <TableRow key={record.id}>
                <TableCell className="font-medium">{record.employee_name}</TableCell>
                <TableCell>{leaveTypeLabels[record.leave_type] || record.leave_type}</TableCell>
                <TableCell>
                  {new Date(record.start_date).toLocaleDateString()} - {new Date(record.end_date).toLocaleDateString()}
                </TableCell>
                <TableCell>{record.duration_days}</TableCell>
                <TableCell>
                  <Badge className={statusColors[record.status]}>{statusLabels[record.status] || record.status}</Badge>
                </TableCell>
                <TableCell>{record.approved_by_name || '—'}</TableCell>
                <TableCell className="text-right">
                  <div className="flex justify-end gap-2">
                    {record.status === 'pending' && (
                      <>
                        <Button size="sm" variant="secondary" onClick={() => approveMutation.mutate(record.id)}>
                          {t('hr.common.approve')}
                        </Button>
                        <Button size="sm" variant="outline" onClick={() => rejectMutation.mutate(record.id)}>
                          {t('hr.common.reject')}
                        </Button>
                      </>
                    )}
                    <Button size="sm" variant="outline" onClick={() => startEdit(record)}>{t('hr.common.edit')}</Button>
                    {isSenior && (
                      <Button
                        size="sm"
                        variant="destructive"
                        onClick={() => {
                          if (confirm(t('hr.pages.timeTracking.deleteConfirm'))) {
                            deleteMutation.mutate(record.id);
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
