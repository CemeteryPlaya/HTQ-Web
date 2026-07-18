/**
 * EmployeeCardView — рендер полной карточки сотрудника (presentational).
 *
 * Используется тремя страницами:
 *  - /hr/employees/:id           (mode='auth')   — все поля + контакты
 *  - /public/employee/:token     (mode='public') — без email/phone, без id-ссылок
 *  - /myprofile (компактный)     (mode='auth')   — те же поля, но без header-имени
 *
 * Компонент не знает, как открыли карточку и кто её смотрит. Все решения о
 * том, что показывать (контакты, ссылки на других сотрудников, и т.д.)
 * принимаются здесь по ``mode`` props.
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
} from 'lucide-react';

import type { EmployeeCard, EmployeeCardBrief } from '@/api/hr';
import { Badge } from '@/components/ui/badge';

interface Props {
  card: EmployeeCard;
  mode: 'auth' | 'public';
  /** Скрыть header (имя + аватар) — для компактных вставок (например, MyHRCard). */
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
    <div className="flex gap-3 text-sm">
      <Icon
        className="mt-0.5 h-4 w-4 flex-shrink-0 text-muted-foreground"
        aria-hidden
      />
      <div className="min-w-0 flex-1">
        <div className="text-xs uppercase tracking-wide text-muted-foreground">
          {label}
        </div>
        <div className="break-words text-foreground">{children || '—'}</div>
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
          className="h-10 w-10 rounded-full object-cover ring-1 ring-border"
        />
      ) : (
        <div className="flex h-10 w-10 items-center justify-center rounded-full bg-muted text-muted-foreground">
          <Users className="h-4 w-4" />
        </div>
      )}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5 truncate font-medium">
          <span className="truncate">{person.full_name || '—'}</span>
          {badge}
        </div>
        <div className="truncate text-xs text-muted-foreground">
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
        className="flex items-center gap-3 rounded-md border bg-background px-3 py-2 transition hover:bg-muted/50"
      >
        {inner}
      </Link>
    );
  }
  return (
    <div className="flex items-center gap-3 rounded-md border bg-background px-3 py-2">
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

  return (
    <div className="grid gap-4">
      {!hideHeader && (
        <div className="rounded-2xl border bg-card p-6 shadow-sm">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
            {card.avatar_url ? (
              <img
                src={card.avatar_url}
                alt=""
                className="h-20 w-20 rounded-full object-cover ring-2 ring-background shadow"
              />
            ) : (
              <div className="flex h-20 w-20 items-center justify-center rounded-full bg-muted text-muted-foreground">
                <Users className="h-9 w-9" />
              </div>
            )}
            <div className="min-w-0 flex-1">
              <h2 className="truncate text-2xl font-semibold">
                {card.full_name || '—'}
              </h2>
              <p className="truncate text-sm text-muted-foreground">
                {[card.position?.title, card.department?.name]
                  .filter(Boolean)
                  .join(' · ') || 'Без должности'}
              </p>
              <div className="mt-2 flex flex-wrap gap-1.5">
                <Badge variant="outline" className="capitalize">
                  {card.status}
                </Badge>
                {card.position?.level !== undefined && (
                  <Badge variant="secondary">Уровень {card.position.level}</Badge>
                )}
              </div>
            </div>
          </div>
          {card.bio && (
            <p className="mt-4 whitespace-pre-line rounded-md bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
              {card.bio}
            </p>
          )}
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        <section className="rounded-2xl border bg-card p-6 shadow-sm">
          <h3 className="mb-4 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Контакты и должность
          </h3>
          <div className="grid gap-3">
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
                      className="underline-offset-2 hover:underline"
                      href={`mailto:${card.email}`}
                    >
                      {card.email}
                    </a>
                  ) : null}
                </FieldRow>
                <FieldRow icon={Phone} label="Телефон">
                  {card.phone ? (
                    <a
                      className="underline-offset-2 hover:underline"
                      href={`tel:${card.phone}`}
                    >
                      {card.phone}
                    </a>
                  ) : null}
                </FieldRow>
              </>
            )}
            {!isAuth && (
              <p className="text-xs italic text-muted-foreground">
                Контакты доступны только сотрудникам компании.
              </p>
            )}
          </div>
        </section>

        <section className="rounded-2xl border bg-card p-6 shadow-sm">
          <div className="mb-4 flex items-center justify-between">
            <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              Проекты PMO
            </h3>
            {card.pmos.length > 0 && (
              <Badge
                variant={totalAllocation > 100 ? 'destructive' : 'outline'}
              >
                {totalAllocation}%
              </Badge>
            )}
          </div>
          {card.pmos.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Сотрудник пока не закреплён ни за одним проектом.
            </p>
          ) : (
            <ul className="space-y-2">
              {card.pmos.map((p) => (
                <li
                  key={p.pmo_id}
                  className="flex items-center justify-between gap-3 rounded-md border bg-background px-3 py-2 text-sm"
                >
                  <div className="min-w-0">
                    <div className="flex items-center gap-1.5 font-medium">
                      <span className="truncate">{p.pmo_name}</span>
                      {p.is_primary && (
                        <Badge variant="default" className="h-4 text-[10px]">
                          Лид
                        </Badge>
                      )}
                    </div>
                    <div className="truncate text-xs text-muted-foreground">
                      {p.pmo_code} ·{' '}
                      {p.position_in_pmo || p.membership_type}
                    </div>
                  </div>
                  <span className="ml-2 flex-shrink-0 font-mono text-muted-foreground">
                    {p.allocation_percent}%
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <section className="rounded-2xl border bg-card p-6 shadow-sm">
          <h3 className="mb-4 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Руководитель
          </h3>
          {card.manager ? (
            <PersonBrief
              person={card.manager}
              mode={mode}
              badge={
                <span title="Руководитель отдела">
                  <Crown className="h-3.5 w-3.5 text-amber-500" />
                </span>
              }
            />
          ) : (
            <p className="text-sm text-muted-foreground">
              Прямой руководитель не назначен.
            </p>
          )}
        </section>

        <section className="rounded-2xl border bg-card p-6 shadow-sm">
          <h3 className="mb-4 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Прямые подчинённые ({card.subordinates.length})
          </h3>
          {card.subordinates.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Сотрудник не руководит отделом.
            </p>
          ) : (
            <ul className="space-y-2">
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
