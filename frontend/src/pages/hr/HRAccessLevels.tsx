import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Shield,
  ShieldCheck,
  ShieldAlert,
  Crown,
  Users,
  Building2,
  ChevronDown,
  ChevronRight,
  Info,
  Search,
  CheckCircle2,
  XCircle,
  Lock,
} from 'lucide-react';
import api from '@/api/client';
import HRLayout from '@/components/hr/HRLayout';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';

/* ─── Types ────────────────────────────────────────────────────────────── */

type DeptLevel = 'junior' | 'middle' | 'senior' | 'lead' | null;

interface Employee {
  id: number;
  first_name: string;
  last_name: string;
  middle_name?: string | null;
  email: string;
  status: string;
  department_id: number;
  position_id: number;
  department: { id: number; name: string; path: string } | null;
  position: { id: number; title: string } | null;
}

interface HRLevelResponse {
  level: DeptLevel;
  scope_department_id: number | null;
  can_read_all: boolean;
  can_write_basic: boolean;
  can_create_employee: boolean;
  can_transfer_employee: boolean;
  can_delete_employee: boolean;
  can_list_user_options: boolean;
  can_manage_user_options: boolean;
}

/* ─── Level config ─────────────────────────────────────────────────────── */

const LEVEL_CONFIG: Record<
  NonNullable<DeptLevel>,
  {
    label: string;
    labelRu: string;
    icon: React.ElementType;
    color: string;
    bg: string;
    border: string;
    ring: string;
    rank: number;
    description: string;
    permissions: string[];
  }
> = {
  lead: {
    label: 'Lead',
    labelRu: 'Руководитель',
    icon: Crown,
    color: 'text-amber-600 dark:text-amber-400',
    bg: 'bg-amber-50 dark:bg-amber-950/30',
    border: 'border-amber-200 dark:border-amber-800',
    ring: 'ring-amber-400',
    rank: 3,
    description: 'Полный доступ к отделу, деструктивные операции, управление аккаунтами',
    permissions: [
      'Чтение всех отделов',
      'Базовые изменения',
      'Создание сотрудников',
      'Перевод сотрудников',
      'Удаление сотрудников',
      'Управление аккаунтами',
      'Просмотр аккаунтов',
    ],
  },
  senior: {
    label: 'Senior',
    labelRu: 'Старший специалист',
    icon: ShieldCheck,
    color: 'text-blue-600 dark:text-blue-400',
    bg: 'bg-blue-50 dark:bg-blue-950/30',
    border: 'border-blue-200 dark:border-blue-800',
    ring: 'ring-blue-400',
    rank: 2,
    description: 'Запись по всем отделам, без деструктивных операций',
    permissions: [
      'Чтение всех отделов',
      'Базовые изменения',
      'Создание сотрудников',
      'Перевод сотрудников',
      'Просмотр аккаунтов',
    ],
  },
  middle: {
    label: 'Middle',
    labelRu: 'Специалист',
    icon: Shield,
    color: 'text-green-600 dark:text-green-400',
    bg: 'bg-green-50 dark:bg-green-950/30',
    border: 'border-green-200 dark:border-green-800',
    ring: 'ring-green-400',
    rank: 1,
    description: 'Базовые изменения только внутри своего отдела',
    permissions: ['Чтение своего отдела', 'Базовые изменения'],
  },
  junior: {
    label: 'Junior',
    labelRu: 'Сотрудник',
    icon: ShieldAlert,
    color: 'text-slate-500 dark:text-slate-400',
    bg: 'bg-slate-50 dark:bg-slate-900/30',
    border: 'border-slate-200 dark:border-slate-700',
    ring: 'ring-slate-400',
    rank: 0,
    description: 'Чтение только своего отдела, без изменений',
    permissions: ['Чтение своего отдела'],
  },
};

const ALL_PERMISSIONS = [
  'Чтение всех отделов',
  'Базовые изменения',
  'Создание сотрудников',
  'Перевод сотрудников',
  'Удаление сотрудников',
  'Просмотр аккаунтов',
  'Управление аккаунтами',
];

/* ─── Level inference ───────────────────────────────────────────────────── */

/**
 * Source explains WHY an employee has this level.
 * Mirrors the backend logic in hr_access.py + biz rules for directors/admins.
 */
type LevelSource =
  | 'director'    // CEO / General director / Executive director
  | 'hr_lead'     // HR director / CPO / Chief people officer
  | 'hr_senior'   // Senior HR specialist, HR head
  | 'hr_middle'   // HR manager / specialist / middle
  | 'hr_junior'   // Junior HR / HR assistant / trainee
  | 'no_access';  // Not in HR and not a director

interface InferResult {
  level: DeptLevel;
  source: LevelSource;
  reason: string;
}

function inferLevelFull(employee: Employee): InferResult {
  const pos = (employee.position?.title ?? '').toLowerCase();
  const dep = (employee.department?.name ?? '').toLowerCase();
  const haystack = `${pos} ${dep}`;

  // ── 1. Global directors/executives → always Lead (mirrors is_admin / is_superuser)
  const isDirector = [
    'генеральный директор', 'исполнительный директор', 'директор',
    'general director', 'executive director', 'ceo', 'coo', 'cto', 'cfo',
    'president', 'вице-президент', 'vice president',
    'управляющий', 'руководитель компании',
  ].some((m) => pos.includes(m));

  if (isDirector) {
    return {
      level: 'lead',
      source: 'director',
      reason: 'Директор/топ-менеджер — полный доступ как у администратора',
    };
  }

  // ── 2. HR employees — same logic as backend classify_hr_level
  const isHr = ['hr', 'human resources', 'people', 'персонал', 'кадр', 'эйчар'].some((m) =>
    haystack.includes(m),
  );

  if (!isHr) {
    return { level: null, source: 'no_access', reason: 'Не HR-отдел и не директор' };
  }

  if (['co hr', 'cohr', 'chief hr', 'chief human resources', 'chief people', 'cpo',
    'hr director', 'director hr', 'руководитель hr', 'директор по персоналу',
  ].some((m) => haystack.includes(m))) {
    return { level: 'lead', source: 'hr_lead', reason: 'Руководитель HR / CPO / HR-директор' };
  }

  if (['senior', 'lead', 'head', 'старш', 'ведущ'].some((m) => haystack.includes(m))) {
    return { level: 'senior', source: 'hr_senior', reason: 'Старший HR-специалист / ведущий / руководитель группы' };
  }

  if (['middle', 'middel', 'mid ', 'manager', 'менеджер', 'специалист'].some((m) =>
    haystack.includes(m))
  ) {
    return { level: 'middle', source: 'hr_middle', reason: 'HR-менеджер / специалист по персоналу' };
  }

  if (['junior', 'assistant', 'trainee', 'младш', 'ассист', 'стаж'].some((m) =>
    haystack.includes(m))
  ) {
    return { level: 'junior', source: 'hr_junior', reason: 'Начинающий HR-специалист / ассистент / стажёр' };
  }

  // Default for unclassified HR employee
  return { level: 'junior', source: 'hr_junior', reason: 'HR-сотрудник (уровень по умолчанию)' };
}

const SOURCE_LABELS: Record<LevelSource, { label: string; color: string }> = {
  director: { label: 'Директор', color: 'text-purple-600 dark:text-purple-400' },
  hr_lead: { label: 'HR Lead', color: 'text-amber-600 dark:text-amber-400' },
  hr_senior: { label: 'HR Senior', color: 'text-blue-600 dark:text-blue-400' },
  hr_middle: { label: 'HR Middle', color: 'text-green-600 dark:text-green-400' },
  hr_junior: { label: 'HR Junior', color: 'text-slate-500 dark:text-slate-400' },
  no_access: { label: 'Нет доступа', color: 'text-muted-foreground' },
};

/* ─── Sub-components ───────────────────────────────────────────────────── */

function LevelBadge({ level }: { level: DeptLevel }) {
  if (!level) return <Badge variant="outline" className="text-muted-foreground">Нет доступа</Badge>;
  const cfg = LEVEL_CONFIG[level];
  const Icon = cfg.icon;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold ${cfg.color} ${cfg.bg} ${cfg.border}`}
    >
      <Icon className="h-3 w-3" />
      {cfg.label}
    </span>
  );
}

function PermissionMatrix({ level }: { level: DeptLevel }) {
  const granted = level ? LEVEL_CONFIG[level].permissions : [];
  return (
    <div className="mt-3 grid grid-cols-1 gap-1">
      {ALL_PERMISSIONS.map((perm) => {
        const has = granted.includes(perm);
        return (
          <div key={perm} className={`flex items-center gap-2 text-xs rounded px-2 py-1 ${has ? 'text-foreground' : 'text-muted-foreground/50'}`}>
            {has
              ? <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-green-500" />
              : <XCircle className="h-3.5 w-3.5 shrink-0 text-muted-foreground/30" />
            }
            {perm}
          </div>
        );
      })}
    </div>
  );
}

function LevelCard({ level, count }: { level: NonNullable<DeptLevel>; count: number }) {
  const [open, setOpen] = useState(false);
  const cfg = LEVEL_CONFIG[level];
  const Icon = cfg.icon;

  return (
    <div className={`rounded-xl border ${cfg.border} ${cfg.bg} p-4 transition-shadow hover:shadow-md`}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className={`flex h-10 w-10 items-center justify-center rounded-full ${cfg.bg} ${cfg.border} border-2`}>
            <Icon className={`h-5 w-5 ${cfg.color}`} />
          </div>
          <div>
            <div className={`font-semibold ${cfg.color}`}>{cfg.label}</div>
            <div className="text-xs text-muted-foreground">{cfg.labelRu}</div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className={`text-2xl font-bold ${cfg.color}`}>{count}</span>
          <button
            onClick={() => setOpen(!open)}
            className="rounded-md p-1 hover:bg-black/5 dark:hover:bg-white/10"
          >
            {open ? <ChevronDown className="h-4 w-4 text-muted-foreground" /> : <ChevronRight className="h-4 w-4 text-muted-foreground" />}
          </button>
        </div>
      </div>

      <p className="mt-2 text-xs text-muted-foreground">{cfg.description}</p>

      {open && <PermissionMatrix level={level} />}
    </div>
  );
}

function EmployeeRow({ employee }: { employee: Employee }) {
  const { level, source, reason } = inferLevelFull(employee);
  const cfg = level ? LEVEL_CONFIG[level] : null;
  const srcMeta = SOURCE_LABELS[source];

  return (
    <div className="flex items-center gap-3 rounded-lg border bg-card/60 px-4 py-3 transition-colors hover:bg-card">
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-muted text-sm font-semibold text-muted-foreground">
        {employee.first_name[0]}{employee.last_name[0]}
      </div>
      <div className="min-w-0 flex-1">
        <div className="truncate font-medium text-sm">
          {employee.last_name} {employee.first_name}
          {employee.middle_name ? ` ${employee.middle_name}` : ''}
        </div>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          {employee.position && <span className="truncate">{employee.position.title}</span>}
          {employee.department && (
            <>
              <span>·</span>
              <span className="truncate">{employee.department.name}</span>
            </>
          )}
        </div>
      </div>

      {/* Source tag */}
      <span className={`hidden sm:inline-block shrink-0 text-xs font-medium ${srcMeta.color}`}>
        {srcMeta.label}
      </span>

      <div className="flex items-center gap-2 shrink-0">
        {level ? (
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <div>
                  <LevelBadge level={level} />
                </div>
              </TooltipTrigger>
              <TooltipContent side="left" className="max-w-[220px] p-3">
                <div className="font-semibold mb-1">{cfg?.labelRu}</div>
                <div className="text-xs text-muted-foreground mb-1">{cfg?.description}</div>
                <div className="text-xs italic text-muted-foreground/70 mb-2 border-l-2 pl-2">{reason}</div>
                <PermissionMatrix level={level} />
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        ) : (
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="flex items-center gap-1 text-xs text-muted-foreground cursor-help">
                  <Lock className="h-3 w-3" />
                  Нет доступа
                </span>
              </TooltipTrigger>
              <TooltipContent side="left">
                <p className="text-xs">{reason}</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        )}
      </div>
    </div>
  );
}



/* ─── Main page ────────────────────────────────────────────────────────── */

const LEVELS_ORDER: NonNullable<DeptLevel>[] = ['lead', 'senior', 'middle', 'junior'];

export default function HRAccessLevels() {
  const [search, setSearch] = useState('');
  const [filterLevel, setFilterLevel] = useState<DeptLevel | 'all'>('all');

  const { data: myLevel } = useQuery<HRLevelResponse>({
    queryKey: ['hr-level'],
    queryFn: async () => (await api.get<HRLevelResponse>('hr/v1/employees/hr-level/')).data,
    staleTime: 5 * 60 * 1000,
    retry: false,
  });

  const { data: employees = [], isLoading } = useQuery<Employee[]>({
    queryKey: ['hr-employees-all-levels'],
    queryFn: async () => {
      const res = await api.get<{ items: Employee[]; total: number }>(
        'hr/v1/employees/?limit=200',
      );
      return res.data.items ?? res.data;
    },
  });

  const enriched = useMemo(
    () =>
      employees.map((e) => ({
        ...e,
        _infer: inferLevelFull(e),
        _level: inferLevelFull(e).level,
      })),
    [employees],
  );

  const counts = useMemo(() => {
    const c: Record<string, number> = { lead: 0, senior: 0, middle: 0, junior: 0, none: 0 };
    enriched.forEach((e) => {
      if (e._level) c[e._level]++;
      else c.none++;
    });
    return c;
  }, [enriched]);

  const filtered = useMemo(() => {
    return enriched.filter((e) => {
      if (filterLevel !== 'all' && e._level !== filterLevel) return false;
      if (search) {
        const q = search.toLowerCase();
        const name = `${e.first_name} ${e.last_name} ${e.middle_name ?? ''}`.toLowerCase();
        const pos = (e.position?.title ?? '').toLowerCase();
        const dep = (e.department?.name ?? '').toLowerCase();
        if (!name.includes(q) && !pos.includes(q) && !dep.includes(q)) return false;
      }
      return true;
    });
  }, [enriched, filterLevel, search]);

  return (
    <HRLayout
      title="Управление уровнями доступа"
      subtitle="Ролевая модель HR-отдела — кто что может делать"
    >
      <div className="space-y-6">

        {/* Info banner */}
        <div className="rounded-xl border border-blue-200 bg-blue-50 p-4 dark:border-blue-800 dark:bg-blue-950/20">
          <div className="flex gap-3">
            <Info className="h-5 w-5 shrink-0 text-blue-500 mt-0.5" />
            <div className="text-sm text-blue-800 dark:text-blue-300 space-y-1">
              <p className="font-semibold">Как работает система уровней</p>
              <p>
                Уровень определяется <strong>автоматически</strong> по должности и отделу.
                Чтобы изменить уровень — обновите должность в разделе{' '}
                <a href="/hr/employees" className="underline">Сотрудники</a>.
              </p>
              <div className="mt-2 grid grid-cols-1 gap-0.5 text-xs opacity-80 sm:grid-cols-2">
                <span>🏛️ Ген. директор / CEO / COO / CTO / CFO → <strong>Lead</strong></span>
                <span>👑 HR-директор / CPO / Руководитель HR → <strong>Lead</strong></span>
                <span>🛡️ Старший HR / Ведущий / Head → <strong>Senior</strong></span>
                <span>⚙️ HR-менеджер / Специалист / Middle → <strong>Middle</strong></span>
                <span>📋 Junior HR / Ассистент / Стажёр → <strong>Junior</strong></span>
                <span>🔒 Остальные сотрудники → <strong>Нет доступа</strong></span>
              </div>
            </div>
          </div>
        </div>

        {/* My access */}
        {myLevel && (
          <div className="rounded-xl border bg-card p-4">
            <div className="flex items-center gap-3">
              <Users className="h-5 w-5 text-muted-foreground" />
              <span className="text-sm font-medium">Ваш уровень доступа:</span>
              <LevelBadge level={myLevel.level} />
            </div>
            {myLevel.level && (
              <div className="mt-3 flex flex-wrap gap-2">
                {[
                  { key: 'can_read_all', label: 'Чтение всех' },
                  { key: 'can_write_basic', label: 'Базовые изм.' },
                  { key: 'can_create_employee', label: 'Создание' },
                  { key: 'can_transfer_employee', label: 'Перевод' },
                  { key: 'can_delete_employee', label: 'Удаление' },
                  { key: 'can_list_user_options', label: 'Просм. акк.' },
                  { key: 'can_manage_user_options', label: 'Упр. акк.' },
                ].map(({ key, label }) => {
                  const has = myLevel[key as keyof HRLevelResponse] as boolean;
                  return (
                    <span
                      key={key}
                      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs ${has
                        ? 'border-green-200 bg-green-50 text-green-700 dark:border-green-800 dark:bg-green-950/30 dark:text-green-400'
                        : 'border-muted text-muted-foreground/40 line-through'
                        }`}
                    >
                      {has ? <CheckCircle2 className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}
                      {label}
                    </span>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {/* Level overview cards */}
        <div>
          <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-muted-foreground uppercase tracking-wide">
            <Building2 className="h-4 w-4" />
            Распределение по уровням
          </h2>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {LEVELS_ORDER.map((lvl) => (
              <LevelCard key={lvl} level={lvl} count={counts[lvl]} />
            ))}
          </div>
        </div>

        {/* Permission matrix table */}
        <div className="rounded-xl border bg-card overflow-hidden">
          <div className="border-b px-4 py-3">
            <h2 className="text-sm font-semibold">Матрица разрешений</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-muted/40">
                  <th className="px-4 py-2 text-left font-medium text-muted-foreground">Разрешение</th>
                  {LEVELS_ORDER.map((lvl) => {
                    const cfg = LEVEL_CONFIG[lvl];
                    const Icon = cfg.icon;
                    return (
                      <th key={lvl} className="px-3 py-2 text-center font-medium">
                        <span className={`inline-flex items-center gap-1 ${cfg.color}`}>
                          <Icon className="h-3.5 w-3.5" />{cfg.label}
                        </span>
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {ALL_PERMISSIONS.map((perm, i) => (
                  <tr key={perm} className={i % 2 === 0 ? '' : 'bg-muted/20'}>
                    <td className="px-4 py-2 text-sm">{perm}</td>
                    {LEVELS_ORDER.map((lvl) => {
                      const has = LEVEL_CONFIG[lvl].permissions.includes(perm);
                      return (
                        <td key={lvl} className="px-3 py-2 text-center">
                          {has
                            ? <CheckCircle2 className="mx-auto h-4 w-4 text-green-500" />
                            : <XCircle className="mx-auto h-4 w-4 text-muted-foreground/25" />
                          }
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Employee list */}
        <div>
          <div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <h2 className="flex items-center gap-2 text-sm font-semibold text-muted-foreground uppercase tracking-wide">
              <Users className="h-4 w-4" />
              Сотрудники и их уровни
            </h2>
            <div className="flex items-center gap-2">
              {/* Level filter pills */}
              <div className="flex items-center gap-1">
                <button
                  onClick={() => setFilterLevel('all')}
                  className={`rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors ${filterLevel === 'all'
                    ? 'border-foreground bg-foreground text-background'
                    : 'border-muted text-muted-foreground hover:border-foreground/40'
                    }`}
                >
                  Все ({enriched.length})
                </button>
                {LEVELS_ORDER.map((lvl) => {
                  const cfg = LEVEL_CONFIG[lvl];
                  return (
                    <button
                      key={lvl}
                      onClick={() => setFilterLevel(filterLevel === lvl ? 'all' : lvl)}
                      className={`rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors ${filterLevel === lvl
                        ? `${cfg.bg} ${cfg.border} ${cfg.color}`
                        : 'border-muted text-muted-foreground hover:border-foreground/40'
                        }`}
                    >
                      {cfg.label} ({counts[lvl]})
                    </button>
                  );
                })}
              </div>
            </div>
          </div>

          <div className="relative mb-3">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder="Поиск по имени, должности, отделу..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9"
            />
          </div>

          {isLoading ? (
            <div className="flex items-center justify-center py-12 text-muted-foreground">
              <div className="h-5 w-5 animate-spin rounded-full border-2 border-muted-foreground border-t-transparent mr-2" />
              Загрузка...
            </div>
          ) : filtered.length === 0 ? (
            <div className="rounded-xl border border-dashed p-8 text-center text-sm text-muted-foreground">
              Сотрудники не найдены
            </div>
          ) : (
            <div className="space-y-2">
              {filtered.map((emp) => (
                <EmployeeRow key={emp.id} employee={emp} />
              ))}
            </div>
          )}
        </div>
      </div>
    </HRLayout>
  );
}
