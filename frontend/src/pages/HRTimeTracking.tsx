import { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  fetchTimeRecords, createTimeRecord, approveTimeRecord, rejectTimeRecord,
  deleteTimeRecord, fetchEmployees,
} from '@/api/hr';
import type { TimeRecord, Employee } from '@/types/hr';
import HRLayout from '@/components/hr/HRLayout';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import {
  Clock, Plus, CheckCircle, XCircle, Loader2, AlertCircle,
  CalendarDays, Palmtree, Stethoscope, Briefcase, Trash2,
} from 'lucide-react';

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */
const formatDate = (d: string | null) => {
  if (!d) return '—';
  return new Date(d).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short', year: 'numeric' });
};

const leaveStatusVariant = (s: string) => {
  switch (s) {
    case 'pending': return 'secondary' as const;
    case 'approved': return 'default' as const;
    case 'rejected': return 'destructive' as const;
    case 'cancelled': return 'outline' as const;
    default: return 'outline' as const;
  }
};

const leaveTypeIcon = (lt: string) => {
  switch (lt) {
    case 'vacation': return Palmtree;
    case 'sick_leave': return Stethoscope;
    case 'business_trip': return Briefcase;
    default: return CalendarDays;
  }
};

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */
const HRTimeTracking = () => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  /* ---- state ---- */
  const [filterStatus, setFilterStatus] = useState<string>('all');
  const [filterLeaveType, setFilterLeaveType] = useState<string>('all');
  const [filterEmployee, setFilterEmployee] = useState<string>('all');
  const [dialogOpen, setDialogOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<TimeRecord | null>(null);

  /* create form */
  const [nf, setNf] = useState({ employee: '', leave_type: 'vacation', start_date: '', end_date: '', comment: '' });
  const [formErrors, setFormErrors] = useState<Record<string, string>>({});

  /* ---- queries ---- */
  const queryParams: Record<string, string> = {};
  if (filterStatus !== 'all') queryParams.status = filterStatus;
  if (filterLeaveType !== 'all') queryParams.leave_type = filterLeaveType;
  if (filterEmployee !== 'all') queryParams.employee = filterEmployee;

  const { data: records = [], isLoading, isError } = useQuery({
    queryKey: ['hr-time-tracking', filterStatus, filterLeaveType, filterEmployee],
    queryFn: () => fetchTimeRecords(Object.keys(queryParams).length ? queryParams : undefined),
    refetchInterval: 30000,
  });

  const { data: employees = [] } = useQuery({
    queryKey: ['hr-employees'],
    queryFn: () => fetchEmployees(),
  });

  /* ---- mutations ---- */
  const createMut = useMutation({
    mutationFn: async () => createTimeRecord({
      employee: Number(nf.employee) as any,
      leave_type: nf.leave_type as any,
      start_date: nf.start_date,
      end_date: nf.end_date,
      comment: nf.comment,
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hr-time-tracking'] });
      closeDialog();
    },
    onError: (err: any) => {
      const data = err?.response?.data;
      if (typeof data === 'object') {
        const mapped: Record<string, string> = {};
        Object.entries(data).forEach(([k, v]) => {
          mapped[k] = Array.isArray(v) ? v.join('. ') : String(v);
        });
        setFormErrors(mapped);
      } else {
        setFormErrors({ _global: err?.message || t('hr.unknownError') });
      }
    },
  });

  const approveMut = useMutation({
    mutationFn: async (id: number) => approveTimeRecord(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hr-time-tracking'] });
      queryClient.invalidateQueries({ queryKey: ['hr-employees'] });
      queryClient.invalidateQueries({ queryKey: ['hr-employee-stats'] });
    },
  });

  const rejectMut = useMutation({
    mutationFn: async (id: number) => rejectTimeRecord(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hr-time-tracking'] });
      queryClient.invalidateQueries({ queryKey: ['hr-employees'] });
      queryClient.invalidateQueries({ queryKey: ['hr-employee-stats'] });
    },
  });

  const deleteMut = useMutation({
    mutationFn: async (rec: TimeRecord) => deleteTimeRecord(rec.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hr-time-tracking'] });
      queryClient.invalidateQueries({ queryKey: ['hr-employees'] });
      queryClient.invalidateQueries({ queryKey: ['hr-employee-stats'] });
      setDeleteTarget(null);
    },
  });

  /* ---- stats ---- */
  const pendingCount = records.filter((r) => r.status === 'pending').length;
  const approvedCount = records.filter((r) => r.status === 'approved').length;
  const vacationCount = records.filter((r) => r.leave_type === 'vacation').length;
  const sickCount = records.filter((r) => r.leave_type === 'sick_leave').length;

  /* ---- dialog ---- */
  const closeDialog = () => {
    setDialogOpen(false);
    setNf({ employee: '', leave_type: 'vacation', start_date: '', end_date: '', comment: '' });
    setFormErrors({});
  };

  const handleCreate = () => {
    const errs: Record<string, string> = {};
    if (!nf.employee) errs.employee = t('hr.timeTracking.employeeRequired');
    if (!nf.start_date) errs.start_date = t('hr.timeTracking.startRequired');
    if (!nf.end_date) errs.end_date = t('hr.timeTracking.endRequired');
    setFormErrors(errs);
    if (Object.keys(errs).length > 0) return;
    createMut.mutate();
  };

  /* ---------------------------------------------------------------- */
  /*  Render                                                           */
  /* ---------------------------------------------------------------- */
  return (
    <HRLayout>
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-lg bg-primary/10 flex items-center justify-center">
            <Clock className="h-5 w-5 text-primary" />
          </div>
          <div>
            <h1 className="font-display text-2xl font-bold tracking-tight">{t('hr.timeTracking.title')}</h1>
            <p className="text-sm text-muted-foreground">{t('hr.timeTracking.subtitle')}</p>
          </div>
        </div>
        <Button onClick={() => setDialogOpen(true)} className="gap-2">
          <Plus className="h-4 w-4" /> {t('hr.timeTracking.add')}
        </Button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
        <Card>
          <CardContent className="flex items-center gap-4 p-4">
            <div className="h-10 w-10 rounded-full bg-amber-100 dark:bg-amber-900/30 flex items-center justify-center">
              <Clock className="h-5 w-5 text-amber-600 dark:text-amber-400" />
            </div>
            <div>
              <p className="text-2xl font-bold">{pendingCount}</p>
              <p className="text-xs text-muted-foreground">{t('hr.timeTracking.pending')}</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex items-center gap-4 p-4">
            <div className="h-10 w-10 rounded-full bg-green-100 dark:bg-green-900/30 flex items-center justify-center">
              <CheckCircle className="h-5 w-5 text-green-600 dark:text-green-400" />
            </div>
            <div>
              <p className="text-2xl font-bold">{approvedCount}</p>
              <p className="text-xs text-muted-foreground">{t('hr.timeTracking.approved')}</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex items-center gap-4 p-4">
            <div className="h-10 w-10 rounded-full bg-blue-100 dark:bg-blue-900/30 flex items-center justify-center">
              <Palmtree className="h-5 w-5 text-blue-600 dark:text-blue-400" />
            </div>
            <div>
              <p className="text-2xl font-bold">{vacationCount}</p>
              <p className="text-xs text-muted-foreground">{t('hr.leaveType.vacation')}</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex items-center gap-4 p-4">
            <div className="h-10 w-10 rounded-full bg-red-100 dark:bg-red-900/30 flex items-center justify-center">
              <Stethoscope className="h-5 w-5 text-red-600 dark:text-red-400" />
            </div>
            <div>
              <p className="text-2xl font-bold">{sickCount}</p>
              <p className="text-xs text-muted-foreground">{t('hr.leaveType.sick_leave')}</p>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Filters */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center gap-3 mb-6">
        <Select value={filterStatus} onValueChange={setFilterStatus}>
          <SelectTrigger className="w-40">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t('hr.timeTracking.allStatuses')}</SelectItem>
            {['pending', 'approved', 'rejected', 'cancelled'].map((s) => (
              <SelectItem key={s} value={s}>{t(`hr.leaveStatus.${s}`)}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={filterLeaveType} onValueChange={setFilterLeaveType}>
          <SelectTrigger className="w-44">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t('hr.timeTracking.allTypes')}</SelectItem>
            {['vacation', 'sick_leave', 'day_off', 'business_trip', 'unpaid'].map((lt) => (
              <SelectItem key={lt} value={lt}>{t(`hr.leaveType.${lt}`)}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={filterEmployee} onValueChange={setFilterEmployee}>
          <SelectTrigger className="w-52">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t('hr.documents.allEmployees')}</SelectItem>
            {employees.map((emp) => (
              <SelectItem key={emp.id} value={String(emp.id)}>{emp.full_name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Loading */}
      {isLoading && (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => <Skeleton key={i} className="h-14 w-full rounded-md" />)}
        </div>
      )}

      {/* Error */}
      {isError && (
        <Card className="border-destructive">
          <CardContent className="flex items-center gap-3 p-6 text-destructive">
            <AlertCircle className="h-5 w-5 shrink-0" />
            <p>{t('hr.loadError')}</p>
          </CardContent>
        </Card>
      )}

      {/* Empty */}
      {!isLoading && !isError && records.length === 0 && (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16 text-center text-muted-foreground">
            <Clock className="h-12 w-12 mb-4 opacity-30" />
            <p className="text-lg font-medium">{t('hr.timeTracking.empty')}</p>
            <Button className="mt-4 gap-2" onClick={() => setDialogOpen(true)}>
              <Plus className="h-4 w-4" /> {t('hr.timeTracking.add')}
            </Button>
          </CardContent>
        </Card>
      )}

      {/* Table */}
      {!isLoading && !isError && records.length > 0 && (
        <div className="bg-card rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t('hr.timeTracking.col.employee')}</TableHead>
                <TableHead>{t('hr.timeTracking.col.type')}</TableHead>
                <TableHead>{t('hr.timeTracking.col.period')}</TableHead>
                <TableHead>{t('hr.timeTracking.col.days')}</TableHead>
                <TableHead>{t('hr.timeTracking.col.status')}</TableHead>
                <TableHead>{t('hr.timeTracking.col.approvedBy')}</TableHead>
                <TableHead className="text-right">{t('hr.timeTracking.col.actions')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {records.map((rec) => {
                const Icon = leaveTypeIcon(rec.leave_type);
                return (
                  <TableRow key={rec.id}>
                    <TableCell className="font-medium">{rec.employee_name}</TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <Icon className="h-4 w-4 text-muted-foreground" />
                        {t(`hr.leaveType.${rec.leave_type}`)}
                      </div>
                    </TableCell>
                    <TableCell>
                      {formatDate(rec.start_date)} — {formatDate(rec.end_date)}
                    </TableCell>
                    <TableCell>{rec.duration_days}</TableCell>
                    <TableCell>
                      <Badge variant={leaveStatusVariant(rec.status)}>{t(`hr.leaveStatus.${rec.status}`)}</Badge>
                    </TableCell>
                    <TableCell>{rec.approved_by_name || '—'}</TableCell>
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-1">
                        {rec.status === 'pending' && (
                          <>
                            <Button
                              size="sm"
                              variant="outline"
                              className="gap-1 text-green-600"
                              onClick={() => approveMut.mutate(rec.id)}
                              disabled={approveMut.isPending}
                            >
                              <CheckCircle className="h-3.5 w-3.5" />
                              {t('hr.timeTracking.approve')}
                            </Button>
                            <Button
                              size="sm"
                              variant="outline"
                              className="gap-1 text-destructive"
                              onClick={() => rejectMut.mutate(rec.id)}
                              disabled={rejectMut.isPending}
                            >
                              <XCircle className="h-3.5 w-3.5" />
                              {t('hr.timeTracking.reject')}
                            </Button>
                          </>
                        )}
                        <Button
                          size="icon"
                          variant="ghost"
                          className="text-destructive h-8 w-8"
                          onClick={() => setDeleteTarget(rec)}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}

      {/* ============ Create Dialog ============ */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{t('hr.timeTracking.addDialog')}</DialogTitle>
            <DialogDescription>{t('hr.timeTracking.addHint')}</DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            {formErrors._global && <p className="text-sm text-destructive">{formErrors._global}</p>}

            <div className="grid gap-2">
              <Label>{t('hr.timeTracking.col.employee')}</Label>
              <Select value={nf.employee} onValueChange={(v) => setNf((f) => ({ ...f, employee: v }))}>
                <SelectTrigger><SelectValue placeholder="—" /></SelectTrigger>
                <SelectContent>
                  {employees.map((emp) => (
                    <SelectItem key={emp.id} value={String(emp.id)}>{emp.full_name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {formErrors.employee && <p className="text-xs text-destructive">{formErrors.employee}</p>}
            </div>

            <div className="grid gap-2">
              <Label>{t('hr.timeTracking.col.type')}</Label>
              <Select value={nf.leave_type} onValueChange={(v) => setNf((f) => ({ ...f, leave_type: v }))}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {['vacation', 'sick_leave', 'day_off', 'business_trip', 'unpaid'].map((lt) => (
                    <SelectItem key={lt} value={lt}>{t(`hr.leaveType.${lt}`)}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="grid gap-2">
                <Label>{t('hr.timeTracking.startDate')}</Label>
                <Input type="date" value={nf.start_date} onChange={(e) => setNf((f) => ({ ...f, start_date: e.target.value }))} />
                {formErrors.start_date && <p className="text-xs text-destructive">{formErrors.start_date}</p>}
              </div>
              <div className="grid gap-2">
                <Label>{t('hr.timeTracking.endDate')}</Label>
                <Input type="date" value={nf.end_date} onChange={(e) => setNf((f) => ({ ...f, end_date: e.target.value }))} />
                {formErrors.end_date && <p className="text-xs text-destructive">{formErrors.end_date}</p>}
              </div>
            </div>

            <div className="grid gap-2">
              <Label>{t('hr.timeTracking.comment')}</Label>
              <Textarea value={nf.comment} onChange={(e) => setNf((f) => ({ ...f, comment: e.target.value }))} rows={3} />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={closeDialog}>{t('hr.cancel')}</Button>
            <Button onClick={handleCreate} disabled={createMut.isPending} className="gap-2">
              {createMut.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              {t('hr.save')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ============ Delete confirmation ============ */}
      <AlertDialog open={!!deleteTarget} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('hr.deleteConfirmTitle')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('hr.deleteConfirmText', { name: deleteTarget?.employee_name })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('hr.cancel')}</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => deleteTarget && deleteMut.mutate(deleteTarget)}
            >
              {t('hr.delete')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </HRLayout>
  );
};

export default HRTimeTracking;
