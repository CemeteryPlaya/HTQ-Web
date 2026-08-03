import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  IdCard,
  MoreHorizontal,
  Pencil,
  Search,
  Share2,
  Trash2,
  UserPlus,
} from 'lucide-react';
import { ShareEmployeeDialog } from '@/components/hr/ShareEmployeeDialog';
import { EmployeeFormDialog } from '@/components/hr/EmployeeFormDialog';
import { Employee, relationLabel } from '@/components/hr/employeeCommon';
import {
  deleteEmployee,
  fetchEmployees,
} from '@/api/hr';
import HRLayout from '@/components/hr/HRLayout';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { cn } from '@/lib/utils';
import { useHRLevel } from '@/hooks/useHRLevel';

const STATUS_BADGE: Record<string, { className: string; dot: string }> = {
  active:     { className: 'bg-emerald-500/10 text-emerald-700 border-emerald-300', dot: 'bg-emerald-500' },
  inactive:   { className: 'bg-amber-500/10 text-amber-700 border-amber-300',       dot: 'bg-amber-500' },
  on_leave:   { className: 'bg-amber-500/10 text-amber-700 border-amber-300',       dot: 'bg-amber-500' },
  terminated: { className: 'bg-rose-500/10 text-rose-700 border-rose-300',          dot: 'bg-rose-500' },
  dismissed:  { className: 'bg-rose-500/10 text-rose-700 border-rose-300',          dot: 'bg-rose-500' },
  suspended:  { className: 'bg-zinc-500/10 text-zinc-700 border-zinc-300',          dot: 'bg-zinc-500' },
  pending:    { className: 'bg-sky-500/10 text-sky-700 border-sky-300',             dot: 'bg-sky-500' },
  rejected:   { className: 'bg-rose-500/10 text-rose-700 border-rose-300',          dot: 'bg-rose-500' },
};

const initialsOf = (fullName: string, fallback: string) => {
  const parts = (fullName || fallback || '?').trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return '?';
  if (parts.length === 1) return parts[0]!.slice(0, 2).toUpperCase();
  return (parts[0]![0] + parts[1]![0]).toUpperCase();
};

const formatShortName = (last: string, first: string, patronymic: string): string => {
  const initials = [first, patronymic]
    .filter(Boolean)
    .map((part) => part[0]!.toUpperCase() + '.')
    .join(' ');
  return [last, initials].filter(Boolean).join(' ').trim();
};

const HREmployees = () => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  // Lifted share-dialog state — opened from the row action button. ``null``
  // means closed; a partial Employee carries id + display name only.
  const [shareTarget, setShareTarget] = useState<{ id: number; full_name: string } | null>(null);
  const {
    level,
    hasHrAccess,
    canWriteBasic,
    canCreateEmployee,
    canDeleteEmployee,
    isLoading: levelLoading,
  } = useHRLevel();
  const { data: employees, isLoading, error } = useQuery({
    queryKey: ['hr-employees'],
    queryFn: () => fetchEmployees({ limit: '200' }),
    enabled: hasHrAccess,
  });

  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');

  const visibleEmployees = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (employees ?? []).filter((emp) => {
      if (statusFilter !== 'all' && emp.status !== statusFilter) return false;
      if (!q) return true;
      const hay = [
        emp.last_name, emp.first_name, emp.middle_name, emp.full_name,
        emp.email, emp.phone,
        relationLabel(emp.position, 'title') || emp.position_title,
        relationLabel(emp.department, 'name') || emp.department_name,
      ].filter(Boolean).join(' ').toLowerCase();
      return hay.includes(q);
    });
  }, [employees, search, statusFilter]);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<Employee | null>(null);

  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      await deleteEmployee(id);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hr-employees'] });
      queryClient.invalidateQueries({ queryKey: ['hr-employee-users'] });
    },
  });

  const startCreate = () => { setEditing(null); setDialogOpen(true); };
  const startEdit = (emp: Employee) => { setEditing(emp); setDialogOpen(true); };

  // Диплинк `/hr/employees?edit=<id>` — им пользуется кнопка «Редактировать»
  // на карточке сотрудника (HREmployeeCard). До этого параметр никто не читал,
  // и кнопка просто уводила на список, ничего не открывая.
  // Параметр снимаем сразу после открытия: иначе он остался бы в истории и
  // повторно открывал бы диалог при возврате «назад».
  useEffect(() => {
    const editId = Number(searchParams.get('edit'));
    if (!Number.isFinite(editId) || editId <= 0 || !employees) return;
    const target = employees.find((e) => e.id === editId);
    if (!target) return;
    startEdit(target);
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.delete('edit');
      return next;
    }, { replace: true });
    // startEdit пересоздаётся каждый рендер и в зависимостях не нужен: эффект
    // должен сработать на появление employees или параметра, а не на ререндер.
  }, [employees, searchParams, setSearchParams]);

  const statusLabels: Record<string, string> = {
    active: t('hr.pages.employees.status.active'),
    on_leave: t('hr.pages.employees.status.onLeave'),
    dismissed: t('hr.pages.employees.status.dismissed'),
    inactive: t('hr.pages.employees.status.inactive', 'Неактивен'),
    terminated: t('hr.pages.employees.status.terminated', 'Уволен'),
    suspended: t('hr.pages.employees.status.suspended', 'Приостановлен'),
    pending: t('hr.pages.employees.status.pending', 'Ожидает'),
    rejected: t('hr.pages.employees.status.rejected', 'Отклонен'),
  };

  if (levelLoading || isLoading) {
    return (
      <HRLayout title={t('hr.pages.employees.title')} subtitle={t('hr.pages.employees.subtitle')}>
        <div className="rounded-2xl border bg-card/70 p-8 text-center">{t('hr.common.loading')}</div>
      </HRLayout>
    );
  }

  if (!hasHrAccess) {
    return (
      <HRLayout title={t('hr.pages.employees.title')} subtitle={t('hr.pages.employees.subtitle')}>
        <div className="rounded-2xl border bg-card/70 p-8 text-center text-muted-foreground">
          {t('hr.common.accessDenied', 'Недостаточно прав для HR-раздела')}
        </div>
      </HRLayout>
    );
  }

  if (error) {
    return (
      <HRLayout title={t('hr.pages.employees.title')} subtitle={t('hr.pages.employees.subtitle')}>
        <div className="rounded-2xl border bg-card/70 p-8 text-center text-red-500">
          <h2 className="text-xl font-semibold mb-2">{t('hr.pages.employees.error')}</h2>
          <p>{(error as any)?.message || t('hr.common.unknownError')}</p>
        </div>
      </HRLayout>
    );
  }

  return (
    <>
      <HRLayout title={t('hr.pages.employees.title')} subtitle={t('hr.pages.employees.subtitle')}>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex flex-1 flex-wrap items-center gap-2">
            <div className="relative flex-1 min-w-[200px] max-w-md">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={t('hr.pages.employees.searchPlaceholder', 'Поиск по ФИО, email, телефону, должности…')}
                className="pl-8 h-9"
              />
            </div>
            <Select value={statusFilter} onValueChange={setStatusFilter}>
              <SelectTrigger className="h-9 w-[160px] text-sm">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t('hr.pages.employees.filters.allStatuses', 'Все статусы')}</SelectItem>
                <SelectItem value="active">{t('hr.pages.employees.status.active')}</SelectItem>
                <SelectItem value="inactive">{t('hr.pages.employees.status.inactive', 'Неактивен')}</SelectItem>
                <SelectItem value="terminated">{t('hr.pages.employees.status.terminated', 'Уволен')}</SelectItem>
              </SelectContent>
            </Select>
            <div className="text-xs text-muted-foreground whitespace-nowrap">
              {t('hr.common.total')}: {visibleEmployees.length}
              {employees && visibleEmployees.length !== employees.length ? ` / ${employees.length}` : ''}
              {level && <span className="ml-2 uppercase tracking-wide">({level.replace('_', ' ')})</span>}
            </div>
          </div>
          {canCreateEmployee && (
            <Button onClick={startCreate} className="h-9 shrink-0">
              <UserPlus className="mr-2 h-4 w-4" />
              {t('hr.pages.employees.add')}
            </Button>
          )}
        </div>

        <div className="bg-card rounded-2xl border">
          <Table className="text-sm">
            <TableHeader>
              <TableRow>
                <TableHead className="min-w-[220px]">{t('hr.pages.employees.table.employee', 'Сотрудник')}</TableHead>
                <TableHead className="min-w-[200px]">{t('hr.pages.employees.table.position')}</TableHead>
                <TableHead className="hidden lg:table-cell w-[140px]">{t('hr.pages.employees.table.phone')}</TableHead>
                <TableHead className="w-[130px]">{t('hr.pages.employees.table.status')}</TableHead>
                <TableHead className="hidden xl:table-cell w-[110px]">{t('hr.pages.employees.table.hired')}</TableHead>
                <TableHead className="w-[100px] text-right">{t('hr.pages.employees.table.actions')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visibleEmployees.map((emp) => {
                let lastName = emp.last_name || '';
                let firstName = emp.first_name || '';
                let patronymic = emp.middle_name || '';
                if (!lastName && !firstName && emp.full_name) {
                  const parts = emp.full_name.trim().split(/\s+/);
                  lastName = parts[0] || '';
                  firstName = parts[1] || '';
                  patronymic = parts.slice(2).join(' ');
                }
                const fullName =
                  emp.full_name
                  || [lastName, firstName, patronymic].filter(Boolean).join(' ')
                  || emp.email;
                const shortName = formatShortName(lastName, firstName, patronymic) || fullName;

                const positionTitle =
                  relationLabel(emp.position, 'title') || emp.position_title || '';
                const departmentName =
                  relationLabel(emp.department, 'name') || emp.department_name || '';
                const hiredAt = emp.hire_date || emp.date_hired || null;
                const statusKey = emp.status || 'active';
                const badge = STATUS_BADGE[statusKey] ?? STATUS_BADGE.active!;

                return (
                  <TableRow
                    key={emp.id}
                    className="cursor-pointer hover:bg-muted/40"
                    onClick={() => navigate(`/hr/employees/${emp.id}`)}
                  >
                    <TableCell className="py-2">
                      <div className="flex items-center gap-3 min-w-0">
                        <Avatar className="h-9 w-9 shrink-0">
                          {emp.avatar_url && <AvatarImage src={emp.avatar_url} alt={fullName} />}
                          <AvatarFallback className="text-xs">{initialsOf(fullName, emp.email)}</AvatarFallback>
                        </Avatar>
                        <div className="min-w-0">
                          <div className="truncate font-medium" title={fullName}>{shortName || '—'}</div>
                          <div className="truncate text-xs text-muted-foreground" title={emp.email}>{emp.email}</div>
                        </div>
                      </div>
                    </TableCell>
                    <TableCell className="py-2">
                      <div className="min-w-0">
                        <div className="truncate" title={positionTitle}>{positionTitle || '—'}</div>
                        <div className="truncate text-xs text-muted-foreground" title={departmentName}>
                          {departmentName || '—'}
                        </div>
                      </div>
                    </TableCell>
                    <TableCell className="hidden lg:table-cell py-2 text-muted-foreground">
                      {emp.phone || '—'}
                    </TableCell>
                    <TableCell className="py-2">
                      <span
                        className={cn(
                          'inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium',
                          badge.className,
                        )}
                      >
                        <span className={cn('h-1.5 w-1.5 rounded-full', badge.dot)} />
                        {statusLabels[statusKey] || statusKey}
                      </span>
                    </TableCell>
                    <TableCell className="hidden xl:table-cell py-2 text-muted-foreground">
                      {hiredAt ? new Date(hiredAt).toLocaleDateString() : '—'}
                    </TableCell>
                    <TableCell className="py-2 text-right" onClick={(e) => e.stopPropagation()}>
                      <div className="flex items-center justify-end gap-1">
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-8 w-8 p-0"
                          title={t('hr.pages.employees.openCard', 'Открыть карточку')}
                          onClick={() => navigate(`/hr/employees/${emp.id}`)}
                        >
                          <IdCard className="h-4 w-4" />
                        </Button>
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button
                              size="sm"
                              variant="ghost"
                              className="h-8 w-8 p-0"
                              title={t('hr.common.more', 'Ещё')}
                            >
                              <MoreHorizontal className="h-4 w-4" />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end" className="w-48">
                            <DropdownMenuItem
                              onClick={() =>
                                setShareTarget({
                                  id: emp.id,
                                  full_name: fullName,
                                })
                              }
                            >
                              <Share2 className="mr-2 h-4 w-4" />
                              {t('hr.pages.employees.actions.share', 'Поделиться')}
                            </DropdownMenuItem>
                            {canWriteBasic && (
                              <DropdownMenuItem onClick={() => startEdit(emp)}>
                                <Pencil className="mr-2 h-4 w-4" />
                                {t('hr.common.edit')}
                              </DropdownMenuItem>
                            )}
                            {canDeleteEmployee && (
                              <>
                                <DropdownMenuSeparator />
                                <DropdownMenuItem
                                  className="text-destructive focus:text-destructive"
                                  onClick={() => {
                                    if (confirm(t('hr.pages.employees.deleteConfirm'))) {
                                      deleteMutation.mutate(emp.id);
                                    }
                                  }}
                                >
                                  <Trash2 className="mr-2 h-4 w-4" />
                                  {t('hr.common.delete')}
                                </DropdownMenuItem>
                              </>
                            )}
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
              {visibleEmployees.length === 0 && (
                <TableRow>
                  <TableCell colSpan={6} className="py-8 text-center text-muted-foreground">
                    {t('hr.pages.employees.empty', 'Нет сотрудников по выбранным условиям')}
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      </HRLayout>

      <ShareEmployeeDialog
        open={shareTarget !== null}
        employee={shareTarget}
        onClose={() => setShareTarget(null)}
      />

      <EmployeeFormDialog
        open={dialogOpen}
        employee={editing}
        onOpenChange={(next) => {
          setDialogOpen(next);
          if (!next) setEditing(null);
        }}
      />
    </>
  );
};

export default HREmployees;
