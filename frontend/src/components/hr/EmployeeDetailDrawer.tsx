/**
 * EmployeeDetailDrawer — side panel that opens on org-chart node click.
 *
 * Two modes:
 *   - mode="auth"   — full profile (email/phone/PMOs/dates) fetched from
 *                     /hr/v1/employees/{id}/ and /employees/{id}/pmos.
 *   - mode="public" — only the fields embedded in the org-tree node payload
 *                     (no extra fetch). Used by PublicOrgView so a share-link
 *                     recipient can browse one-time links.
 */
import { useQuery } from '@tanstack/react-query';
import {
  Building2,
  Briefcase,
  Calendar,
  Crown,
  Mail,
  Phone,
  Users,
} from 'lucide-react';

import api from '@/api/client';
import { Badge } from '@/components/ui/badge';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import type { OrgRawNode } from './OrgChart';
import { useTranslation } from 'react-i18next';

type Mode = 'auth' | 'public';

interface Props {
  node: OrgRawNode | null;
  mode: Mode;
  onClose: () => void;
}

interface EmployeeDetail {
  id: number;
  first_name: string;
  last_name: string;
  middle_name: string | null;
  email: string;
  phone: string | null;
  hire_date: string;
  status: string;
  avatar_url: string | null;
  bio: string | null;
  department: { id: number; name: string } | null;
  position: { id: number; title: string } | null;
}

interface EmployeePmo {
  pmo_id: number;
  pmo_name: string;
  pmo_code: string;
  pmo_status: string;
  membership_type: string;
  position_in_pmo: string | null;
  allocation_percent: number;
  is_primary: boolean;
}

function metaString(meta: Record<string, unknown> | undefined, key: string): string | null {
  const v = meta?.[key];
  return typeof v === 'string' && v.trim() ? v : null;
}

function metaNumber(meta: Record<string, unknown> | undefined, key: string): number | null {
  const v = meta?.[key];
  return typeof v === 'number' && Number.isFinite(v) ? v : null;
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleDateString('ru');
  } catch {
    return iso;
  }
}

function Field({ icon: Icon, label, value }: { icon: typeof Mail; label: string; value: React.ReactNode }) {
  return (
    <div className="flex gap-3 text-sm">
      <Icon className="mt-0.5 h-4 w-4 flex-shrink-0 text-muted-foreground" aria-hidden />
      <div className="min-w-0 flex-1">
        <div className="text-xs uppercase tracking-wide text-muted-foreground">{label}</div>
        <div className="break-words text-foreground">{value || '—'}</div>
      </div>
    </div>
  );
}

export function EmployeeDetailDrawer({ node, mode, onClose }: Props) {
  const { t } = useTranslation();
  const meta = node?.meta;
  const holderId = metaNumber(meta, 'holder_id');
  const holderName = metaString(meta, 'holder_name');
  const holderAvatar = metaString(meta, 'holder_avatar_url');
  const holderEmail = metaString(meta, 'holder_email');
  const holderPhone = metaString(meta, 'holder_phone');
  const departmentName = metaString(meta, 'department_name');
  const headsDepartmentName = metaString(meta, 'heads_department_name');
  const isPhantom = !holderName;
  const positionTitle = node?.label ?? '';

  // Authenticated mode pulls full employee profile + PMO list.
  const isAuthMode = mode === 'auth';
  const employeeQuery = useQuery<EmployeeDetail>({
    queryKey: ['hr-employee-detail', holderId],
    queryFn: async () => (await api.get(`hr/v1/employees/${holderId}/`)).data,
    enabled: Boolean(node) && isAuthMode && Boolean(holderId),
  });
  const pmosQuery = useQuery<EmployeePmo[]>({
    queryKey: ['hr-employee-pmos', holderId],
    queryFn: async () => (await api.get(`hr/v1/employees/${holderId}/pmos`)).data,
    enabled: Boolean(node) && isAuthMode && Boolean(holderId),
  });

  const employee = employeeQuery.data;
  const pmos = pmosQuery.data ?? [];
  const totalAllocation = pmos.reduce((acc, p) => acc + p.allocation_percent, 0);

  return (
    <Sheet open={Boolean(node)} onOpenChange={(o) => !o && onClose()}>
      <SheetContent
        side="right"
        className="!inset-x-0 !bottom-0 !top-auto !h-[85dvh] !w-full overflow-y-auto rounded-t-xl border-t p-4 pb-[calc(1rem+env(safe-area-inset-bottom))] sm:!inset-y-0 sm:!left-auto sm:!right-0 sm:!h-full sm:!w-[420px] sm:max-w-[480px] sm:rounded-none sm:border-l sm:border-t-0 sm:p-6"
      >
        <SheetHeader>
          <div className="flex items-center gap-3">
            {holderAvatar ? (
              <img
                src={holderAvatar}
                alt=""
                className="h-14 w-14 rounded-full object-cover ring-2 ring-white shadow"
              />
            ) : (
              <div className="flex h-14 w-14 items-center justify-center rounded-full bg-muted text-muted-foreground">
                <Users className="h-6 w-6" />
              </div>
            )}
            <div className="min-w-0 flex-1">
              <SheetTitle className="truncate text-left">
                {holderName ?? positionTitle}
              </SheetTitle>
              <SheetDescription className="text-left">
                {holderName ? positionTitle : t('hr.card.position')}
              </SheetDescription>
            </div>
          </div>
        </SheetHeader>

        <div className="mt-5 space-y-4">
          {/* Phantom (vacant) flag — visible in both modes */}
          {isPhantom && (
            <div className="rounded-md border border-dashed bg-muted/30 px-3 py-2 text-xs italic text-muted-foreground">
              {t('hr.drawer.positionVacant')}
            </div>
          )}

          {/* Department head badge */}
          {headsDepartmentName && (
            <div className="flex items-center gap-2 rounded-md border bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
              <Crown className="h-4 w-4" />
              <span>{t('hr.drawer.headsDepartment', { department: headsDepartmentName })}</span>
            </div>
          )}

          <Field
            icon={Briefcase}
            label={t('hr.card.position')}
            value={positionTitle}
          />
          <Field
            icon={Building2}
            label={t('hr.card.department')}
            value={departmentName}
          />

          {!isAuthMode && holderName && (
            <div className="space-y-3 border-t pt-4">
              <Field icon={Mail} label="Email" value={
                holderEmail
                  ? <a className="underline-offset-2 hover:underline" href={`mailto:${holderEmail}`}>{holderEmail}</a>
                  : null
              } />
              <Field icon={Phone} label={t('profile.phone')} value={
                holderPhone
                  ? <a className="underline-offset-2 hover:underline" href={`tel:${holderPhone}`}>{holderPhone}</a>
                  : null
              } />
            </div>
          )}

          {/* Auth mode + holder exists: full profile */}
          {isAuthMode && holderId !== null && (
            <>
              {employeeQuery.isLoading && (
                <div className="text-sm text-muted-foreground">{t('hr.drawer.loading')}</div>
              )}
              {employee && (
                <div className="space-y-3 border-t pt-4">
                  <Field icon={Mail} label="Email" value={
                    employee.email
                      ? <a className="underline-offset-2 hover:underline" href={`mailto:${employee.email}`}>{employee.email}</a>
                      : null
                  } />
                  <Field icon={Phone} label={t('profile.phone')} value={
                    employee.phone
                      ? <a className="underline-offset-2 hover:underline" href={`tel:${employee.phone}`}>{employee.phone}</a>
                      : null
                  } />
                  <Field icon={Calendar} label={t('hr.card.hireDate')} value={fmtDate(employee.hire_date)} />
                  {employee.bio && (
                    <div className="rounded-md bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
                      {employee.bio}
                    </div>
                  )}
                </div>
              )}

              {pmos.length > 0 && (
                <div className="space-y-2 border-t pt-4">
                  <div className="flex items-center justify-between">
                    <h4 className="text-sm font-semibold">{t('hr.drawer.pmoProjects')}</h4>
                    <span className={`text-xs ${totalAllocation > 100 ? 'text-destructive font-medium' : 'text-muted-foreground'}`}>
                      {t('profile.pmoAllocation', { percent: totalAllocation })}
                    </span>
                  </div>
                  {totalAllocation > 100 && (
                    <p className="text-xs text-destructive">
                      {t('hr.drawer.overAllocated')}
                    </p>
                  )}
                  <ul className="space-y-1.5">
                    {pmos.map((p) => (
                      <li key={p.pmo_id} className="flex items-center justify-between rounded-md border px-2.5 py-1.5 text-xs">
                        <div className="min-w-0">
                          <div className="flex items-center gap-1.5 font-medium">
                            <span className="truncate">{p.pmo_name}</span>
                            {p.is_primary && <Badge variant="default" className="h-4 text-[10px]">{t('profile.pmoLead')}</Badge>}
                          </div>
                          {p.position_in_pmo && (
                            <div className="text-muted-foreground truncate">{p.position_in_pmo}</div>
                          )}
                        </div>
                        <span className="ml-2 flex-shrink-0 font-mono text-muted-foreground">{p.allocation_percent}%</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {!employeeQuery.isLoading && !employee && (
                <div className="text-xs italic text-muted-foreground">
                  {t('hr.drawer.notFound')}
                </div>
              )}
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
