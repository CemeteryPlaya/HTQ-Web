import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Loader2, UsersRound } from 'lucide-react';

import { bulkImportEmployees, fetchImportCandidates } from '@/api/hr';
import type { BulkImportResult, Department, Position } from '@/types/hr';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { errorDetail } from '@/lib/apiError';

/**
 * Массовый импорт: карточки сотрудников из учёток, у которых их ещё нет.
 *
 * Отдел, должность и дата приёма — общие на всю пачку: это ровно те поля,
 * которых учётка не знает, и спрашивать их по одному на каждого означало бы
 * ту же форму N раз вместо импорта.
 *
 * Результат показывается как отчёт, а не как «готово»: пачка почти всегда
 * частично успешна (у кого-то занят email, кого-то успели завести), и
 * пропущенных нужно назвать поимённо с причиной — иначе человек не узнает,
 * кого именно не хватает.
 */

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  departments: Department[];
  positions: Position[];
}

const EmployeeBulkImportDialog = ({ open, onOpenChange, departments, positions }: Props) => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<number[]>([]);
  const [department, setDepartment] = useState('none');
  const [position, setPosition] = useState('none');
  const [hireDate, setHireDate] = useState('');
  const [result, setResult] = useState<BulkImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const { data: candidates = [], isFetching } = useQuery({
    queryKey: ['import-candidates'],
    queryFn: () => fetchImportCandidates(),
    enabled: open,
  });

  useEffect(() => {
    if (!open) {
      setSearch('');
      setSelected([]);
      setResult(null);
      setError(null);
    }
  }, [open]);

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return candidates;
    return candidates.filter((row) => (
      `${row.full_name} ${row.email}`.toLowerCase().includes(q)
    ));
  }, [candidates, search]);

  // Должности принадлежат отделу — предлагать чужие бессмысленно.
  const availablePositions = useMemo(() => {
    if (department === 'none') return positions;
    return positions.filter((p) => String(p.department ?? p.department_id) === department);
  }, [positions, department]);

  const importMutation = useMutation({
    mutationFn: () => bulkImportEmployees({
      user_ids: selected,
      department_id: Number(department),
      position_id: Number(position),
      hire_date: hireDate,
      status: 'active',
    }),
    onSuccess: (data) => {
      setResult(data);
      setSelected([]);
      queryClient.invalidateQueries({ queryKey: ['hr-employees'] });
      queryClient.invalidateQueries({ queryKey: ['import-candidates'] });
      queryClient.invalidateQueries({ queryKey: ['hr-employee-users'] });
    },
    onError: (err) => {
      setError(
        errorDetail(err)
        || t('hr.pages.employees.import.error', 'Не удалось выполнить импорт'),
      );
    },
  });

  const toggle = (id: number) => {
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };

  const allVisibleSelected = visible.length > 0 && visible.every((r) => selected.includes(r.id));
  const toggleAll = () => {
    setSelected(allVisibleSelected
      ? selected.filter((id) => !visible.some((r) => r.id === id))
      : [...new Set([...selected, ...visible.map((r) => r.id)])]);
  };

  const ready = selected.length > 0 && department !== 'none' && position !== 'none' && !!hireDate;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <UsersRound className="h-5 w-5" />
            {t('hr.pages.employees.import.title', 'Импорт из пользователей')}
          </DialogTitle>
          <DialogDescription>
            {t(
              'hr.pages.employees.import.description',
              'Показаны учётные записи, для которых карточки сотрудника ещё нет.',
            )}
          </DialogDescription>
        </DialogHeader>

        {result ? (
          <ImportReport result={result} onClose={() => setResult(null)} />
        ) : (
          <div className="grid gap-4">
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t('hr.pages.employees.import.search', 'Поиск по имени или почте')}
            />

            <div className="max-h-56 overflow-y-auto rounded-md border">
              {isFetching && (
                <p className="px-3 py-2 text-xs text-muted-foreground">
                  {t('hr.common.loading', 'Загрузка...')}
                </p>
              )}
              {!isFetching && visible.length === 0 && (
                <p className="px-3 py-2 text-sm text-muted-foreground">
                  {t('hr.pages.employees.import.empty', 'Все учётные записи уже связаны с карточками')}
                </p>
              )}
              {visible.length > 0 && (
                <label className="flex items-center gap-2 border-b px-3 py-2 text-xs text-muted-foreground">
                  <Checkbox checked={allVisibleSelected} onCheckedChange={toggleAll} />
                  {t('hr.pages.employees.import.selectAll', 'Выбрать всех')}
                </label>
              )}
              {visible.map((row) => (
                <label
                  key={row.id}
                  className="flex cursor-pointer items-center gap-2 px-3 py-2 text-sm hover:bg-muted"
                >
                  <Checkbox
                    checked={selected.includes(row.id)}
                    onCheckedChange={() => toggle(row.id)}
                  />
                  <span className="flex-1 truncate">{row.full_name || row.email}</span>
                  <span className="truncate text-xs text-muted-foreground">{row.email}</span>
                </label>
              ))}
            </div>

            <div className="grid gap-4 md:grid-cols-3">
              <label className="grid gap-2 text-sm">
                {t('hr.pages.employees.fields.department')}
                <Select
                  value={department}
                  onValueChange={(v) => { setDepartment(v); setPosition('none'); }}
                >
                  <SelectTrigger>
                    <SelectValue placeholder={t('hr.pages.employees.placeholders.selectDepartment')} />
                  </SelectTrigger>
                  <SelectContent>
                    {departments.map((d) => (
                      <SelectItem key={d.id} value={String(d.id)}>{d.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </label>

              <label className="grid gap-2 text-sm">
                {t('hr.pages.employees.fields.position')}
                <Select value={position} onValueChange={setPosition}>
                  <SelectTrigger>
                    <SelectValue placeholder={t('hr.pages.employees.placeholders.selectPosition')} />
                  </SelectTrigger>
                  <SelectContent>
                    {availablePositions.map((p) => (
                      <SelectItem key={p.id} value={String(p.id)}>{p.title}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </label>

              <label className="grid gap-2 text-sm">
                {t('hr.pages.employees.fields.dateHired')}
                <Input
                  type="date"
                  value={hireDate}
                  onChange={(e) => setHireDate(e.target.value)}
                />
              </label>
            </div>

            {error && <p className="text-sm text-destructive">{error}</p>}
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {result ? t('common.close', 'Закрыть') : t('common.cancel', 'Отмена')}
          </Button>
          {!result && (
            <Button
              onClick={() => { setError(null); importMutation.mutate(); }}
              disabled={!ready || importMutation.isPending}
            >
              {importMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {t('hr.pages.employees.import.submit', 'Создать карточки')}
              {selected.length > 0 && ` (${selected.length})`}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

/** Отчёт о пачке: сколько создано и — поимённо — кто пропущен и почему. */
const ImportReport = ({
  result, onClose,
}: {
  result: BulkImportResult;
  onClose: () => void;
}) => {
  const { t } = useTranslation();

  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge>
          {t('hr.pages.employees.import.created', 'Создано: {{count}}', {
            count: result.created_count,
          })}
        </Badge>
        {result.skipped_count > 0 && (
          <Badge variant="secondary">
            {t('hr.pages.employees.import.skipped', 'Пропущено: {{count}}', {
              count: result.skipped_count,
            })}
          </Badge>
        )}
      </div>

      {result.skipped.length > 0 && (
        <ul className="grid gap-1 rounded-md border px-3 py-2 text-sm">
          {result.skipped.map((row) => (
            <li key={row.user_id} className="flex items-center gap-2">
              <span className="text-muted-foreground">#{row.user_id}</span>
              <span>{t(`hr.pages.employees.import.reason.${row.reason}`, row.reason)}</span>
            </li>
          ))}
        </ul>
      )}

      <Button variant="ghost" size="sm" className="justify-self-start" onClick={onClose}>
        {t('hr.pages.employees.import.importMore', 'Импортировать ещё')}
      </Button>
    </div>
  );
};

export default EmployeeBulkImportDialog;
