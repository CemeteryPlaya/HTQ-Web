import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Info } from 'lucide-react';

import { fetchMatchSuggestions } from '@/api/hr';
import type { EmployeeMatch, UserMatch } from '@/types/hr';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { matchQueryIsAnswerable } from '@/components/hr/employeePrefill';
import { useDebounced } from '@/components/mail/mailboxLookup';

/**
 * «Кажется, этого человека система уже знает».
 *
 * Плашка под полями формы, отвечающая на два разных вопроса одновременно:
 *
 * - **карточка уже есть** (`employees`) — предупреждение: заводят повторно.
 *   Раньше такой дубль ловился только уникальностью email, то есть не ловился
 *   вовсе, стоило человеку сменить почту;
 * - **есть учётка** (`users`) — предложение: вот откуда взять данные.
 *
 * Первый случай важнее и потому идёт выше и оформлен строже.
 *
 * Построена по образцу MailboxLookupNotice: тот же дебаунс и тот же приём
 * «не спрашиваем сервер, пока спрашивать не о чем».
 */

const DEBOUNCE_MS = 400;

interface Props {
  email: string;
  phone: string;
  firstName: string;
  lastName: string;
  patronymic?: string;
  /** Редактируемая карточка не должна находить саму себя. */
  excludeEmployeeId?: number | null;
  /** «Подтянуть» из найденной учётки — открывает диалог префилла. */
  onUseUser?: (user: UserMatch) => void;
  /** Открыть найденную карточку, чтобы убедиться, что это тот же человек. */
  onOpenEmployee?: (employee: EmployeeMatch) => void;
  enabled?: boolean;
}

const reasonLabel = (t: (k: string, d?: string) => string, reasons: string[]): string =>
  reasons
    .map((reason) => t(`hr.pages.employees.match.reason.${reason}`, reason))
    .join(', ');

const EmployeeMatchNotice = ({
  email, phone, firstName, lastName, patronymic = '',
  excludeEmployeeId = null, onUseUser, onOpenEmployee, enabled = true,
}: Props) => {
  const { t } = useTranslation();

  const query = useDebounced(
    { email, phone, firstName, lastName, patronymic },
    DEBOUNCE_MS,
  );
  const answerable = matchQueryIsAnswerable(query);

  const { data } = useQuery({
    queryKey: ['employee-match', query, excludeEmployeeId],
    queryFn: () => fetchMatchSuggestions({
      email: query.email,
      phone: query.phone,
      first_name: query.firstName,
      last_name: query.lastName,
      patronymic: query.patronymic,
      exclude_employee_id: excludeEmployeeId,
    }),
    enabled: enabled && answerable,
    staleTime: 30_000,
  });

  const employees = data?.employees ?? [];
  // Учётка, у которой карточка уже есть, не предлагается как источник — про
  // неё уже сказано в списке карточек выше.
  const users = (data?.users ?? []).filter((u) => !u.employee_id);

  if (employees.length === 0 && users.length === 0) return null;

  return (
    <div className="grid gap-2">
      {employees.length > 0 && (
        <Notice tone="warning" icon={AlertTriangle}>
          <p className="font-medium">
            {t('hr.pages.employees.match.duplicateTitle', 'Похоже, такой сотрудник уже есть')}
          </p>
          <ul className="mt-1 grid gap-1">
            {employees.map((employee) => (
              <li key={employee.id} className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{employee.full_name}</span>
                <span className="text-xs text-muted-foreground">
                  {[employee.position_title, employee.department_name].filter(Boolean).join(' · ')
                    || employee.email}
                </span>
                <span className="text-xs text-muted-foreground">
                  ({reasonLabel(t, employee.match_on)})
                </span>
                {onOpenEmployee && (
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    className="h-6 px-2 text-xs"
                    onClick={() => onOpenEmployee(employee)}
                  >
                    {t('hr.pages.employees.match.openCard', 'Открыть')}
                  </Button>
                )}
              </li>
            ))}
          </ul>
        </Notice>
      )}

      {users.length > 0 && (
        <Notice tone="info" icon={Info}>
          <p className="font-medium">
            {t('hr.pages.employees.match.userTitle', 'В системе есть подходящая учётная запись')}
          </p>
          <ul className="mt-1 grid gap-1">
            {users.map((user) => (
              <li key={user.id} className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{user.full_name}</span>
                <span className="text-xs text-muted-foreground">{user.email}</span>
                <span className="text-xs text-muted-foreground">
                  ({reasonLabel(t, user.match_on)})
                </span>
                {onUseUser && (
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    className="h-6 px-2 text-xs"
                    onClick={() => onUseUser(user)}
                  >
                    {t('hr.pages.employees.match.useUser', 'Подтянуть данные')}
                  </Button>
                )}
              </li>
            ))}
          </ul>
        </Notice>
      )}
    </div>
  );
};

const Notice = ({
  tone, icon: Icon, children,
}: {
  tone: 'warning' | 'info';
  icon: typeof Info;
  children: React.ReactNode;
}) => (
  <div
    className={cn(
      'flex gap-2 rounded-md border px-3 py-2 text-sm',
      tone === 'warning'
        ? 'border-destructive/40 bg-destructive/5'
        : 'border-primary/30 bg-primary/5',
    )}
  >
    <Icon
      className={cn('mt-0.5 h-4 w-4 shrink-0',
        tone === 'warning' ? 'text-destructive' : 'text-primary')}
    />
    <div className="min-w-0 flex-1">{children}</div>
  </div>
);

export default EmployeeMatchNotice;
