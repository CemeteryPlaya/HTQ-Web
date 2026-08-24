/** Employee picker — "Добавить" → choose a department → choose an employee.
 *  Returns platform user ids. Reusable across the builder wherever people are
 *  selected (submitters, approvers, CC, process admins). `multiple` toggles
 *  single vs many; `max` caps the count (e.g. process admins ≤ 5). */

import { useQuery } from '@tanstack/react-query';
import { Plus, Search, X } from 'lucide-react';
import { useMemo, useState } from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';

import { fetchDepartments, fetchEmployees } from '@/api/hr';
import { useTranslation } from 'react-i18next';

interface Props {
  value: number[];
  onChange: (ids: number[]) => void;
  multiple?: boolean;
  max?: number;
  addLabel?: string;
}

export function EmployeePicker({ value, onChange, multiple = true, max, addLabel }: Props) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [dept, setDept] = useState<string>('');
  const [search, setSearch] = useState('');

  const departments = useQuery({ queryKey: ['hr', 'departments'], queryFn: fetchDepartments });
  const employees = useQuery({ queryKey: ['hr', 'employees', 'picker'], queryFn: () => fetchEmployees() });

  const nameById = useMemo(() => {
    const m = new Map<number, string>();
    for (const e of employees.data ?? []) {
      if (e.user_id != null) m.set(e.user_id, e.full_name || `ID ${e.user_id}`);
    }
    return m;
  }, [employees.data]);

  const list = useMemo(() => {
    if (!dept) return [];
    const q = search.trim().toLowerCase();
    return (employees.data ?? []).filter((e) =>
      e.user_id != null
      && String(e.department_id) === dept
      && (!q || (e.full_name ?? '').toLowerCase().includes(q)),
    );
  }, [employees.data, dept, search]);

  const atMax = Boolean(max && value.length >= max);
  const canAdd = multiple ? !atMax : value.length === 0;

  function add(uid: number) {
    if (value.includes(uid)) return;
    if (!multiple) { onChange([uid]); setOpen(false); return; }
    if (max && value.length >= max) {
      toast.error(t('requests.employeePicker.maxReached', { max }));
      return;
    }
    onChange([...value, uid]);
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        {value.map((uid) => (
          <span key={uid} className="inline-flex items-center gap-1 rounded-full border bg-muted/40 px-2.5 py-1 text-xs">
            {nameById.get(uid) ?? `ID ${uid}`}
            <button type="button" onClick={() => onChange(value.filter((x) => x !== uid))} aria-label={t('requests.employeePicker.remove')}>
              <X className="h-3 w-3 text-muted-foreground hover:text-destructive" />
            </button>
          </span>
        ))}
        {canAdd && (
          <Button type="button" variant="outline" size="sm" onClick={() => setOpen(true)}>
            <Plus className="mr-1 h-3.5 w-3.5" /> {addLabel ?? t('common.add')}
          </Button>
        )}
        {max && <span className="text-xs text-muted-foreground">{value.length}/{max}</span>}
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader><DialogTitle>{t('requests.employeePicker.title')}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1.5">
              <Label className="text-xs">{t('requests.employeePicker.department')}</Label>
              <Select value={dept} onValueChange={(v) => { setDept(v); setSearch(''); }}>
                <SelectTrigger><SelectValue placeholder={t('requests.employeePicker.pickDepartment')} /></SelectTrigger>
                <SelectContent>
                  {departments.data?.map((d) => (
                    <SelectItem key={d.id} value={String(d.id)}>{d.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {dept && (
              <>
                <div className="relative">
                  <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder={t('requests.employeePicker.searchPlaceholder')} className="pl-9" />
                </div>
                <div className="max-h-64 overflow-y-auto rounded-md border">
                  {employees.isLoading && <div className="p-3 text-sm text-muted-foreground">{t('signoff.loadingEllipsis')}</div>}
                  {!employees.isLoading && list.length === 0 && (
                    <div className="p-3 text-sm text-muted-foreground">{t('requests.employeePicker.noAccounts')}</div>
                  )}
                  {list.map((e) => {
                    const picked = e.user_id != null && value.includes(e.user_id);
                    return (
                      <button
                        key={e.id}
                        type="button"
                        disabled={picked}
                        onClick={() => e.user_id != null && add(e.user_id)}
                        className={`flex w-full items-center justify-between border-b px-3 py-2 text-left text-sm last:border-b-0 ${picked ? 'opacity-50' : 'hover:bg-muted/40'}`}
                      >
                        <span>
                          <span className="block font-medium">{e.full_name}</span>
                          {e.position_title && <span className="block text-xs text-muted-foreground">{e.position_title}</span>}
                        </span>
                        {picked && <span className="text-xs text-muted-foreground">{t('requests.employeePicker.selected')}</span>}
                      </button>
                    );
                  })}
                </div>
                {multiple && (
                  <div className="flex justify-end">
                    <Button type="button" size="sm" onClick={() => setOpen(false)}>{t('common.done')}</Button>
                  </div>
                )}
              </>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
