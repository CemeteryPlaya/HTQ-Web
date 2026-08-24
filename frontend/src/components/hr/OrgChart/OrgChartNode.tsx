import { memo } from 'react';
import { Handle, Position, type NodeProps } from '@xyflow/react';
import { useTranslation } from 'react-i18next';
import i18next from '@/i18n';
import { translatedMap } from '@/lib/i18n/translatedMap';
import {
  BriefcaseBusiness,
  Building2,
  Mail,
  Pencil,
  Phone,
  type LucideIcon,
  UserRound,
  Users,
  UsersRound,
} from 'lucide-react';

export type OrgNodeData = {
  label: string;
  type: 'department' | 'position' | 'employee' | 'pmo' | string;
  unit_type?: string | null;
  level?: number | null;
  weight?: number | null;
  direction?: 'TB' | 'LR';
  meta?: Record<string, unknown>;
  /** Ручная правка включена */
  editable?: boolean;
  /** Количество прямых подчинённых */
  reportsCount?: number;
  /** Пока тянут связь: годится ли эта карточка как цель. null — не тянут. */
  dropState?: 'valid' | 'invalid' | null;
  /** Фокус на ветке: 'in' — входит в ветку, 'out' — вне её, null — фокуса нет. */
  branchState?: 'in' | 'out' | null;
};

const UNIT_LABELS: Record<string, string> = translatedMap({
  headquarters: 'hr.orgChart.unit.headquarters',
  division: 'hr.orgChart.unit.division',
  department: 'hr.orgChart.unit.department',
  pmo: 'hr.orgChart.unit.pmo',
});

function getMetaString(meta: Record<string, unknown> | undefined, key: string): string | null {
  const value = meta?.[key];
  return typeof value === 'string' && value.trim() ? value : null;
}

function getMetaNumber(meta: Record<string, unknown> | undefined, key: string): number | null {
  const value = meta?.[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function getInitials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return '?';
  const first = parts[0]?.[0] ?? '';
  const last = parts.length > 1 ? parts[parts.length - 1]?.[0] ?? '' : '';
  return (first + last).toUpperCase() || '?';
}

function cardTone(data: OrgNodeData): string {
  if (data.type === 'department') {
    return 'border-slate-300/80 bg-white/95 text-slate-950 dark:border-slate-700/80 dark:bg-neutral-950/95 dark:text-slate-50 shadow-xs hover:border-primary/60';
  }
  if (data.type === 'employee') {
    return 'border-emerald-300/80 bg-emerald-50/70 text-emerald-950 dark:border-emerald-800/80 dark:bg-emerald-950/40 dark:text-emerald-50 shadow-xs hover:border-emerald-500';
  }
  if (data.type === 'pmo') {
    return 'border-amber-300/80 bg-amber-50/70 text-amber-950 dark:border-amber-800/80 dark:bg-amber-950/40 dark:text-amber-50 shadow-xs hover:border-amber-500';
  }
  if (getMetaString(data.meta, 'holder_name')) {
    return 'border-sky-300/80 bg-sky-50/70 text-sky-950 dark:border-sky-800/80 dark:bg-sky-950/40 dark:text-sky-50 shadow-xs hover:border-sky-500';
  }
  return 'border-slate-300/80 bg-slate-50/70 text-slate-950 dark:border-slate-700/80 dark:bg-slate-900/40 dark:text-slate-50 shadow-xs hover:border-primary/50';
}

function unitLabel(data: OrgNodeData): string {
  const key = data.type === 'department' ? data.unit_type ?? 'department' : data.type;
  return UNIT_LABELS[key] ?? i18next.t('hr.orgChart.unit.generic');
}

function resolveContent(data: OrgNodeData): {
  primary: string;
  secondary: string;
  avatarUrl: string | null;
  icon: LucideIcon;
  extraCount: number;
} {
  const meta = data.meta;
  const holderName = getMetaString(meta, 'holder_name');
  const holderCount = getMetaNumber(meta, 'holder_count') ?? 0;

  if (data.type === 'position') {
    const headsDept = getMetaString(meta, 'heads_department_name');
    const ownDept = getMetaString(meta, 'department_name');
    const titleLine = data.label;
    let contextLine: string | null = null;
    if (headsDept) {
      contextLine = i18next.t('hr.orgChart.headsDepartment', { department: headsDept });
    } else if (ownDept) {
      contextLine = ownDept;
    }
    const secondary = holderName
      ? [titleLine, contextLine].filter(Boolean).join(' · ')
      : i18next.t('hr.orgChart.vacant');
    return {
      primary: holderName ?? data.label,
      secondary,
      avatarUrl: getMetaString(meta, 'holder_avatar_url'),
      icon: holderName ? UserRound : BriefcaseBusiness,
      extraCount: Math.max(0, holderCount - 1),
    };
  }

  if (data.type === 'department') {
    const managerName = getMetaString(meta, 'manager_name');
    return {
      primary: data.label,
      secondary: managerName ? i18next.t('hr.orgChart.managerName', { name: managerName }) : unitLabel(data),
      avatarUrl: getMetaString(meta, 'manager_avatar_url'),
      icon: managerName ? UsersRound : Building2,
      extraCount: 0,
    };
  }

  if (data.type === 'employee') {
    return {
      primary: data.label,
      secondary:
        getMetaString(meta, 'position_title') ??
        getMetaString(meta, 'department_name') ??
        i18next.t('hr.orgChart.employee'),
      avatarUrl: getMetaString(meta, 'avatar_url'),
      icon: UserRound,
      extraCount: 0,
    };
  }

  return {
    primary: data.label,
    secondary:
      [getMetaString(meta, 'code'), getMetaString(meta, 'status')]
        .filter(Boolean)
        .join(' · ') || unitLabel(data),
    avatarUrl: null,
    icon: UsersRound,
    extraCount: 0,
  };
}

function AvatarMark({
  name,
  avatarUrl,
  icon: Icon,
}: {
  name: string;
  avatarUrl: string | null;
  icon: LucideIcon;
}) {
  if (avatarUrl) {
    return (
      <img
        src={avatarUrl}
        alt=""
        className="h-11 w-11 rounded-full object-cover ring-2 ring-white shadow-xs dark:ring-neutral-900"
      />
    );
  }

  return (
    <span className="flex h-11 w-11 items-center justify-center rounded-full bg-white text-xs font-bold text-slate-700 ring-1 ring-slate-200 dark:bg-neutral-900 dark:text-slate-200 dark:ring-slate-700 shadow-xs">
      {name ? getInitials(name) : <Icon className="h-5 w-5" aria-hidden="true" />}
    </span>
  );
}

export const OrgChartNode = memo(({ data, selected }: NodeProps) => {
  const { t } = useTranslation();
  const d = data as OrgNodeData;
  const content = resolveContent(d);
  const holderEmail = getMetaString(d.meta, 'holder_email');
  const holderPhone = getMetaString(d.meta, 'holder_phone');
  const showContacts =
    d.type === 'position' &&
    Boolean(getMetaString(d.meta, 'holder_name')) &&
    Boolean(holderEmail || holderPhone);
  const levelColor = getMetaString(d.meta, 'level_color');
  const isHorizontal = d.direction === 'LR';
  const targetPosition = isHorizontal ? Position.Left : Position.Top;
  const sourcePosition = isHorizontal ? Position.Right : Position.Bottom;

  const handleClassName = d.editable
    ? '!h-3.5 !w-3.5 !bg-sky-500 hover:!bg-sky-400 !opacity-100 !border-2 !border-white dark:!border-neutral-900 shadow-sm transition-transform hover:scale-125 cursor-crosshair'
    : '!h-2 !w-2 !bg-slate-400 !opacity-60';

  const reportsCount = d.reportsCount ?? 0;

  return (
    <div
      style={levelColor ? { borderColor: levelColor } : undefined}
      className={`group relative h-[168px] w-[215px] rounded-xl border px-3 py-2.5 transition-all duration-200 backdrop-blur-xs ${cardTone(
        d
      )} ${
        selected ? 'ring-2 ring-primary ring-offset-2 shadow-md' : ''
      } ${
        d.editable ? 'hover:shadow-md' : ''
      } ${
        // Фокус на ветке: своё — подсвечено, чужое — приглушено.
        d.branchState === 'in'
          ? 'ring-2 ring-primary/70 shadow-lg z-10'
          : d.branchState === 'out'
            ? 'opacity-25 saturate-50'
            : ''
      } ${
        // Пока тянут связь — видно, куда бросать можно, а куда нет.
        d.dropState === 'valid'
          ? 'ring-2 ring-sky-500 ring-offset-1 shadow-lg scale-[1.02]'
          : d.dropState === 'invalid'
            ? 'opacity-40 grayscale'
            : ''
      }`}
    >
      {/* Target connector handle */}
      <Handle
        type="target"
        position={targetPosition}
        className={handleClassName}
        title={d.editable ? t('hr.orgChart.reportToNode') : undefined}
      />

      {/* Level Tag (top-left) */}
      {d.level != null && (
        <span className="absolute left-2 top-2 rounded-md bg-background/80 px-1.5 py-0.5 text-[9px] font-bold text-muted-foreground ring-1 ring-border/60">
          L{d.level}
        </span>
      )}

      {/* Reports Count or Extra Holders (top-right) */}
      <div className="absolute right-2 top-2 flex items-center gap-1">
        {content.extraCount > 0 && (
          <span className="rounded-full bg-white/95 px-1.5 py-0.5 text-[10px] font-bold text-slate-700 ring-1 ring-slate-200 dark:bg-neutral-900/95 dark:text-slate-200 dark:ring-slate-700">
            +{content.extraCount}
          </span>
        )}
        {reportsCount > 0 && (
          <span
            className="flex items-center gap-0.5 rounded-full bg-primary/10 px-1.5 py-0.5 text-[10px] font-semibold text-primary ring-1 ring-primary/20"
            title={t('hr.orgChart.directReportsCount', { count: reportsCount })}
          >
            <Users className="h-2.5 w-2.5" />
            {reportsCount}
          </span>
        )}
        {d.editable && (
          <span className="opacity-0 group-hover:opacity-100 transition-opacity p-0.5 rounded bg-background/80 text-muted-foreground hover:text-foreground">
            <Pencil className="h-3 w-3" />
          </span>
        )}
      </div>

      <div className="flex h-full min-w-0 flex-col items-center justify-center text-center pt-1">
        <AvatarMark name={content.primary} avatarUrl={content.avatarUrl} icon={content.icon} />
        <div className="mt-1.5 min-w-0 max-w-full">
          <p className="truncate text-xs font-bold leading-snug text-foreground" title={content.primary}>
            {content.primary}
          </p>
          <p
            className="mt-0.5 line-clamp-2 text-[11px] leading-tight text-muted-foreground"
            title={content.secondary}
          >
            {content.secondary}
          </p>
        </div>
        {showContacts && (
          <div className="mt-1.5 w-full space-y-0.5 text-left text-[10px] leading-tight text-muted-foreground">
            {holderEmail && (
              <div className="flex min-w-0 items-center gap-1" title={holderEmail}>
                <Mail className="h-2.5 w-2.5 shrink-0" aria-hidden="true" />
                <span className="truncate">{holderEmail}</span>
              </div>
            )}
            {holderPhone && (
              <div className="flex min-w-0 items-center gap-1" title={holderPhone}>
                <Phone className="h-2.5 w-2.5 shrink-0" aria-hidden="true" />
                <span className="truncate">{holderPhone}</span>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Source connector handle */}
      <Handle
        type="source"
        position={sourcePosition}
        className={handleClassName}
        title={d.editable ? t('hr.orgChart.dragToAssign') : undefined}
      />
    </div>
  );
});

OrgChartNode.displayName = 'OrgChartNode';
