import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { ArrowRight, Loader2, Mail, User, Users } from 'lucide-react';

import {
  applyPrefill, fetchEmployeeUsers, fetchEmployees, fetchMailboxSources, previewPrefill,
} from '@/api/hr';
import type {
  Employee, PrefillFieldDiff, PrefillPreview, PrefillSourceRef, PrefillSourceType,
} from '@/types/hr';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { errorDetail } from '@/lib/apiError';
import { cn } from '@/lib/utils';
import {
  PREFILL_FIELD_LABEL_KEYS, PREFILL_SOURCE_TYPES, defaultSelection, isSelectable, pickValues,
} from '@/components/hr/employeePrefill';
import { useDebounced } from '@/components/mail/mailboxLookup';

/**
 * «Подтянуть данные» — перенос уже имеющихся сведений в карточку сотрудника.
 *
 * Два шага в одном диалоге: выбрать источник (учётка, коллега, почтовый ящик)
 * и отметить, что именно перенести. Второй шаг существует ровно потому, что
 * молча перезаписывать заполненные поля нельзя: расхождения показываются как
 * «было → станет» и по умолчанию сняты.
 *
 * Диалог обслуживает оба режима формы:
 * - `employeeId` задан — применяет патч сам и отдаёт обновлённую карточку;
 * - `employeeId` пуст (создание) — ничего не сохраняет, а возвращает значения
 *   в форму, где человек ещё раз их увидит перед отправкой.
 */

const SOURCE_ICONS: Record<PrefillSourceType, typeof User> = {
  user: User,
  employee: Users,
  mailbox: Mail,
};

const MIN_SEARCH = 2;

interface SourceOption {
  id: number;
  title: string;
  subtitle: string;
  /** «Карточка у этого источника уже есть» — предупреждение, а не запрет. */
  taken?: boolean;
}

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Карточка, в которую переносим. `null` — форма создания. */
  employeeId?: number | null;
  /** Разрешено ли смотреть учётки и ящики (право hr.users.list). */
  canUseAccountSources?: boolean;
  /** Режим создания: значения возвращаются в форму. */
  onApplyToForm?: (values: Record<string, string | number>) => void;
  /** Режим редактирования: карточка уже сохранена сервером. */
  onApplied?: (employee: Employee) => void;
}

const EmployeePrefillDialog = ({
  open, onOpenChange, employeeId = null, canUseAccountSources = true,
  onApplyToForm, onApplied,
}: Props) => {
  const { t } = useTranslation();
  const [sourceType, setSourceType] = useState<PrefillSourceType>(
    canUseAccountSources ? 'user' : 'employee',
  );
  const [search, setSearch] = useState('');
  const [picked, setPicked] = useState<SourceRefWithTitle | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  const debouncedSearch = useDebounced(search, 400);

  // Смена вкладки сбрасывает выбор: «отмечено имя из учётки» не должно
  // пережить переключение на почтовый ящик.
  useEffect(() => {
    setPicked(null);
    setSelected([]);
    setError(null);
  }, [sourceType]);

  useEffect(() => {
    if (!open) {
      setSearch('');
      setPicked(null);
      setSelected([]);
      setError(null);
    }
  }, [open]);

  const searchReady = debouncedSearch.trim().length >= MIN_SEARCH;

  const { data: userOptions = [], isFetching: usersLoading } = useQuery({
    queryKey: ['prefill-users', debouncedSearch],
    queryFn: () => fetchEmployeeUsers({ search: debouncedSearch, limit: '20' }),
    enabled: open && sourceType === 'user' && canUseAccountSources && searchReady,
  });

  const { data: employeeOptions = [], isFetching: employeesLoading } = useQuery({
    queryKey: ['prefill-employees', debouncedSearch],
    queryFn: () => fetchEmployees({ search: debouncedSearch, limit: '20' }),
    enabled: open && sourceType === 'employee' && searchReady,
  });

  const { data: mailboxOptions = [], isFetching: mailboxesLoading } = useQuery({
    queryKey: ['prefill-mailboxes', debouncedSearch],
    queryFn: () => fetchMailboxSources({ search: debouncedSearch }),
    enabled: open && sourceType === 'mailbox' && canUseAccountSources && searchReady,
  });

  const options: SourceOption[] = useMemo(() => {
    if (sourceType === 'user') {
      return userOptions.map((u) => ({
        id: u.id,
        title: u.full_name || u.email,
        subtitle: u.email,
        taken: Boolean(u.employee_id) && u.employee_id !== employeeId,
      }));
    }
    if (sourceType === 'employee') {
      return employeeOptions
        .filter((e) => e.id !== employeeId)
        .map((e) => ({
          id: e.id,
          title: e.full_name || e.email,
          subtitle: [e.position_title, e.department_name].filter(Boolean).join(' · '),
        }));
    }
    return mailboxOptions.map((m) => ({
      id: m.id,
      title: m.address,
      subtitle: m.display_name || '',
    }));
  }, [sourceType, userOptions, employeeOptions, mailboxOptions, employeeId]);

  const optionsLoading = usersLoading || employeesLoading || mailboxesLoading;

  const source: PrefillSourceRef | null = picked
    ? { type: picked.type, id: picked.id }
    : null;

  const { data: preview, isFetching: previewLoading } = useQuery({
    queryKey: ['prefill-preview', picked?.type, picked?.id, employeeId],
    queryFn: () => previewPrefill(source as PrefillSourceRef, employeeId),
    enabled: open && source !== null,
  });

  // Умолчание выставляется один раз на загруженный предпросмотр: дальше
  // галочками распоряжается человек, и перерисовка не должна их возвращать.
  useEffect(() => {
    if (preview) setSelected(defaultSelection(preview.fields));
  }, [preview]);

  const applyMutation = useMutation({
    mutationFn: async () => {
      if (!source || !preview) throw new Error('no_source');
      if (employeeId) return applyPrefill(employeeId, source, selected);
      onApplyToForm?.(pickValues(preview, selected));
      return null;
    },
    onSuccess: (employee) => {
      if (employee) onApplied?.(employee);
      onOpenChange(false);
    },
    onError: (err) => {
      setError(
        errorDetail(err)
        || t('hr.pages.employees.prefill.applyError', 'Не удалось перенести данные'),
      );
    },
  });

  const toggle = (field: string) => {
    setSelected((prev) => (
      prev.includes(field) ? prev.filter((f) => f !== field) : [...prev, field]
    ));
  };

  // Без права hr.users.list остаётся единственный источник, не показывающий
  // чужие учётки, — соседняя карточка сотрудника.
  const availableTabs: PrefillSourceType[] = canUseAccountSources
    ? [...PREFILL_SOURCE_TYPES]
    : ['employee'];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {t('hr.pages.employees.prefill.title', 'Подтянуть данные')}
          </DialogTitle>
          <DialogDescription>
            {t(
              'hr.pages.employees.prefill.description',
              'Выберите, откуда взять сведения. Заполненные поля не изменятся, пока вы их не отметите.',
            )}
          </DialogDescription>
        </DialogHeader>

        <Tabs value={sourceType} onValueChange={(v) => setSourceType(v as PrefillSourceType)}>
          <TabsList>
            {availableTabs.map((type) => {
              const Icon = SOURCE_ICONS[type];
              return (
                <TabsTrigger key={type} value={type} className="gap-2">
                  <Icon className="h-4 w-4" />
                  {t(`hr.pages.employees.prefill.sources.${type}`)}
                </TabsTrigger>
              );
            })}
          </TabsList>

          {availableTabs.map((type) => (
            <TabsContent key={type} value={type} className="mt-4 grid gap-3">
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={t(
                  'hr.pages.employees.prefill.searchPlaceholder',
                  'Начните вводить (от 2 символов)',
                )}
              />

              {!searchReady && !picked && (
                <p className="text-xs text-muted-foreground">
                  {t('hr.pages.employees.prefill.searchHint', 'Введите минимум 2 символа')}
                </p>
              )}

              {searchReady && (
                <div className="max-h-44 overflow-y-auto rounded-md border">
                  {optionsLoading && (
                    <p className="px-3 py-2 text-xs text-muted-foreground">
                      {t('hr.common.loading', 'Загрузка...')}
                    </p>
                  )}
                  {!optionsLoading && options.length === 0 && (
                    <p className="px-3 py-2 text-xs text-muted-foreground">
                      {t('hr.pages.employees.prefill.nothingFound', 'Ничего не найдено')}
                    </p>
                  )}
                  {options.map((option) => (
                    <button
                      key={option.id}
                      type="button"
                      className={cn(
                        'flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-muted',
                        picked?.id === option.id && picked?.type === type && 'bg-muted',
                      )}
                      onClick={() => setPicked({ type, id: option.id, title: option.title })}
                    >
                      <span className="flex-1 truncate">{option.title}</span>
                      {option.subtitle && (
                        <span className="truncate text-xs text-muted-foreground">
                          {option.subtitle}
                        </span>
                      )}
                      {option.taken && (
                        <Badge variant="secondary" className="shrink-0 text-[10px]">
                          {t('hr.pages.employees.prefill.hasCard', 'уже есть карточка')}
                        </Badge>
                      )}
                    </button>
                  ))}
                </div>
              )}
            </TabsContent>
          ))}
        </Tabs>

        {previewLoading && (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            {t('hr.common.loading', 'Загрузка...')}
          </p>
        )}

        {preview && !previewLoading && (
          <PrefillPreviewTable
            preview={preview}
            selected={selected}
            onToggle={toggle}
          />
        )}

        {error && <p className="text-sm text-destructive">{error}</p>}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t('common.cancel', 'Отмена')}
          </Button>
          <Button
            onClick={() => { setError(null); applyMutation.mutate(); }}
            disabled={!preview || selected.length === 0 || applyMutation.isPending}
          >
            {applyMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {t('hr.pages.employees.prefill.apply', 'Перенести отмеченное')}
            {selected.length > 0 && ` (${selected.length})`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

interface SourceRefWithTitle extends PrefillSourceRef {
  title: string;
}

/** Таблица «было → станет». Вынесена, чтобы диалог читался целиком. */
const PrefillPreviewTable = ({
  preview, selected, onToggle,
}: {
  preview: PrefillPreview;
  selected: string[];
  onToggle: (field: string) => void;
}) => {
  const { t } = useTranslation();

  if (preview.fields.length === 0) {
    return (
      <p className="rounded-md border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
        {t('hr.pages.employees.prefill.nothingToTransfer', 'Этот источник не даёт данных для переноса')}
      </p>
    );
  }

  return (
    <div className="grid gap-2">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <span>
          {t('hr.pages.employees.prefill.fillableCount', 'Будет заполнено: {{count}}', {
            count: preview.fillable,
          })}
        </span>
        {preview.conflicts > 0 && (
          <Badge variant="destructive" className="text-[10px]">
            {t('hr.pages.employees.prefill.conflictsCount', 'Расхождений: {{count}}', {
              count: preview.conflicts,
            })}
          </Badge>
        )}
      </div>

      <div className="overflow-x-auto rounded-md border">
        <table className="w-full text-sm">
          <thead className="bg-muted/50 text-xs text-muted-foreground">
            <tr>
              <th className="w-10 px-2 py-2" />
              <th className="px-2 py-2 text-left font-medium">
                {t('hr.pages.employees.prefill.columnField', 'Поле')}
              </th>
              <th className="px-2 py-2 text-left font-medium">
                {t('hr.pages.employees.prefill.columnCurrent', 'Сейчас')}
              </th>
              <th className="px-2 py-2 text-left font-medium">
                {t('hr.pages.employees.prefill.columnIncoming', 'Станет')}
              </th>
            </tr>
          </thead>
          <tbody>
            {preview.fields.map((row) => (
              <PrefillRow
                key={row.field}
                row={row}
                checked={selected.includes(row.field)}
                onToggle={onToggle}
              />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

const PrefillRow = ({
  row, checked, onToggle,
}: {
  row: PrefillFieldDiff;
  checked: boolean;
  onToggle: (field: string) => void;
}) => {
  const { t } = useTranslation();
  const selectable = isSelectable(row);
  const labelKey = PREFILL_FIELD_LABEL_KEYS[row.field];

  return (
    <tr className={cn('border-t', row.state === 'same' && 'text-muted-foreground')}>
      <td className="px-2 py-2 align-top">
        <Checkbox
          checked={checked}
          disabled={!selectable}
          onCheckedChange={() => onToggle(row.field)}
          aria-label={labelKey ? t(labelKey) : row.field}
        />
      </td>
      <td className="px-2 py-2 align-top">
        <span className="font-medium">{labelKey ? t(labelKey) : row.field}</span>
        {row.state === 'conflict' && (
          <Badge variant="destructive" className="ml-2 text-[10px]">
            {t('hr.pages.employees.prefill.stateConflict', 'расхождение')}
          </Badge>
        )}
        {row.state === 'same' && (
          <Badge variant="secondary" className="ml-2 text-[10px]">
            {t('hr.pages.employees.prefill.stateSame', 'совпадает')}
          </Badge>
        )}
      </td>
      <td className="px-2 py-2 align-top break-all">
        {row.current_display || <span className="text-muted-foreground">—</span>}
      </td>
      <td className="px-2 py-2 align-top break-all">
        <span className="inline-flex items-start gap-1">
          <ArrowRight className="mt-1 h-3 w-3 shrink-0 text-muted-foreground" />
          {row.incoming_display || '—'}
        </span>
      </td>
    </tr>
  );
};

export default EmployeePrefillDialog;
