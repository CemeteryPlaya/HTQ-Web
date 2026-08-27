import React, { useMemo, useState, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Briefcase,
  Check,
  ChevronsUpDown,
  IdCard,
  Lock,
  MoreHorizontal,
  Pencil,
  Plus,
  Search,
  Share2,
  Sparkles,
  Trash2,
  UserPlus,
  UsersRound,
} from 'lucide-react';
import { ShareEmployeeDialog } from '@/components/hr/ShareEmployeeDialog';
import EmployeeBulkImportDialog from '@/components/hr/EmployeeBulkImportDialog';
import EmployeeMatchNotice from '@/components/hr/EmployeeMatchNotice';
import EmployeePrefillDialog from '@/components/hr/EmployeePrefillDialog';
import NewAccountCredentials from '@/components/hr/NewAccountCredentials';
import {
  createEmployee,
  createEmployeeUser,
  createPosition,
  deleteEmployee,
  fetchDepartments,
  fetchEmployees,
  fetchEmployeeUsers,
  fetchPositions,
  updateEmployee,
} from '@/api/hr';
import api from '@/api/client';
import HRLayout from '@/components/hr/HRLayout';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { PhoneInput } from '@/components/ui/phone-input';
import { Textarea } from '@/components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { cn } from '@/lib/utils';
import { useHRLevel } from '@/hooks/useHRLevel';
import type {
  Department, Employee, HRUserOption, LevelThreshold, NextWeightForLevel, Position,
} from '@/types/hr';

interface Employee {
  id: number;
  // Backend EmployeeOut: ``user_id`` is the platform-user link.
  user_id?: number | null;
  // Legacy alias retained for older endpoints — read both when present.
  user?: number | null;
  // Names live separately on the backend; older responses sometimes
  // synthesised ``full_name`` — keep it optional as a fallback.
  first_name?: string;
  last_name?: string;
  middle_name?: string | null;
  full_name?: string;
  username?: string;
  email: string;
  // EmployeeOut returns ``position_id`` + nested ``position: {id, title}``.
  position_id?: number | null;
  position?: { id: number; title: string } | number | null;
  position_title?: string;
  department_id?: number | null;
  department?: { id: number; name: string } | number | null;
  department_name?: string;
  phone?: string;
  // EmployeeOut: ``hire_date`` / ``termination_date``. Older endpoints used
  // ``date_hired``/``date_dismissed`` — accept either.
  hire_date?: string | null;
  date_hired?: string | null;
  termination_date?: string | null;
  date_dismissed?: string | null;
  status: string;
  notes?: string;
  bio?: string;
  // Sensitive (Senior-only — absent from API response for Junior)
  salary?: string | null;
  bonus?: string | null;
  passport_data?: string;
  bank_account?: string;
  // Synced from user-service via the replica worker; absent on bare-skeleton
  // employees that aren't linked to a platform user yet.
  avatar_url?: string | null;
}

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

/** Pull the int id from a relation that may arrive as either a flat int
 * or a nested ``{id, ...}`` object (depends on the endpoint version). */
const relationId = (rel: unknown): number | null => {
  if (rel == null) return null;
  if (typeof rel === 'number') return rel;
  if (typeof rel === 'object' && 'id' in (rel as any)) return Number((rel as any).id);
  return null;
};

const relationLabel = (rel: unknown, key: 'title' | 'name'): string => {
  if (rel && typeof rel === 'object' && key in (rel as any)) {
    return String((rel as any)[key] || '');
  }
  return '';
};

interface Department {
  id: number;
  name: string;
}

interface HRUser {
  id: number;
  full_name: string;
  email: string;
  /** Sent by backend HRUserOption — used to prefill EmployeeCreate.first_name / last_name. */
  first_name?: string;
  last_name?: string;
}

/** Frontend-friendly status values mapped to the backend's allowed pattern. */
const STATUS_TO_BACKEND: Record<string, 'active' | 'inactive' | 'terminated'> = {
  active: 'active',
  on_leave: 'inactive',
  inactive: 'inactive',
  dismissed: 'terminated',
  terminated: 'terminated',
};

const HREmployees = () => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  // Lifted share-dialog state — opened from the row action button. ``null``
  // means closed; a partial Employee carries id + display name only.
  const [shareTarget, setShareTarget] = useState<{ id: number; full_name: string } | null>(null);
  const {
    level,
    hasHrAccess,
    canWriteBasic,
    canCreateEmployee,
    canTransferEmployee,
    canDeleteEmployee,
    canListUserOptions,
    canManageUserOptions,
    isLoading: levelLoading,
  } = useHRLevel();
  const { data: employees, isLoading, error } = useQuery({
    queryKey: ['hr-employees'],
    queryFn: () => fetchEmployees({ limit: '200' }),
    enabled: hasHrAccess,
  });

  const { data: departments } = useQuery({
    queryKey: ['hr-departments'],
    queryFn: fetchDepartments,
    enabled: hasHrAccess,
  });

  const { data: positions } = useQuery({
    queryKey: ['hr-positions'],
    queryFn: fetchPositions,
    enabled: hasHrAccess,
  });

  const { data: users } = useQuery({
    queryKey: ['hr-employee-users'],
    queryFn: () => fetchEmployeeUsers(),
    enabled: canListUserOptions,
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

  const [searchParams, setSearchParams] = useSearchParams();

  useEffect(() => {
    if (searchParams.get('action') === 'new' && canCreateEmployee) {
      startCreate();
      const newParams = new URLSearchParams(searchParams);
      newParams.delete('action');
      setSearchParams(newParams, { replace: true });
    }
  }, [searchParams, canCreateEmployee]);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<Employee | null>(null);
  const [form, setForm] = useState({
    user: 'none',
    position: 'none',
    department: 'none',
    phone: '',
    date_hired: '',
    date_dismissed: '',
    status: 'active',
    notes: '',
    last_name: '',
    first_name: '',
    middle_name: '',
    email: '',
    avatar_url: '',
  });
  const [prefillOpen, setPrefillOpen] = useState(false);
  const [bulkImportOpen, setBulkImportOpen] = useState(false);

  const [formError, setFormError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  const saveMutation = useMutation({
    mutationFn: async () => {
      const backendStatus = STATUS_TO_BACKEND[form.status] || 'active';

      if (editing) {
        // EmployeeUpdate — все поля необязательны, шлём только заполненное.
        const patch: Record<string, unknown> = {
          status: backendStatus,
          phone: form.phone || undefined,
          bio: form.notes || undefined,
          first_name: form.first_name || undefined,
          last_name: form.last_name || undefined,
          middle_name: form.middle_name || undefined,
          email: form.email || undefined,
          avatar_url: form.avatar_url || undefined,
        };
        if (form.position !== 'none') patch.position_id = Number(form.position);
        if (form.department !== 'none') patch.department_id = Number(form.department);
        if (form.date_dismissed) patch.termination_date = form.date_dismissed;
        return updateEmployee(editing.id, patch as Partial<Employee>);
      }

      // EmployeeCreate — first_name / last_name / email / department_id /
      // position_id / hire_date обязательны на бэкенде. Значения берутся из
      // формы: их туда либо ввели руками, либо перенесли из источника
      // (учётка, коллега, почтовый ящик) — форме незачем знать, откуда.
      const selected = users?.find((u) => String(u.id) === form.user);

      const payload: Record<string, unknown> = {
        first_name: form.first_name || selected?.first_name || 'Unknown',
        last_name: form.last_name || selected?.last_name || '',
        middle_name: form.middle_name || undefined,
        email: form.email || selected?.email,
        phone: form.phone || undefined,
        avatar_url: form.avatar_url || undefined,
        department_id: Number(form.department),
        position_id: Number(form.position),
        hire_date: form.date_hired,
        status: backendStatus,
        bio: form.notes || undefined,
      };
      // Учётка необязательна: карточку заводят и на человека, которого в
      // платформе ещё нет, — привязать её можно позже.
      if (selected) payload.user_id = selected.id;
      return createEmployee(payload as Partial<Employee>);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hr-employees'] });
      queryClient.invalidateQueries({ queryKey: ['hr-employee-users'] });
      setDialogOpen(false);
      setEditing(null);
      setFormError(null);
      setFieldErrors({});
      setForm({
        user: 'none', position: 'none', department: 'none', phone: '',
        date_hired: '', date_dismissed: '', status: 'active', notes: '',
        last_name: '', first_name: '', middle_name: '', email: '', avatar_url: '',
      });
    },
    onError: (err: any) => {
      const data = err?.response?.data;
      // eslint-disable-next-line no-console
      console.warn('[hr.employees] save error', err?.response?.status, data);

      // FastAPI 422 — { detail: [{ loc: ["body","field"], msg, type }, ...] }
      if (data && Array.isArray(data.detail)) {
        const fields: Record<string, string> = {};
        const summary: string[] = [];
        for (const item of data.detail) {
          const loc = Array.isArray(item.loc) ? item.loc : [];
          const field = loc.length ? String(loc[loc.length - 1]) : 'unknown';
          fields[field] = item.msg || String(item);
          summary.push(`${field}: ${item.msg || ''}`);
        }
        setFieldErrors(fields);
        setFormError(summary.join(' • '));
        return;
      }

      setFieldErrors({});
      setFormError(
        (typeof data?.detail === 'string' ? data.detail : null) ||
          err?.message ||
          t('hr.employees.saveError'),
      );
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      await deleteEmployee(id);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hr-employees'] });
      queryClient.invalidateQueries({ queryKey: ['hr-employee-users'] });
    },
  });

  /** Front-side validation that mirrors the backend's required-field set
   * (first_name / last_name / email / department_id / position_id /
   * hire_date). We block the request before it hits the API so the user
   * gets a fast, field-pinned hint instead of a generic 422. */
  const handleSave = () => {
    const errs: Record<string, string> = {};
    if (!editing) {
      // Учётка больше НЕ обязательна: карточку заводят и на человека, которого
      // в платформе ещё нет (данные пришли из ящика или введены руками), а
      // привязать учётку можно позже. Обязательно то, что требует модель.
      if (!form.last_name.trim()) {
        errs.last_name = t('hr.pages.employees.errors.lastNameRequired', 'Укажите фамилию');
      }
      if (!form.email.trim()) {
        errs.email = t('hr.pages.employees.errors.emailRequired', 'Укажите email');
      }
      if (form.department === 'none') {
        errs.department = t('hr.pages.employees.errors.departmentRequired', 'Выберите отдел');
      }
      if (form.position === 'none') {
        errs.position = t('hr.pages.employees.errors.positionRequired', 'Выберите должность');
      }
      if (!form.date_hired) {
        errs.date_hired = t('hr.pages.employees.errors.hireDateRequired', 'Укажите дату приёма');
      }
    }
    if (Object.keys(errs).length > 0) {
      setFieldErrors(errs);
      setFormError(t('hr.pages.employees.errors.fillRequired', 'Заполните обязательные поля'));
      return;
    }
    setFieldErrors({});
    setFormError(null);
    saveMutation.mutate();
  };

  const [userPopoverOpen, setUserPopoverOpen] = useState(false);
  const [createUserOpen, setCreateUserOpen] = useState(false);
  const [newUserForm, setNewUserForm] = useState({ first_name: '', last_name: '', patronymic: '', email: '' });
  // Доступы только что заведённой учётки. Живут до закрытия диалога:
  // пароль нигде больше не хранится, и тост здесь не годится —
  // случайно смахнув его, человек теряет единственный способ войти.
  const [createdCredentials, setCreatedCredentials] = useState<
    { email: string; password: string } | null
  >(null);

  const [positionPopoverOpen, setPositionPopoverOpen] = useState(false);
  const [createPositionOpen, setCreatePositionOpen] = useState(false);
  const [newPositionForm, setNewPositionForm] = useState<{
    title: string;
    department_id: string;
    level: string;
    weight: string;
    grade: string;
    description: string;
    hr_level: '' | 'junior' | 'middle' | 'senior' | 'lead';
  }>({ title: '', department_id: '', level: '', weight: '100', grade: '1', description: '', hr_level: '' });
  const [newPositionError, setNewPositionError] = useState<string | null>(null);

  // Ключ общий со страницей «Должности» — справочник уровней тянется один раз.
  const { data: levelThresholds } = useQuery<LevelThreshold[]>({
    queryKey: ['hr-level-thresholds'],
    queryFn: async () => (await api.get<LevelThreshold[]>('hr/v1/positions/levels/')).data,
  });
  const sortedThresholds = useMemo(
    () => [...(levelThresholds ?? [])].sort((a, b) => a.level_number - b.level_number),
    [levelThresholds],
  );
  const newPositionThreshold = sortedThresholds.find(
    (item) => item.level_number === Number(newPositionForm.level),
  );
  const newPositionWeightOutOfRange = Boolean(
    newPositionThreshold
    && newPositionForm.weight !== ''
    && (Number(newPositionForm.weight) < newPositionThreshold.weight_from
      || Number(newPositionForm.weight) > newPositionThreshold.weight_to),
  );

  const createPositionMutation = useMutation({
    mutationFn: async () => {
      const payload: Record<string, unknown> = {
        title: newPositionForm.title.trim(),
        department_id: Number(newPositionForm.department_id),
        weight: Number(newPositionForm.weight) || 100,
        grade: Number(newPositionForm.grade) || 1,
        description: newPositionForm.description || undefined,
      };
      if (newPositionForm.level) payload.level = Number(newPositionForm.level);
      if (newPositionForm.hr_level) {
        payload.permissions = { hr_level: newPositionForm.hr_level, permissions: [] };
      }
      return createPosition(payload);
    },
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ['hr-positions'] });
      queryClient.invalidateQueries({ queryKey: ['hr-positions-v1'] });
      setForm((prev) => ({
        ...prev,
        position: String(created.id),
        // Если у новой должности задан отдел и в форме отдел ещё не выбран —
        // подставим его, чтобы создать сотрудника одним движением.
        department: prev.department && prev.department !== 'none'
          ? prev.department
          : (created.department_id ? String(created.department_id) : prev.department),
      }));
      setCreatePositionOpen(false);
      setNewPositionForm({
        title: '', department_id: '', level: '', weight: '100', grade: '1',
        description: '', hr_level: '',
      });
      setNewPositionError(null);
    },
    onError: (err: any) => {
      const data = err?.response?.data;
      setNewPositionError(
        (typeof data?.detail === 'string' ? data.detail : null)
        || (Array.isArray(data?.detail) ? data.detail.map((d: any) => d.msg).join(' • ') : null)
        || err?.message
        || t('hr.employees.createPositionError'),
      );
    },
  });

  /** Свободный вес выбранного уровня подбирает сервер: вес глобально уникален,
   *  и этот диалог не видит, какие значения уже заняты. */
  const suggestWeightForLevel = async (levelNumber: number) => {
    try {
      const res = await api.get<NextWeightForLevel>(
        `hr/v1/positions/levels/${levelNumber}/next-weight`,
      );
      setNewPositionForm((prev) => (
        Number(prev.level) === levelNumber ? { ...prev, weight: String(res.data.weight) } : prev
      ));
    } catch {
      setNewPositionError(t('hr.employees.weightError'));
    }
  };

  const changeNewPositionLevel = (value: string) => {
    setNewPositionForm((prev) => ({ ...prev, level: value }));
    setNewPositionError(null);
    const levelNumber = Number(value);
    if (levelNumber) void suggestWeightForLevel(levelNumber);
  };

  const startCreatePosition = () => {
    setPositionPopoverOpen(false);
    setNewPositionError(null);
    // Вес НЕ фиксируем на 100: он глобально уникален, и 100 почти всегда уже
    // занят — диалог падал с 409 «Weight 100 is already taken» у всех подряд.
    // Берём первый уровень и просим у сервера свободный вес внутри него.
    const firstLevel = sortedThresholds[0];
    setNewPositionForm({
      title: '',
      // Preselect the department picked on the employee form, if any.
      department_id: form.department && form.department !== 'none' ? form.department : '',
      level: firstLevel ? String(firstLevel.level_number) : '',
      weight: String(firstLevel?.weight_from ?? 100),
      grade: '1',
      description: '',
      hr_level: '',
    });
    setCreatePositionOpen(true);
    if (firstLevel) void suggestWeightForLevel(firstLevel.level_number);
  };

  const createUserMutation = useMutation({
    mutationFn: async (data: typeof newUserForm) => {
      return createEmployeeUser(data);
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['hr-employee-users'] });
      // Учётка выбрана в форме, а её данные сразу уезжают в поля карточки —
      // ради этого её и заводили, не выходя из формы сотрудника.
      setForm((prev) => ({
        ...prev,
        user: String(data.id),
        first_name: data.first_name || prev.first_name,
        last_name: data.last_name || prev.last_name,
        middle_name: data.patronymic || prev.middle_name,
        email: data.email || prev.email,
      }));
      setNewUserForm({ first_name: '', last_name: '', patronymic: '', email: '' });
      setUserPopoverOpen(false);
      // Диалог НЕ закрывается: сначала человек забирает пароль. Без него
      // заведённая учётка бесполезна — войти ею будет нечем.
      if (data.generated_password) {
        setCreatedCredentials({ email: data.email, password: data.generated_password });
      } else {
        setCreateUserOpen(false);
      }
    },
  });

  const startCreate = () => {
    setEditing(null);
    setFormError(null);
    setFieldErrors({});
    setForm({
      user: 'none', position: 'none', department: 'none', phone: '',
      date_hired: '', date_dismissed: '', status: 'active', notes: '',
      last_name: '', first_name: '', middle_name: '', email: '', avatar_url: '',
    });
    setDialogOpen(true);
  };

  const startEdit = (emp: Employee) => {
    setEditing(emp);
    setFormError(null);
    setFieldErrors({});

    // Backend EmployeeOut uses ``user_id`` / nested ``position``+``department``
    // objects / ``hire_date`` / ``termination_date``; older endpoints used
    // ``user`` / ``date_hired`` / ``date_dismissed``. Read both shapes so the
    // edit dialog works regardless of which response format we got.
    const userId = emp.user_id ?? (typeof emp.user === 'number' ? emp.user : null);
    const positionId = emp.position_id ?? relationId(emp.position);
    const departmentId = emp.department_id ?? relationId(emp.department);

    setForm({
      user: userId ? String(userId) : 'none',
      position: positionId ? String(positionId) : 'none',
      department: departmentId ? String(departmentId) : 'none',
      phone: emp.phone || '',
      date_hired: emp.hire_date || emp.date_hired || '',
      date_dismissed: emp.termination_date || emp.date_dismissed || '',
      status: emp.status || 'active',
      notes: emp.bio || emp.notes || '',
      last_name: emp.last_name || '',
      first_name: emp.first_name || '',
      middle_name: emp.middle_name || '',
      email: emp.email || '',
      avatar_url: emp.avatar_url || '',
    });
    setDialogOpen(true);
  };

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
        <div className="rounded-3xl border bg-card p-4 shadow-2xs mb-6">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex flex-1 flex-wrap items-center gap-3">
              <div className="relative flex-1 min-w-[220px] max-w-md">
                <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
                <Input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder={t('hr.pages.employees.searchPlaceholder', 'Поиск по ФИО, email, телефону, должности…')}
                  className="pl-9 h-9 text-xs bg-muted/30 rounded-xl"
                />
              </div>
              <Select value={statusFilter} onValueChange={setStatusFilter}>
                <SelectTrigger className="h-9 w-[160px] text-xs rounded-xl bg-muted/30">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="rounded-2xl">
                  <SelectItem value="all">{t('hr.pages.employees.filters.allStatuses', 'Все статусы')}</SelectItem>
                  <SelectItem value="active">{t('hr.pages.employees.status.active')}</SelectItem>
                  <SelectItem value="inactive">{t('hr.pages.employees.status.inactive', 'Неактивен')}</SelectItem>
                  <SelectItem value="terminated">{t('hr.pages.employees.status.terminated', 'Уволен')}</SelectItem>
                </SelectContent>
              </Select>
              <div className="text-xs font-semibold text-muted-foreground whitespace-nowrap">
                {t('hr.common.total')}: {visibleEmployees.length}
                {employees && visibleEmployees.length !== employees.length ? ` / ${employees.length}` : ''}
                {level && <span className="ml-2 font-mono uppercase text-[10px] bg-muted px-2 py-0.5 rounded-md">({level.replace('_', ' ')})</span>}
              </div>
            </div>

            {canCreateEmployee && canListUserOptions && (
              <Button
                variant="outline"
                className="h-9 gap-2 rounded-xl font-semibold shrink-0"
                onClick={() => setBulkImportOpen(true)}
              >
                <UsersRound className="h-4 w-4" />
                {t('hr.pages.employees.import.open', 'Импорт из пользователей')}
              </Button>
            )}
            <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
              {canCreateEmployee && (
                <DialogTrigger asChild>
                  <Button onClick={startCreate} className="h-9 gap-2 rounded-xl bg-primary text-primary-foreground hover:bg-primary/90 font-semibold shadow-2xs shrink-0">
                    <UserPlus className="h-4 w-4" />
                    {t('hr.pages.employees.add', 'Добавить сотрудника')}
                  </Button>
                </DialogTrigger>
              )}
            <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
              <DialogHeader>
                <DialogTitle>{editing ? t('hr.pages.employees.edit') : t('hr.pages.employees.new')}</DialogTitle>
              </DialogHeader>
              <div className="grid gap-4">
                {/* «Подтянуть данные» доступно и при создании, и при
                    редактировании: в режиме правки это единственный способ
                    привязать учётку к уже заведённой карточке (PATCH поле
                    user_id не принимает). */}
                <div className="flex justify-end">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="gap-2"
                    onClick={() => setPrefillOpen(true)}
                    disabled={editing ? !canWriteBasic : !canCreateEmployee}
                  >
                    <Sparkles className="h-4 w-4" />
                    {t('hr.pages.employees.prefill.open', 'Подтянуть данные')}
                  </Button>
                </div>
                <div className="grid gap-4 md:grid-cols-2">
                  {editing ? (
                    <label className="grid gap-2 text-sm">
                      {t('hr.pages.employees.fields.user')}
                      <Input
                        value={editing.user_id
                          ? `${users?.find((u) => u.id === editing.user_id)?.full_name || `#${editing.user_id}`}`
                          : t('hr.pages.employees.prefill.noAccount', 'Учётная запись не привязана')}
                        readOnly
                      />
                    </label>
                  ) : (
                    <label className="grid gap-2 text-sm">
                      {t('hr.pages.employees.fields.user')}
                      {/* modal — не косметика: без него список сотрудников не
                          прокручивается колесом. Диалог на время открытия
                          блокирует прокрутку документа (react-remove-scroll) и
                          пропускает события только внутри своего поддерева, а
                          содержимое поповера рендерится порталом в body, то
                          есть снаружи. Список при этом технически
                          прокручиваемый — отсюда ощущение сломанного колеса.
                          С modal поповер ставит собственную блокировку и
                          разрешает прокрутку у себя. */}
                      <Popover modal open={userPopoverOpen} onOpenChange={setUserPopoverOpen}>
                        <PopoverTrigger asChild>
                          <Button
                            variant="outline"
                            role="combobox"
                            aria-expanded={userPopoverOpen}
                            className="w-full justify-between font-normal"
                          >
                            {form.user && form.user !== 'none'
                              ? users?.find((u) => String(u.id) === form.user)?.full_name || t('hr.pages.employees.placeholders.selectUser')
                              : t('hr.pages.employees.placeholders.selectUser')}
                            <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
                          </Button>
                        </PopoverTrigger>
                        <PopoverContent className="w-[400px] p-0" align="start">
                          <Command>
                            <CommandInput placeholder={t('hr.pages.employees.searchUser')} />
                            <CommandEmpty>{t('hr.pages.employees.noUserFound')}</CommandEmpty>
                            <CommandList>
                              <CommandGroup>
                                <CommandItem
                                  value="none"
                                  onSelect={() => {
                                    setForm({ ...form, user: 'none' });
                                    setUserPopoverOpen(false);
                                  }}
                                >
                                  <Check className={cn("mr-2 h-4 w-4", form.user === 'none' ? "opacity-100" : "opacity-0")} />
                                  {t('hr.pages.employees.placeholders.selectUser')}
                                </CommandItem>
                                {users?.map((u) => (
                                  <CommandItem
                                    key={u.id}
                                    value={`${u.full_name} ${u.email}`}
                                    onSelect={() => {
                                      // Выбор учётки — это и есть «подтянуть»:
                                      // раньше отсюда уезжали только имя,
                                      // фамилия и почта, хотя телефон, отчество
                                      // и аватар в учётке уже были. Пустое поле
                                      // учётки не затирает введённое руками.
                                      setForm({
                                        ...form,
                                        user: String(u.id),
                                        first_name: u.first_name || form.first_name,
                                        last_name: u.last_name || form.last_name,
                                        middle_name: u.patronymic || form.middle_name,
                                        email: u.email || form.email,
                                        phone: u.phone || form.phone,
                                        avatar_url: u.avatar_url || form.avatar_url,
                                        notes: u.bio || form.notes,
                                      });
                                      setUserPopoverOpen(false);
                                    }}
                                  >
                                    <Check className={cn("mr-2 h-4 w-4", form.user === String(u.id) ? "opacity-100" : "opacity-0")} />
                                    {u.full_name} ({u.email})
                                  </CommandItem>
                                ))}
                              </CommandGroup>
                              {canManageUserOptions && (
                                <CommandGroup>
                                  <CommandItem
                                    onSelect={() => {
                                      setUserPopoverOpen(false);
                                      setCreateUserOpen(true);
                                    }}
                                    className="text-primary font-medium flex items-center gap-2 cursor-pointer"
                                  >
                                    <UserPlus className="h-4 w-4" />
                                    {t('hr.pages.employees.createUser')}
                                  </CommandItem>
                                </CommandGroup>
                              )}
                            </CommandList>
                          </Command>
                        </PopoverContent>
                      </Popover>
                    </label>
                  )}
                  <label className="grid gap-2 text-sm">
                    {t('hr.pages.employees.fields.status')}
                    <Select value={form.status} onValueChange={(value) => setForm({ ...form, status: value })} disabled={!canWriteBasic}>
                      <SelectTrigger>
                        <SelectValue placeholder={t('hr.pages.employees.placeholders.selectStatus')} />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="active">{t('hr.pages.employees.status.active')}</SelectItem>
                        <SelectItem value="inactive">{t('hr.pages.employees.status.inactive', 'Неактивен')}</SelectItem>
                        <SelectItem value="terminated">{t('hr.pages.employees.status.terminated', 'Уволен')}</SelectItem>
                      </SelectContent>
                    </Select>
                  </label>
                </div>

                {/* ФИО и почта — собственные поля карточки. Раньше их
                    брали из выбранной учётки в момент отправки, и завести
                    сотрудника без учётки было нельзя в принципе. */}
                <div className="grid gap-4 md:grid-cols-3">
                  <label className="grid gap-2 text-sm">
                    {t('hr.pages.employees.fields.lastName')}
                    <Input
                      value={form.last_name}
                      readOnly={!canWriteBasic}
                      onChange={(e) => setForm({ ...form, last_name: e.target.value })}
                    />
                    {fieldErrors.last_name && (
                      <span className="text-xs text-destructive">{fieldErrors.last_name}</span>
                    )}
                  </label>
                  <label className="grid gap-2 text-sm">
                    {t('hr.pages.employees.fields.firstName')}
                    <Input
                      value={form.first_name}
                      readOnly={!canWriteBasic}
                      onChange={(e) => setForm({ ...form, first_name: e.target.value })}
                    />
                  </label>
                  <label className="grid gap-2 text-sm">
                    {t('hr.pages.employees.fields.patronymic')}
                    <Input
                      value={form.middle_name}
                      readOnly={!canWriteBasic}
                      onChange={(e) => setForm({ ...form, middle_name: e.target.value })}
                    />
                  </label>
                </div>

                <label className="grid gap-2 text-sm">
                  {t('hr.pages.employees.fields.email')}
                  <Input
                    type="email"
                    value={form.email}
                    readOnly={!canWriteBasic}
                    onChange={(e) => setForm({ ...form, email: e.target.value })}
                  />
                  {fieldErrors.email && (
                    <span className="text-xs text-destructive">{fieldErrors.email}</span>
                  )}
                </label>

                {/* Подсказка о совпадении. Появляется, только когда набрано
                    что-то опознающее (почта, телефон или ФИО целиком) — см.
                    matchQueryIsAnswerable. */}
                {canCreateEmployee && (
                  <EmployeeMatchNotice
                    email={form.email}
                    phone={form.phone}
                    firstName={form.first_name}
                    lastName={form.last_name}
                    patronymic={form.middle_name}
                    excludeEmployeeId={editing?.id ?? null}
                    onOpenEmployee={(employee) => navigate(`/hr/employees/${employee.id}`)}
                    onUseUser={() => setPrefillOpen(true)}
                  />
                )}

                <div className="grid gap-4 md:grid-cols-2">
                  <label className="grid gap-2 text-sm">
                    {t('hr.pages.employees.fields.position')}
                    {/* modal — по той же причине, что у списка пользователей
                        выше: этот поповер тоже живёт внутри диалога, и без
                        него список должностей не прокручивается колесом. */}
                    <Popover modal open={positionPopoverOpen} onOpenChange={setPositionPopoverOpen}>
                      <PopoverTrigger asChild>
                        <Button
                          variant="outline"
                          role="combobox"
                          aria-expanded={positionPopoverOpen}
                          className="w-full justify-between font-normal"
                          disabled={editing ? !canTransferEmployee : !canCreateEmployee}
                        >
                          <span className="flex items-center gap-2 truncate">
                            {form.position && form.position !== 'none' ? (
                              <>
                                <span className="truncate">
                                  {positions?.find((p) => String(p.id) === form.position)?.title
                                    || t('hr.pages.employees.placeholders.selectPosition')}
                                </span>
                                {positions?.find((p) => String(p.id) === form.position)?.is_system && (
                                  <Lock className="h-3 w-3 shrink-0 text-muted-foreground" />
                                )}
                              </>
                            ) : (
                              t('hr.pages.employees.placeholders.selectPosition')
                            )}
                          </span>
                          <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
                        </Button>
                      </PopoverTrigger>
                      <PopoverContent className="w-[--radix-popover-trigger-width] min-w-[320px] p-0" align="start">
                        <Command>
                          <CommandInput placeholder={t('hr.pages.employees.searchPosition', 'Поиск должности…')} />
                          <CommandEmpty>{t('hr.pages.employees.noPositionFound', 'Должность не найдена')}</CommandEmpty>
                          <CommandList>
                            <CommandGroup>
                              <CommandItem
                                value="none"
                                onSelect={() => {
                                  setForm({ ...form, position: 'none' });
                                  setPositionPopoverOpen(false);
                                }}
                              >
                                <Check className={cn('mr-2 h-4 w-4', form.position === 'none' ? 'opacity-100' : 'opacity-0')} />
                                {t('hr.common.noPosition')}
                              </CommandItem>
                              {positions?.map((pos) => (
                                <CommandItem
                                  key={pos.id}
                                  value={`${pos.title} ${pos.department_name ?? ''}`}
                                  onSelect={() => {
                                    setForm({ ...form, position: String(pos.id) });
                                    setPositionPopoverOpen(false);
                                  }}
                                >
                                  <Check className={cn('mr-2 h-4 w-4', form.position === String(pos.id) ? 'opacity-100' : 'opacity-0')} />
                                  <span className="flex-1 truncate">{pos.title}</span>
                                  {pos.is_system && (
                                    <span
                                      className="ml-2 inline-flex items-center gap-1 rounded border bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground"
                                      title={t('hr.positions.systemTitle')}
                                    >
                                      <Lock className="h-3 w-3" /> {t('hr.employees.systemShort')}
                                    </span>
                                  )}
                                </CommandItem>
                              ))}
                            </CommandGroup>
                            {(editing ? canTransferEmployee : canCreateEmployee) && (
                              <CommandGroup>
                                <CommandItem
                                  onSelect={startCreatePosition}
                                  className="text-primary font-medium flex items-center gap-2 cursor-pointer"
                                >
                                  <Plus className="h-4 w-4" />
                                  {t('hr.pages.employees.createPosition', 'Создать новую должность')}
                                </CommandItem>
                              </CommandGroup>
                            )}
                          </CommandList>
                        </Command>
                      </PopoverContent>
                    </Popover>
                  </label>
                  <label className="grid gap-2 text-sm">
                    {t('hr.pages.employees.fields.department')}
                    <Select value={form.department} onValueChange={(value) => setForm({ ...form, department: value })} disabled={editing ? !canTransferEmployee : !canCreateEmployee}>
                      <SelectTrigger>
                        <SelectValue placeholder={t('hr.pages.employees.placeholders.selectDepartment')} />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="none">{t('hr.common.noDepartment')}</SelectItem>
                        {departments?.map((dept) => (
                          <SelectItem key={dept.id} value={String(dept.id)}>
                            {dept.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </label>
                </div>

                <div className="grid gap-4 md:grid-cols-2">
                  <label className="grid gap-2 text-sm">
                    {t('hr.pages.employees.fields.phone')}
                    <PhoneInput value={form.phone} onChange={(v) => setForm({ ...form, phone: v })} />
                  </label>
                  <label className="grid gap-2 text-sm">
                    {t('hr.pages.employees.fields.dateHired')}
                    <Input type="date" value={form.date_hired} onChange={(e) => setForm({ ...form, date_hired: e.target.value })} />
                  </label>
                </div>

                <div className="grid gap-4 md:grid-cols-2">
                  <label className="grid gap-2 text-sm">
                    {t('hr.pages.employees.fields.dateDismissed')}
                    <Input type="date" value={form.date_dismissed} readOnly={!canTransferEmployee} onChange={(e) => setForm({ ...form, date_dismissed: e.target.value })} />
                  </label>
                </div>

                <label className="grid gap-2 text-sm">
                  {t('hr.pages.employees.fields.notes')}
                  <Textarea value={form.notes} readOnly={!canWriteBasic} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
                </label>

                {formError && (
                  <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                    {formError}
                  </div>
                )}
                <div className="flex justify-end gap-2">
                  <Button variant="outline" onClick={() => setDialogOpen(false)}>{t('hr.common.cancel')}</Button>
                  <Button onClick={handleSave} disabled={saveMutation.isPending}>
                    {saveMutation.isPending ? t('hr.common.saving') : t('hr.common.save')}
                  </Button>
                </div>
              </div>
            </DialogContent>
          </Dialog>

          {/* Диалог префилла обслуживает оба режима: при создании отдаёт
              значения в форму, при правке сам сохраняет отмеченное. */}
          <EmployeePrefillDialog
            open={prefillOpen}
            onOpenChange={setPrefillOpen}
            employeeId={editing?.id ?? null}
            canUseAccountSources={canListUserOptions}
            onApplyToForm={(values) => {
              setForm((prev) => ({
                ...prev,
                last_name: (values.last_name as string) ?? prev.last_name,
                first_name: (values.first_name as string) ?? prev.first_name,
                middle_name: (values.middle_name as string) ?? prev.middle_name,
                email: (values.email as string) ?? prev.email,
                phone: (values.phone as string) ?? prev.phone,
                avatar_url: (values.avatar_url as string) ?? prev.avatar_url,
                notes: (values.bio as string) ?? prev.notes,
                department: values.department_id ? String(values.department_id) : prev.department,
                position: values.position_id ? String(values.position_id) : prev.position,
                user: values.user_id ? String(values.user_id) : prev.user,
              }));
            }}
            onApplied={(employee) => {
              queryClient.invalidateQueries({ queryKey: ['hr-employees'] });
              // Карточка уже сохранена сервером — перечитываем её в форму,
              // чтобы «Сохранить» не отправил следом устаревшие значения.
              startEdit(employee);
            }}
          />

          <EmployeeBulkImportDialog
            open={bulkImportOpen}
            onOpenChange={setBulkImportOpen}
            departments={departments ?? []}
            positions={positions ?? []}
          />
        </div>
        </div>

        <div className="bg-card rounded-3xl border shadow-2xs overflow-hidden">
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
                        {/* modal={false} — меню открывает диалоги. Модальное меню и диалог
                            оба ставят на body `pointer-events: none` и снимают каждый в
                            своём обработчике; меню закрывается раньше, порядок снятия
                            ломается, и блокировка остаётся навсегда — страница перестаёт
                            принимать клики до перезагрузки. */}
                        <DropdownMenu modal={false}>
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

      {/* Create Position Dialog */}
      <Dialog open={createPositionOpen} onOpenChange={setCreatePositionOpen}>
        <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Briefcase className="h-4 w-4" />
              {t('hr.pages.employees.createPositionTitle', 'Новая должность')}
            </DialogTitle>
          </DialogHeader>
          <div className="grid gap-3">
            <label className="grid gap-1.5 text-sm">
              {t('hr.pages.positions.fields.title')}
              <Input
                value={newPositionForm.title}
                onChange={(e) => setNewPositionForm({ ...newPositionForm, title: e.target.value })}
                placeholder={t('hr.pages.employees.positionTitlePlaceholder', 'Например, Старший аналитик')}
                autoFocus
              />
            </label>
            <label className="grid gap-1.5 text-sm">
              {t('hr.pages.positions.fields.department')}
              <Select
                value={newPositionForm.department_id || 'none'}
                onValueChange={(v) => setNewPositionForm({ ...newPositionForm, department_id: v === 'none' ? '' : v })}
              >
                <SelectTrigger>
                  <SelectValue placeholder={t('hr.pages.positions.placeholders.selectDepartment')} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">—</SelectItem>
                  {departments?.map((d) => (
                    <SelectItem key={d.id} value={String(d.id)}>{d.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </label>
            <label className="grid gap-1.5 text-sm">
              {t('hr.pages.positions.fields.level')}
              <Select value={newPositionForm.level} onValueChange={changeNewPositionLevel}>
                <SelectTrigger>
                  <SelectValue placeholder={t('hr.positions.pickLevel')} />
                </SelectTrigger>
                <SelectContent>
                  {sortedThresholds.map((threshold) => (
                    <SelectItem key={threshold.id} value={String(threshold.level_number)}>
                      <span className="flex items-center gap-2">
                        <span
                          className="h-2.5 w-2.5 rounded-full"
                          style={{ backgroundColor: threshold.color ?? '#64748b' }}
                        />
                        L{threshold.level_number}{threshold.label ? `: ${threshold.label}` : ''}
                        <span className="font-mono text-xs text-muted-foreground">
                          {threshold.weight_from}-{threshold.weight_to}
                        </span>
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {sortedThresholds.length === 0 && (
                <span className="text-xs text-muted-foreground">
                  {t('hr.employees.noLevelsHint')}
                </span>
              )}
            </label>
            <div className="grid grid-cols-2 gap-3">
              <label className="grid gap-1.5 text-sm">
                {t('hr.pages.employees.weight', 'Вес')}
                <Input
                  type="number"
                  min={0}
                  value={newPositionForm.weight}
                  onChange={(e) => setNewPositionForm({ ...newPositionForm, weight: e.target.value })}
                />
                {newPositionWeightOutOfRange && newPositionThreshold ? (
                  <span className="text-xs text-destructive">
                    {t('hr.positions.weightOutOfRange', {
                      level: newPositionThreshold.level_number,
                      from: newPositionThreshold.weight_from,
                      to: newPositionThreshold.weight_to,
                    })}
                  </span>
                ) : newPositionThreshold ? (
                  <span className="text-xs text-muted-foreground">
                    {t('hr.employees.orderWithinLevel', {
                      from: newPositionThreshold.weight_from,
                      to: newPositionThreshold.weight_to,
                    })}
                  </span>
                ) : null}
              </label>
              <label className="grid gap-1.5 text-sm">
                {t('hr.pages.employees.grade', 'Грейд')}
                <Input
                  type="number"
                  min={1}
                  max={10}
                  value={newPositionForm.grade}
                  onChange={(e) => setNewPositionForm({ ...newPositionForm, grade: e.target.value })}
                />
              </label>
            </div>
            <label className="grid gap-1.5 text-sm">
              {t('hr.pages.employees.hrLevel', 'Уровень HR-доступа')}
              <Select
                value={newPositionForm.hr_level || 'none'}
                onValueChange={(v) =>
                  setNewPositionForm({
                    ...newPositionForm,
                    hr_level: v === 'none' ? '' : (v as typeof newPositionForm.hr_level),
                  })
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">{t('hr.positions.noHrAccess')}</SelectItem>
                  <SelectItem value="junior">{t('hr.employees.accessJunior')}</SelectItem>
                  <SelectItem value="middle">{t('hr.employees.accessMiddle')}</SelectItem>
                  <SelectItem value="senior">{t('hr.employees.accessSenior')}</SelectItem>
                  <SelectItem value="lead">{t('hr.employees.accessLead')}</SelectItem>
                </SelectContent>
              </Select>
            </label>
            <label className="grid gap-1.5 text-sm">
              {t('hr.pages.employees.description', 'Описание')}
              <Textarea
                value={newPositionForm.description}
                onChange={(e) => setNewPositionForm({ ...newPositionForm, description: e.target.value })}
                rows={2}
              />
            </label>
            <p className="text-xs text-muted-foreground">
              {t('hr.employees.finerPermissions')} <strong>{t('hr.employees.hrPositionsPath')}</strong>.
            </p>
            {newPositionError && (
              <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                {newPositionError}
              </div>
            )}
            <div className="flex justify-end gap-2 mt-2">
              <Button variant="outline" onClick={() => setCreatePositionOpen(false)}>
                {t('hr.common.cancel')}
              </Button>
              <Button
                onClick={() => createPositionMutation.mutate()}
                disabled={
                  !newPositionForm.title.trim()
                  || !newPositionForm.department_id
                  || newPositionWeightOutOfRange
                  || createPositionMutation.isPending
                }
              >
                {createPositionMutation.isPending ? t('hr.common.saving') : t('hr.common.save')}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* Create User Dialog */}
      <Dialog
        open={createUserOpen}
        onOpenChange={(open) => {
          setCreateUserOpen(open);
          if (!open) setCreatedCredentials(null);
        }}
      >
        <DialogContent className="max-w-md max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t('hr.pages.employees.createUserTitle')}</DialogTitle>
          </DialogHeader>
          {createdCredentials ? (
            <NewAccountCredentials
              credentials={createdCredentials}
              onDone={() => {
                setCreatedCredentials(null);
                setCreateUserOpen(false);
              }}
            />
          ) : (
          <div className="grid gap-4">
            <label className="grid gap-2 text-sm">
              {t('hr.pages.employees.fields.lastName')}
              <Input
                value={newUserForm.last_name}
                onChange={(e) => setNewUserForm({ ...newUserForm, last_name: e.target.value })}
              />
            </label>
            <label className="grid gap-2 text-sm">
              {t('hr.pages.employees.fields.firstName')}
              <Input
                value={newUserForm.first_name}
                onChange={(e) => setNewUserForm({ ...newUserForm, first_name: e.target.value })}
              />
            </label>
            <label className="grid gap-2 text-sm">
              {t('hr.pages.employees.fields.patronymic')}
              <Input
                value={newUserForm.patronymic}
                onChange={(e) => setNewUserForm({ ...newUserForm, patronymic: e.target.value })}
              />
            </label>
            <label className="grid gap-2 text-sm">
              {t('hr.pages.employees.fields.email')}
              <Input
                type="email"
                value={newUserForm.email}
                onChange={(e) => setNewUserForm({ ...newUserForm, email: e.target.value })}
              />
            </label>
            <div className="flex justify-end gap-2 mt-4">
              <Button variant="outline" onClick={() => setCreateUserOpen(false)}>
                {t('hr.common.cancel')}
              </Button>
              <Button
                onClick={() => createUserMutation.mutate(newUserForm)}
                disabled={!newUserForm.last_name || !newUserForm.first_name || !newUserForm.email || createUserMutation.isPending}
              >
                {createUserMutation.isPending ? t('hr.common.saving') : t('hr.common.save')}
              </Button>
            </div>
            {createUserMutation.isError && (
              <p className="text-red-500 text-sm mt-2">
                {(createUserMutation.error as any)?.response?.data?.detail || t('hr.common.unknownError')}
              </p>
            )}
          </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
};

export default HREmployees;
