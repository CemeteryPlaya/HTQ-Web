/**
 * EmployeeCardView — рендер полной карточки сотрудника (presentational).
 */
import { Link } from 'react-router-dom';
import {
  Briefcase,
  Building2,
  Calendar,
  Crown,
  Mail,
  Phone,
  Users,
  FolderGit2,
  UserCheck,
} from 'lucide-react';

import type { EmployeeCard, EmployeeCardBrief } from '@/api/hr';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

interface Props {
  card: EmployeeCard;
  mode: 'auth' | 'public';
  hideHeader?: boolean;
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleDateString('ru');
  } catch {
    return iso;
  }
}

function FieldRow({
  icon: Icon,
  label,
  children,
}: {
  icon: typeof Mail;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex gap-3 text-sm items-start">
      <div className="mt-0.5 rounded-md bg-muted/60 p-1.5 text-muted-foreground shrink-0">
        <Icon className="h-3.5 w-3.5" aria-hidden />
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground/80">
          {label}
        </div>
        <div className="break-words font-medium text-foreground text-sm mt-0.5">{children || '—'}</div>
      </div>
    </div>
  );
}

function PersonBrief({
  person,
  mode,
  badge,
}: {
  person: EmployeeCardBrief;
  mode: 'auth' | 'public';
  badge?: React.ReactNode;
}) {
  const inner = (
    <>
      {person.avatar_url ? (
        <img
          src={person.avatar_url}
          alt=""
          className="h-10 w-10 rounded-full object-cover ring-2 ring-background shadow-xs shrink-0"
        />
      ) : (
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary font-semibold text-sm">
          {person.full_name?.charAt(0).toUpperCase() || 'U'}
        </div>
      )}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5 truncate font-semibold text-sm">
          <span className="truncate">{person.full_name || '—'}</span>
          {badge}
        </div>
        <div className="truncate text-xs text-muted-foreground mt-0.5">
          {[person.position_title, person.department_name]
            .filter(Boolean)
            .join(' · ') || '—'}
        </div>
      </div>
    </>
  );

  if (mode === 'auth') {
    return (
      <Link
        to={`/hr/employees/${person.id}`}
        className="flex items-center gap-3 rounded-xl border bg-muted/20 hover:bg-muted/60 px-3.5 py-2.5 transition-all hover:border-primary/30 shadow-2xs"
      >
        {inner}
      </Link>
    );
  }
  return (
    <div className="flex items-center gap-3 rounded-xl border bg-muted/20 px-3.5 py-2.5">
      {inner}
    </div>
  );
}

export function EmployeeCardView({ card, mode, hideHeader }: Props) {
  const totalAllocation = card.pmos.reduce(
    (acc, p) => acc + (p.allocation_percent || 0),
    0,
  );
  const isAuth = mode === 'auth';
  const hasContacts = Boolean(card.email || card.phone);

  const isActive = card.status?.toLowerCase() === 'active';

  return (
    <div className="grid gap-6">
      {!hideHeader && (
        <div className="rounded-3xl border bg-card p-6 shadow-2xs hover:shadow-xs transition-all">
          <div className="flex flex-col gap-5 sm:flex-row sm:items-center">
            {card.avatar_url ? (
              <img
                src={card.avatar_url}
                alt=""
                className="h-20 w-20 rounded-full object-cover ring-4 ring-primary/10 shadow-md shrink-0"
              />
            ) : (
              <div className="flex h-20 w-20 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary text-2xl font-bold">
                {card.full_name?.charAt(0).toUpperCase() || 'U'}
              </div>
            )}
            <div className="min-w-0 flex-1 space-y-1">
              <div className="flex flex-wrap items-center gap-3">
                <h2 className="truncate text-2xl font-bold tracking-tight">
                  {card.full_name || '—'}
                </h2>
                <Badge
                  variant="outline"
                  className={cn(
                    'capitalize gap-1.5 px-2.5 py-0.5 text-xs font-semibold',
                    isActive
                      ? 'bg-emerald-500/10 text-emerald-700 border-emerald-300 dark:text-emerald-400 dark:border-emerald-800'
                      : 'bg-amber-500/10 text-amber-700 border-amber-300 dark:text-amber-400 dark:border-amber-800'
                  )}
                >
                  <span
                    className={cn(
                      'h-2 w-2 rounded-full',
                      isActive ? 'bg-emerald-500 animate-pulse' : 'bg-amber-500'
                    )}
                  />
                  {card.status}
                </Badge>
              </div>

              <p className="truncate text-sm text-muted-foreground font-medium">
                {[card.position?.title, card.department?.name]
                  .filter(Boolean)
                  .join(' · ') || 'Без должности'}
              </p>

              {card.position?.level !== undefined && (
                <div className="pt-1">
                  <Badge variant="secondary" className="text-xs font-semibold">
                    Уровень {card.position.level}
                  </Badge>
                </div>
              )}
            </div>
          </div>

          {card.bio && (
            <p className="mt-4 whitespace-pre-line rounded-xl bg-muted/40 px-4 py-3 text-sm text-muted-foreground leading-relaxed">
              {card.bio}
            </p>
          )}
        </div>
      )}

      {/* Grid: Contacts & PMO */}
      <div className="grid gap-6 md:grid-cols-2">
        {/* Contacts & Position */}
        <section className="rounded-3xl border bg-card p-6 shadow-2xs hover:shadow-xs transition-all">
          <h3 className="mb-4 text-xs font-bold uppercase tracking-wider text-muted-foreground/80 flex items-center gap-2">
            <Briefcase className="h-4 w-4 text-primary" />
            Контакты и должность
          </h3>
          <div className="grid gap-4">
            <FieldRow icon={Briefcase} label="Должность">
              {card.position?.title || '—'}
            </FieldRow>
            <FieldRow icon={Building2} label="Отдел">
              {card.department?.name || '—'}
            </FieldRow>
            <FieldRow icon={Calendar} label="Дата найма">
              {fmtDate(card.hire_date)}
            </FieldRow>
            {isAuth && hasContacts && (
              <>
                <FieldRow icon={Mail} label="Email">
                  {card.email ? (
                    <a
                      className="text-primary hover:underline font-medium"
                      href={`mailto:${card.email}`}
                    >
                      {card.email}
                    </a>
                  ) : null}
                </FieldRow>
                <FieldRow icon={Phone} label="Телефон">
                  {card.phone ? (
                    <a
                      className="text-primary hover:underline font-medium"
                      href={`tel:${card.phone}`}
                    >
                      {card.phone}
                    </a>
                  ) : null}
                </FieldRow>
              </>
            )}
            {!isAuth && (
              <p className="text-xs italic text-muted-foreground pt-1">
                Контакты доступны только сотрудникам компании.
              </p>
            )}
          </div>
        </section>

        {/* PMO Projects */}
        <section className="rounded-3xl border bg-card p-6 shadow-2xs hover:shadow-xs transition-all">
          <div className="mb-4 flex items-center justify-between">
            <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground/80 flex items-center gap-2">
              <FolderGit2 className="h-4 w-4 text-primary" />
              Проекты PMO
            </h3>
            {card.pmos.length > 0 && (
              <Badge
                variant={totalAllocation > 100 ? 'destructive' : 'outline'}
                className="font-mono text-xs"
              >
                Загрузка: {totalAllocation}%
              </Badge>
            )}
          </div>
          {card.pmos.length === 0 ? (
            <p className="text-sm text-muted-foreground py-4 text-center border rounded-xl bg-muted/20">
              Сотрудник пока не закреплён ни за одним проектом.
            </p>
          ) : (
            <ul className="space-y-2.5">
              {card.pmos.map((p) => (
                <li
                  key={p.pmo_id}
                  className="flex items-center justify-between gap-3 rounded-xl border bg-muted/20 hover:bg-muted/50 px-3.5 py-2.5 text-sm transition-colors"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 font-semibold">
                      <span className="truncate">{p.pmo_name}</span>
                      {p.is_primary && (
                        <Badge variant="secondary" className="h-4 text-[10px] font-semibold">
                          Лид
                        </Badge>
                      )}
                    </div>
                    <div className="truncate text-xs text-muted-foreground mt-0.5">
                      {p.pmo_code} · {p.position_in_pmo || p.membership_type}
                    </div>
                  </div>
                  <span className="font-mono text-sm font-semibold text-foreground shrink-0">
                    {p.allocation_percent}%
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      {/* Manager & Subordinates */}
      <div className="grid gap-6 md:grid-cols-2">
        {/* Manager */}
        <section className="rounded-3xl border bg-card p-6 shadow-2xs hover:shadow-xs transition-all">
          <h3 className="mb-4 text-xs font-bold uppercase tracking-wider text-muted-foreground/80 flex items-center gap-2">
            <Crown className="h-4 w-4 text-amber-500" />
            Руководитель
          </h3>
          {card.manager ? (
            <PersonBrief
              person={card.manager}
              mode={mode}
              badge={
                <span title="Руководитель">
                  <Crown className="h-3.5 w-3.5 text-amber-500" />
                </span>
              }
            />
          ) : (
            <p className="text-sm text-muted-foreground py-4 text-center border rounded-xl bg-muted/20">
              Прямой руководитель не назначен.
            </p>
          )}
        </section>

        {/* Subordinates */}
        <section className="rounded-3xl border bg-card p-6 shadow-2xs hover:shadow-xs transition-all">
          <h3 className="mb-4 text-xs font-bold uppercase tracking-wider text-muted-foreground/80 flex items-center gap-2">
            <UserCheck className="h-4 w-4 text-primary" />
            Прямые подчинённые ({card.subordinates.length})
          </h3>
          {card.subordinates.length === 0 ? (
            <p className="text-sm text-muted-foreground py-4 text-center border rounded-xl bg-muted/20">
              Сотрудник не руководит отделом.
            </p>
          ) : (
            <ul className="space-y-2.5">
              {card.subordinates.map((sub) => (
                <li key={sub.id}>
                  <PersonBrief person={sub} mode={mode} />
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}
