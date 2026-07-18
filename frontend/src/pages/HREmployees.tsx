import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  fetchEmployees, fetchEmployeeStats, fetchDepartments, fetchPositions,
  fetchEmployeeUsers, createEmployee, updateEmployee, deleteEmployee,
} from '@/api/hr';
import type { Employee, EmployeeStats, Department, Position } from '@/types/hr';
import HRLayout from '@/components/hr/HRLayout';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { PhoneInput } from '@/components/ui/phone-input';
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
import {
  Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList,
} from '@/components/ui/command';
import {
  Popover, PopoverContent, PopoverTrigger,
} from '@/components/ui/popover';
import { Textarea } from '@/components/ui/textarea';
import {
  Users, UserCheck, Clock, UserX, Search, Plus, Pencil, Trash2, Loader2, AlertCircle, ChevronsUpDown, Check,
} from 'lucide-react';
import { cn } from '@/lib/utils';

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */
const formatDate = (d: string | null) => {
  if (!d) return '—';
  return new Date(d).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short', year: 'numeric' });
};

const statusBadgeVariant = (s: string) => {
  switch (s) {
    case 'active': return 'default' as const;
    case 'on_leave':
    case 'inactive': return 'secondary' as const;
    case 'dismissed':
    case 'terminated': return 'destructive' as const;
    default: return 'outline' as const;
  }
};

/** Frontend uses HR-friendly labels (``on_leave`` / ``dismissed``); backend
 * EmployeeCreate.status pattern only accepts ``active|inactive|terminated``. */
const STATUS_TO_BACKEND: Record<string, 'active' | 'inactive' | 'terminated'> = {
  active: 'active',
  on_leave: 'inactive',
  inactive: 'inactive',
  dismissed: 'terminated',
  terminated: 'terminated',
};

const STATUS_FROM_BACKEND: Record<string, string> = {
  active: 'active',
  inactive: 'on_leave',
  terminated: 'dismissed',
};

interface EmployeeForm {
  user: string;
  position: string;
  department: string;
  phone: string;
  date_hired: string;
  date_dismissed: string;
  status: string;
  notes: string;
}

const emptyForm: EmployeeForm = {
  user: 'none',
  position: 'none',
  department: 'none',
  phone: '',
  date_hired: '', date_dismissed: '', status: 'active', notes: '',
};

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */
const HREmployees = () => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  /* ---- state ---- */
  const [search, setSearch] = useState('');
  const [filterStatus, setFilterStatus] = useState<string>('all');
  const [dialogOpen, setDialogOpen] = useState(false);
  const [userPickerOpen, setUserPickerOpen] = useState(false);
  const [editing, setEditing] = useState<Employee | null>(null);
  const [form, setForm] = useState<EmployeeForm>({ ...emptyForm });
  const [formErrors, setFormErrors] = useState<Record<string, string>>({});
  const [deleteTarget, setDeleteTarget] = useState<Employee | null>(null);

  /* ---- queries ---- */
  const { data: employees = [], isLoading, isError } = useQuery({
    queryKey: ['hr-employees'],
    queryFn: () => fetchEmployees(),
    refetchInterval: 30000,
  });

  const { data: stats } = useQuery({
    queryKey: ['hr-employee-stats'],
    queryFn: fetchEmployeeStats,
  });

  const { data: departments = [] } = useQuery({
    queryKey: ['hr-departments'],
    queryFn: fetchDepartments,
  });

  const { data: positions = [] } = useQuery({
    queryKey: ['hr-positions'],
    queryFn: fetchPositions,
  });

  const { data: availableUsers = [], isFetching: usersLoading } = useQuery({
    queryKey: ['hr-employee-users', dialogOpen],
    queryFn: () => fetchEmployeeUsers(),
    enabled: dialogOpen && !editing,
  });

  /* ---- mutations ---- */
  const saveMutation = useMutation({
    mutationFn: async () => {
      const backendStatus = STATUS_TO_BACKEND[form.status] || 'active';

      if (editing) {
        // EmployeeUpdate — every field optional; only send what changed/has a value.
        const patch: Record<string, unknown> = {
          status: backendStatus,
          phone: form.phone || undefined,
          bio: form.notes || undefined,
        };
        if (form.department !== 'none') patch.department_id = Number(form.department);
        if (form.position !== 'none') patch.position_id = Number(form.position);
        if (form.date_dismissed) patch.termination_date = form.date_dismissed;
        return updateEmployee(editing.id, patch);
      }

      // EmployeeCreate — first_name/last_name/email/department_id/position_id/hire_date
      // are all REQUIRED by the backend schema. We pull name+email from the
      // selected user record so the operator only has to pick "who".
      const selected = availableUsers.find((u) => String(u.id) === form.user);
      if (!selected) throw new Error('user_required');

      const [splitFirst = '', ...splitRest] = (selected.full_name || '').trim().split(/\s+/);
      const splitLast = splitRest.join(' ');

      const payload = {
        user_id: selected.id,
        first_name: selected.first_name || splitFirst || selected.username || 'Unknown',
        last_name: selected.last_name || splitLast || '',
        email: selected.email,
        phone: form.phone || undefined,
        department_id: Number(form.department),
        position_id: Number(form.position),
        hire_date: form.date_hired,
        status: backendStatus,
        bio: form.notes || undefined,
      };
      // eslint-disable-next-line no-console
      console.debug('[hr.employees] create payload', payload);
      return createEmployee(payload as any);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hr-employees'] });
      queryClient.invalidateQueries({ queryKey: ['hr-employee-stats'] });
      closeDialog();
    },
    onError: (err: any) => {
      const data = err?.response?.data;
      // eslint-disable-next-line no-console
      console.warn('[hr.employees] save error', err?.response?.status, data);

      // FastAPI 422 shape: { detail: [{ loc: ["body","field"], msg, type }, ...] }
      if (data && Array.isArray(data.detail)) {
        const mapped: Record<string, string> = {};
        for (const item of data.detail) {
          const loc = Array.isArray(item.loc) ? item.loc : [];
          const field = loc.length ? String(loc[loc.length - 1]) : '_global';
          mapped[field] = item.msg || String(item);
        }
        if (Object.keys(mapped).length === 0) {
          mapped._global = t('hr.unknownError');
        }
        setFormErrors(mapped);
        return;
      }

      if (data && typeof data === 'object' && !data.detail) {
        const mapped: Record<string, string> = {};
        Object.entries(data).forEach(([k, v]) => {
          mapped[k] = Array.isArray(v) ? v.join('. ') : String(v);
        });
        setFormErrors(mapped);
        return;
      }

      setFormErrors({
        _global:
          (typeof data?.detail === 'string' ? data.detail : null) ||
          err?.message ||
          t('hr.unknownError'),
      });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async (emp: Employee) => deleteEmployee(emp.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hr-employees'] });
      queryClient.invalidateQueries({ queryKey: ['hr-employee-stats'] });
      setDeleteTarget(null);
    },
  });

  /* ---- filtered list ---- */
  let filtered = employees;
  if (filterStatus !== 'all') filtered = filtered.filter((e) => e.status === filterStatus);
  if (search.trim()) {
    const q = search.toLowerCase();
    filtered = filtered.filter(
      (e) =>
        e.full_name.toLowerCase().includes(q) ||
        e.username.toLowerCase().includes(q) ||
        e.email.toLowerCase().includes(q) ||
        (e.position_title || '').toLowerCase().includes(q) ||
        (e.department_name || '').toLowerCase().includes(q),
    );
  }

  /* ---- dialog helpers ---- */
  const openCreate = () => {
    setEditing(null);
    setForm({ ...emptyForm });
    setFormErrors({});
    setDialogOpen(true);
  };

  const openEdit = (emp: Employee) => {
    setEditing(emp);
    setForm({
      user: emp.user ? String(emp.user) : 'none',
      position: emp.position ? String(emp.position) : 'none',
      department: emp.department ? String(emp.department) : 'none',
      phone: emp.phone || '',
      date_hired: emp.date_hired || '',
      date_dismissed: emp.date_dismissed || '',
      status: emp.status,
      notes: emp.notes || '',
    });
    setFormErrors({});
    setDialogOpen(true);
  };

  const closeDialog = () => {
    setDialogOpen(false);
    setEditing(null);
    setForm({ ...emptyForm });
    setFormErrors({});
  };

  const handleSave = () => {
    const errs: Record<string, string> = {};
    if (!editing) {
      if (!form.user || form.user === 'none') {
        errs.user = t('hr.employees.userRequired');
      }
      if (form.department === 'none') {
        errs.department = t('hr.employees.departmentRequired', 'Выберите отдел');
      }
      if (form.position === 'none') {
        errs.position = t('hr.employees.positionRequired', 'Выберите должность');
      }
      if (!form.date_hired) {
        errs.date_hired = t('hr.employees.hireDateRequired', 'Укажите дату приёма');
      }
    }
    setFormErrors(errs);
    if (Object.keys(errs).length > 0) return;
    saveMutation.mutate();
  };

  /* ---- stat card data ---- */
  const statCards = [
    { key: 'all', count: stats?.total ?? employees.length, label: t('hr.employees.total'), icon: Users, color: 'blue' },
    { key: 'active', count: stats?.active ?? 0, label: t('hr.employees.active'), icon: UserCheck, color: 'green' },
    { key: 'on_leave', count: stats?.on_leave ?? 0, label: t('hr.employees.onLeave'), icon: Clock, color: 'amber' },
    { key: 'dismissed', count: stats?.dismissed ?? 0, label: t('hr.employees.dismissed'), icon: UserX, color: 'red' },
  ];

  /* ---------------------------------------------------------------- */
  /*  Render                                                           */
  /* ---------------------------------------------------------------- */
  return (
    <HRLayout>
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-lg bg-primary/10 flex items-center justify-center">
            <Users className="h-5 w-5 text-primary" />
          </div>
          <div>
            <h1 className="font-display text-2xl font-bold tracking-tight">{t('hr.employees.title')}</h1>
            <p className="text-sm text-muted-foreground">{t('hr.employees.subtitle')}</p>
          </div>
        </div>
        <Button onClick={openCreate} className="gap-2">
          <Plus className="h-4 w-4" /> {t('hr.employees.add')}
        </Button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
        {statCards.map((s) => (
          <Card
            key={s.key}
            className={`cursor-pointer transition-all hover:shadow-md ${filterStatus === s.key ? 'ring-2 ring-primary' : ''}`}
            onClick={() => setFilterStatus(s.key)}
          >
            <CardContent className="flex items-center gap-4 p-4">
              <div className={`h-10 w-10 rounded-full bg-${s.color}-100 dark:bg-${s.color}-900/30 flex items-center justify-center`}>
                <s.icon className={`h-5 w-5 text-${s.color}-600 dark:text-${s.color}-400`} />
              </div>
              <div>
                <p className="text-2xl font-bold">{s.count}</p>
                <p className="text-xs text-muted-foreground">{s.label}</p>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Search */}
      <div className="relative mb-6">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={t('hr.employees.searchPlaceholder')}
          className="pl-10"
        />
      </div>

      {/* Loading */}
      {isLoading && (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-14 w-full rounded-md" />
          ))}
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
      {!isLoading && !isError && filtered.length === 0 && (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16 text-center text-muted-foreground">
            <Users className="h-12 w-12 mb-4 opacity-30" />
            <p className="text-lg font-medium">{t('hr.employees.empty')}</p>
            <Button className="mt-4 gap-2" onClick={openCreate}>
              <Plus className="h-4 w-4" /> {t('hr.employees.add')}
            </Button>
          </CardContent>
        </Card>
      )}

      {/* Table */}
      {!isLoading && !isError && filtered.length > 0 && (
        <div className="bg-card rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t('hr.employees.col.name')}</TableHead>
                <TableHead>{t('hr.employees.col.position')}</TableHead>
                <TableHead>{t('hr.employees.col.department')}</TableHead>
                <TableHead>{t('hr.employees.col.phone')}</TableHead>
                <TableHead>{t('hr.employees.col.hired')}</TableHead>
                <TableHead>{t('hr.employees.col.status')}</TableHead>
                <TableHead className="text-right">{t('hr.employees.col.actions')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((emp) => (
                <TableRow key={emp.id}>
                  <TableCell>
                    <div>
                      <div className="font-medium">{emp.full_name}</div>
                      <div className="text-xs text-muted-foreground">{emp.email}</div>
                    </div>
                  </TableCell>
                  <TableCell>{emp.position_title || '—'}</TableCell>
                  <TableCell>{emp.department_name || '—'}</TableCell>
                  <TableCell>{emp.phone || '—'}</TableCell>
                  <TableCell>{formatDate(emp.date_hired)}</TableCell>
                  <TableCell>
                    <Badge variant={statusBadgeVariant(emp.status)}>
                      {t(`hr.status.${emp.status}`)}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex items-center justify-end gap-1">
                      <Button size="icon" variant="ghost" onClick={() => openEdit(emp)}>
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button size="icon" variant="ghost" className="text-destructive" onClick={() => setDeleteTarget(emp)}>
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {/* ============ Create/Edit Dialog ============ */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-lg max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{editing ? t('hr.employees.edit') : t('hr.employees.addDialog')}</DialogTitle>
            <DialogDescription>{editing ? t('hr.employees.editHint') : t('hr.employees.addHint')}</DialogDescription>
          </DialogHeader>

          <div className="grid gap-4 py-4">
            {formErrors._global && (
              <p className="text-sm text-destructive">{formErrors._global}</p>
            )}

            {!editing && (
              <div className="grid gap-2">
                <Label>{t('hr.employees.userId')}</Label>
                {/*
                  Combobox via cmdk — Radix Select inside a modal Dialog has
                  a long-standing issue where mouse clicks on items don't
                  register (keyboard arrows still work). cmdk's items are
                  plain buttons, so they're immune. Bonus: built-in search
                  for the (potentially long) user list.
                */}
                {(() => {
                  const selected = availableUsers.find((u) => String(u.id) === form.user);
                  return (
                    <Popover open={userPickerOpen} onOpenChange={setUserPickerOpen}>
                      <PopoverTrigger asChild>
                        <Button
                          type="button"
                          variant="outline"
                          role="combobox"
                          aria-expanded={userPickerOpen}
                          className="justify-between font-normal"
                        >
                          <span className={cn('truncate', !selected && 'text-muted-foreground')}>
                            {selected
                              ? `${selected.full_name} • ${selected.email}`
                              : t('hr.employees.userPlaceholder')}
                          </span>
                          <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
                        </Button>
                      </PopoverTrigger>
                      <PopoverContent
                        className="w-[--radix-popover-trigger-width] p-0"
                        align="start"
                      >
                        <Command>
                          <CommandInput placeholder={t('hr.employees.userPlaceholder') as string} />
                          <CommandList>
                            <CommandEmpty>
                              {usersLoading ? t('hr.loading', 'Загрузка…') : t('hr.employees.noUsers')}
                            </CommandEmpty>
                            <CommandGroup>
                              {availableUsers.map((u) => (
                                <CommandItem
                                  key={u.id}
                                  value={`${u.full_name} ${u.email}`}
                                  onSelect={() => {
                                    setForm((f) => ({ ...f, user: String(u.id) }));
                                    setUserPickerOpen(false);
                                  }}
                                >
                                  <Check
                                    className={cn(
                                      'mr-2 h-4 w-4',
                                      String(u.id) === form.user ? 'opacity-100' : 'opacity-0',
                                    )}
                                  />
                                  <div className="flex flex-col">
                                    <span>{u.full_name || u.email}</span>
                                    {u.full_name && (
                                      <span className="text-xs text-muted-foreground">{u.email}</span>
                                    )}
                                  </div>
                                </CommandItem>
                              ))}
                            </CommandGroup>
                          </CommandList>
                        </Command>
                      </PopoverContent>
                    </Popover>
                  );
                })()}
                {formErrors.user && <p className="text-xs text-destructive">{formErrors.user}</p>}
              </div>
            )}

            <div className="grid grid-cols-2 gap-4">
              <div className="grid gap-2">
                <Label>{t('hr.employees.col.department')}</Label>
                <Select value={form.department} onValueChange={(v) => setForm((f) => ({ ...f, department: v }))}>
                  <SelectTrigger><SelectValue placeholder="—" /></SelectTrigger>
                  <SelectContent>
                    {departments.map((d) => (
                      <SelectItem key={d.id} value={String(d.id)}>{d.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {formErrors.department && <p className="text-xs text-destructive">{formErrors.department}</p>}
              </div>
              <div className="grid gap-2">
                <Label>{t('hr.employees.col.position')}</Label>
                <Select value={form.position} onValueChange={(v) => setForm((f) => ({ ...f, position: v }))}>
                  <SelectTrigger><SelectValue placeholder="—" /></SelectTrigger>
                  <SelectContent>
                    {positions.map((p) => (
                      <SelectItem key={p.id} value={String(p.id)}>{p.title}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {formErrors.position && <p className="text-xs text-destructive">{formErrors.position}</p>}
              </div>
            </div>

            <div className="grid gap-2">
              <Label>{t('hr.employees.col.phone')}</Label>
              <PhoneInput value={form.phone} onChange={(v) => setForm((f) => ({ ...f, phone: v }))} />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="grid gap-2">
                <Label>{t('hr.employees.col.hired')}</Label>
                <Input
                  type="date"
                  value={form.date_hired}
                  onChange={(e) => setForm((f) => ({ ...f, date_hired: e.target.value }))}
                />
                {formErrors.date_hired && <p className="text-xs text-destructive">{formErrors.date_hired}</p>}
              </div>
              <div className="grid gap-2">
                <Label>{t('hr.employees.dateDismissed')}</Label>
                <Input
                  type="date"
                  value={form.date_dismissed}
                  onChange={(e) => setForm((f) => ({ ...f, date_dismissed: e.target.value }))}
                />
              </div>
            </div>

            <div className="grid gap-2">
              <Label>{t('hr.employees.col.status')}</Label>
              <Select value={form.status} onValueChange={(v) => setForm((f) => ({ ...f, status: v }))}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="active">{t('hr.status.active')}</SelectItem>
                  <SelectItem value="on_leave">{t('hr.status.on_leave')}</SelectItem>
                  <SelectItem value="dismissed">{t('hr.status.dismissed')}</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="grid gap-2">
              <Label>{t('hr.employees.notes')}</Label>
              <Textarea value={form.notes} onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))} rows={3} />
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={closeDialog}>{t('hr.cancel')}</Button>
            <Button onClick={handleSave} disabled={saveMutation.isPending} className="gap-2">
              {saveMutation.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
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
              {t('hr.deleteConfirmText', { name: deleteTarget?.full_name })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('hr.cancel')}</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => deleteTarget && deleteMutation.mutate(deleteTarget)}
            >
              {t('hr.delete')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </HRLayout>
  );
};

export default HREmployees;
