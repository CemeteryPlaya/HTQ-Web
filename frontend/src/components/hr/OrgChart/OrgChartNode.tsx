import { memo } from 'react';
import { Handle, Position, type NodeProps } from '@xyflow/react';
import {
  BriefcaseBusiness,
  Building2,
  Mail,
  Phone,
  type LucideIcon,
  UserRound,
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
};

const UNIT_LABELS: Record<string, string> = {
  headquarters: 'Головная структура',
  division: 'Направление',
  department: 'Подразделение',
  pmo: 'PMO',
};

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
    return 'border-slate-300 bg-white text-slate-950 dark:border-slate-700 dark:bg-neutral-950 dark:text-slate-50';
  }
  if (data.type === 'employee') {
    return 'border-emerald-300 bg-emerald-50 text-emerald-950 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-50';
  }
  if (data.type === 'pmo') {
    return 'border-amber-300 bg-amber-50 text-amber-950 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-50';
  }
  if (getMetaString(data.meta, 'holder_name')) {
    return 'border-sky-300 bg-sky-50 text-sky-950 dark:border-sky-800 dark:bg-sky-950 dark:text-sky-50';
  }
  return 'border-slate-300 bg-slate-50 text-slate-950 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-50';
}

function unitLabel(data: OrgNodeData): string {
  const key = data.type === 'department' ? data.unit_type ?? 'department' : data.type;
  return UNIT_LABELS[key] ?? 'Структура';
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
    // Compose the secondary line: position title plus, when relevant, either
    // "руководит отделом X" (for dept heads) or just the dept the position
    // sits in (for everyone else).
    const titleLine = data.label;
    let contextLine: string | null = null;
    if (headsDept) {
      contextLine = `Руководит: ${headsDept}`;
    } else if (ownDept) {
      contextLine = ownDept;
    }
    const secondary = holderName
      ? [titleLine, contextLine].filter(Boolean).join(' · ')
      : 'Вакантно';
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
      secondary: managerName ? `Руководитель: ${managerName}` : unitLabel(data),
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
        getMetaString(meta, 'department') ??
        'Сотрудник',
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
        className="h-12 w-12 rounded-full object-cover ring-2 ring-white shadow-sm dark:ring-neutral-900"
      />
    );
  }

  return (
    <span className="flex h-12 w-12 items-center justify-center rounded-full bg-white text-sm font-semibold text-slate-700 ring-1 ring-slate-200 dark:bg-neutral-900 dark:text-slate-200 dark:ring-slate-700">
      {name ? getInitials(name) : <Icon className="h-5 w-5" aria-hidden="true" />}
    </span>
  );
}

export const OrgChartNode = memo(({ data }: NodeProps) => {
  const d = data as OrgNodeData;
  const content = resolveContent(d);
  const holderEmail = getMetaString(d.meta, 'holder_email');
  const holderPhone = getMetaString(d.meta, 'holder_phone');
  const showContacts = d.type === 'position' && Boolean(getMetaString(d.meta, 'holder_name')) && Boolean(holderEmail || holderPhone);
  const levelColor = getMetaString(d.meta, 'level_color');
  const isHorizontal = d.direction === 'LR';
  const targetPosition = isHorizontal ? Position.Left : Position.Top;
  const sourcePosition = isHorizontal ? Position.Right : Position.Bottom;

  return (
    <div
      style={levelColor ? { borderColor: levelColor } : undefined}
      className={`relative h-[168px] w-[210px] rounded-md border px-3 py-3 shadow-sm ${cardTone(d)}`}
    >
      <Handle type="target" position={targetPosition} className="!h-2 !w-2 !bg-slate-400 !opacity-70" />

      {content.extraCount > 0 && (
        <span className="absolute right-2 top-2 rounded-full bg-white/90 px-1.5 py-0.5 text-[10px] font-semibold text-slate-600 ring-1 ring-slate-200 dark:bg-neutral-900/90 dark:text-slate-200 dark:ring-slate-700">
          +{content.extraCount}
        </span>
      )}

      <div className="flex h-full min-w-0 flex-col items-center justify-center text-center">
        <AvatarMark name={content.primary} avatarUrl={content.avatarUrl} icon={content.icon} />
        <div className="mt-2 min-w-0 max-w-full">
          <p className="truncate text-sm font-semibold leading-tight" title={content.primary}>
            {content.primary}
          </p>
          <p className="mt-0.5 line-clamp-2 text-xs leading-tight text-muted-foreground" title={content.secondary}>
            {content.secondary}
          </p>
        </div>
        {showContacts && (
          <div className="mt-2 w-full space-y-1 text-left text-[10px] leading-tight text-muted-foreground">
            {holderEmail && (
              <div className="flex min-w-0 items-center gap-1" title={holderEmail}>
                <Mail className="h-3 w-3 flex-shrink-0" aria-hidden="true" />
                <span className="truncate">{holderEmail}</span>
              </div>
            )}
            {holderPhone && (
              <div className="flex min-w-0 items-center gap-1" title={holderPhone}>
                <Phone className="h-3 w-3 flex-shrink-0" aria-hidden="true" />
                <span className="truncate">{holderPhone}</span>
              </div>
            )}
          </div>
        )}
      </div>

      <Handle type="source" position={sourcePosition} className="!h-2 !w-2 !bg-slate-400 !opacity-70" />
    </div>
  );
});

OrgChartNode.displayName = 'OrgChartNode';
