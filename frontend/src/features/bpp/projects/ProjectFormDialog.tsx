/**
 * Создание и правка проекта (D-02). Право — узел `project.projects`
 * (`create`/`edit`: директора, ФД, АДМ); экран открывает диалог только с
 * правом, отказ сервера (403 E-ACC-01, повтор кода 422 E-PRJ-01) — тостом.
 *
 * При правке код, вид и страна не меняются (сервер их не принимает):
 * бюджет ведётся в стране проекта (Q-B08), и смена страны задним числом
 * перекроила бы уже утверждённые лимиты. Название, статус, сроки и
 * руководитель правятся только здесь: доска задач проекта их повторяет, и
 * правку, которую доска принять не может (имя занято другой доской), сервер
 * отклоняет целиком — 409 E-PRJ-04, текст тостом.
 */
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';

import { EmployeePicker } from '@/components/common/EmployeePicker';
import { Button } from '@/components/ui/button';
import { DateInput } from '@/components/ui/date-input';
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { reportApiError } from '@/lib/apiError';

import { COUNTRIES_KEY, counterpartyApi } from '../counterparties/api';
import { CounterpartyPicker } from '../counterparties/CounterpartyPicker';

import {
  projectApi, type Project, type ProjectCreate, type ProjectKind, type ProjectStatus,
} from './api';
import { KIND_LABELS, STATUS_LABELS } from './labels';

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Проект при правке; без него — создание. */
  project?: Project;
  onSaved: (project: Project) => void;
}

const EMPTY: ProjectCreate = {
  code: '',
  name: '',
  kind: 'project',
  country_code: 'KZ',
  manager_user_id: null,
  customer_name: '',
  customer_counterparty_id: '',
  date_start: null,
  date_end: null,
};

export function ProjectFormDialog({ open, onOpenChange, project, onSaved }: Props) {
  const { t } = useTranslation();
  const [values, setValues] = useState<ProjectCreate>(EMPTY);
  const [status, setStatus] = useState<ProjectStatus>('active');
  const [errors, setErrors] = useState<Partial<Record<keyof ProjectCreate, string>>>({});
  const [saving, setSaving] = useState(false);
  // Замок в ref: два клика в одном такте оба увидели бы `saving === false`.
  const inFlight = useRef(false);

  const countries = useQuery({
    queryKey: COUNTRIES_KEY,
    queryFn: counterpartyApi.countries,
    staleTime: 10 * 60 * 1000,
    enabled: open && !project,
  });

  useEffect(() => {
    if (!open) return;
    setErrors({});
    setValues(project ? {
      ...EMPTY,
      code: project.code,
      name: project.name,
      kind: project.kind,
      country_code: project.country_code,
      manager_user_id: project.manager_user_id,
      customer_name: project.customer_name,
      customer_counterparty_id: project.customer_counterparty_id ?? '',
      date_start: project.date_start ?? null,
      date_end: project.date_end ?? null,
    } : EMPTY);
    setStatus(project?.status ?? 'active');
  }, [open, project]);

  const set = <K extends keyof ProjectCreate>(key: K, value: ProjectCreate[K]) => {
    setValues((current) => ({ ...current, [key]: value }));
    setErrors((current) => ({ ...current, [key]: undefined }));
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (inFlight.current) return;
    const found: typeof errors = {};
    if (!project && !values.code.trim()) found.code = t('bpp.projects.codeRequired', 'Укажите код проекта');
    if (!values.name.trim()) found.name = t('bpp.projects.nameRequired', 'Укажите наименование проекта');
    if (values.date_start && values.date_end && values.date_end < values.date_start) {
      found.date_end = t('bpp.projects.datesOrder', 'Окончание не может быть раньше начала');
    }
    if (Object.keys(found).length > 0) {
      setErrors(found);
      return;
    }
    inFlight.current = true;
    setSaving(true);
    try {
      const saved = project
        ? await projectApi.update(project.id, {
          name: values.name.trim(),
          status,
          manager_user_id: values.manager_user_id,
          customer_name: values.customer_name.trim(),
          customer_counterparty_id: values.customer_counterparty_id,
          date_start: values.date_start,
          date_end: values.date_end,
        })
        : await projectApi.create({
          ...values,
          code: values.code.trim(),
          name: values.name.trim(),
          customer_name: values.customer_name.trim(),
        });
      onSaved(saved);
      onOpenChange(false);
    } catch (error) {
      reportApiError(error, t('bpp.projects.saveFailed', 'Не удалось сохранить проект'));
    } finally {
      inFlight.current = false;
      setSaving(false);
    }
  };

  const errorOf = (key: keyof ProjectCreate) =>
    errors[key] ? <p className="text-xs text-destructive">{errors[key]}</p> : null;

  return (
    <Dialog open={open} onOpenChange={(next) => { if (!saving) onOpenChange(next); }}>
      <DialogContent className="sm:max-w-xl" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>
            {project
              ? t('bpp.projects.editTitle', 'Изменить проект')
              : t('bpp.projects.createTitle', 'Новый проект')}
          </DialogTitle>
        </DialogHeader>
        <form id="bpp-project-form" onSubmit={submit} noValidate className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="prj-code">{t('bpp.projects.code', 'Код')}</Label>
            <Input
              id="prj-code"
              value={values.code}
              onChange={(event) => set('code', event.target.value)}
              disabled={Boolean(project) || saving}
              className="font-mono"
            />
            {errorOf('code')}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="prj-kind">{t('bpp.projects.kindTitle', 'Вид')}</Label>
            <Select
              value={values.kind}
              onValueChange={(value) => set('kind', value as ProjectKind)}
              disabled={Boolean(project) || saving}
            >
              <SelectTrigger id="prj-kind"><SelectValue /></SelectTrigger>
              <SelectContent>
                {(Object.entries(KIND_LABELS) as [ProjectKind, [string, string]][]).map(([kind, [key, label]]) => (
                  <SelectItem key={kind} value={kind}>{t(key, label)}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5 sm:col-span-2">
            <Label htmlFor="prj-name">{t('bpp.projects.name', 'Наименование')}</Label>
            <Input
              id="prj-name"
              value={values.name}
              onChange={(event) => set('name', event.target.value)}
              disabled={saving}
            />
            {errorOf('name')}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="prj-country">{t('bpp.projects.country', 'Страна')}</Label>
            {project ? (
              <Input id="prj-country" value={values.country_code} disabled />
            ) : (
              <Select
                value={values.country_code}
                onValueChange={(value) => set('country_code', value)}
                disabled={saving}
              >
                <SelectTrigger id="prj-country"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {(countries.data ?? []).map((country) => (
                    <SelectItem key={country.code} value={country.code}>
                      {country.code} — {country.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </div>
          {project && (
            <div className="space-y-1.5">
              <Label htmlFor="prj-status">{t('bpp.projects.statusTitle', 'Статус')}</Label>
              <Select value={status} onValueChange={(value) => setStatus(value as ProjectStatus)} disabled={saving}>
                <SelectTrigger id="prj-status"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {(Object.entries(STATUS_LABELS) as [ProjectStatus, [string, string, string]][]).map(([code, [key, label]]) => (
                    <SelectItem key={code} value={code}>{t(key, label)}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
          <div className="space-y-1.5 sm:col-span-2">
            <Label>{t('bpp.projects.manager', 'Руководитель проекта')}</Label>
            <EmployeePicker
              value={values.manager_user_id ? [values.manager_user_id] : []}
              onChange={(ids) => set('manager_user_id', ids[0] ?? null)}
              multiple={false}
              addLabel={t('bpp.projects.pickManager', 'Выбрать')}
            />
          </div>
          <div className="space-y-1.5 sm:col-span-2">
            <Label htmlFor="prj-customer">{t('bpp.projects.customer', 'Заказчик')}</Label>
            <Input
              id="prj-customer"
              value={values.customer_name}
              onChange={(event) => set('customer_name', event.target.value)}
              disabled={saving}
            />
          </div>
          <div className="space-y-1.5 sm:col-span-2">
            <Label htmlFor="prj-customer-counterparty">
              {t('bpp.projects.customerCounterparty', 'Заказчик — контрагент')}
            </Label>
            <CounterpartyPicker
              id="prj-customer-counterparty"
              value={values.customer_counterparty_id || null}
              onChange={(id) => set('customer_counterparty_id', id ?? '')}
              disabled={saving}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="prj-start">{t('bpp.projects.dateStart', 'Начало')}</Label>
            <DateInput
              id="prj-start"
              value={values.date_start ?? ''}
              onChange={(value) => set('date_start', value || null)}
              disabled={saving}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="prj-end">{t('bpp.projects.dateEnd', 'Окончание')}</Label>
            <DateInput
              id="prj-end"
              value={values.date_end ?? ''}
              onChange={(value) => set('date_end', value || null)}
              disabled={saving}
            />
            {errorOf('date_end')}
          </div>
        </form>
        <DialogFooter>
          <Button type="button" variant="outline" disabled={saving} onClick={() => onOpenChange(false)}>
            {t('bpp.document.cancel', 'Отмена')}
          </Button>
          <Button type="submit" form="bpp-project-form" disabled={saving}>
            {saving && <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />}
            {project ? t('bpp.projects.save', 'Сохранить') : t('bpp.projects.createSubmit', 'Создать проект')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default ProjectFormDialog;
