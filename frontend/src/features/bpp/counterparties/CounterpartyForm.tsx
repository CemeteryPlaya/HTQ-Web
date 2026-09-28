/**
 * Форма карточки контрагента (ТЗ §18) — создание и правка.
 *
 * - **Рег. номер проверяется до запроса** тем же алгоритмом, что на сервере
 *   (`validation.ts`): БИН/ИИН с контрольным разрядом у казахстанского,
 *   свободный номер до 30 знаков у прочих. При правке — только если меняется
 *   тип, страна или номер: карточка, перенесённая со старым неверным номером,
 *   должна принимать правку телефона (так же решил сервер).
 * - **Дубль (страна, номер)** — E-CTR-02: сервер кладёт ключ существующего
 *   контрагента в `fields[0].existing_id`, форма даёт ссылку на его карточку
 *   вместо того, чтобы заводить второго.
 * - Прочие отказы с `fields` (E-CTR-03, E-REF-04, E-VAL-01) — у своих полей,
 *   текст сервера — над кнопками.
 * - Кнопка «Сохранить» защищена от двойного нажатия (`useIdempotentAction`),
 *   правка шлёт только изменённые поля и `version` (устарела — 409 E-CON-01).
 * - Уход с несохранёнными изменениями — диалог `useUnsavedChangesGuard`;
 *   «Сохранить черновик» в нём сохраняет карточку: черновиков у справочника
 *   нет, а терять введённое при уходе нельзя.
 */
import {
  useMemo, useState, type ComponentProps, type FormEvent, type ReactNode,
} from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { AlertTriangle, Loader2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { errorCode, explainedDetail, reportApiError } from '@/lib/apiError';
import { cn } from '@/lib/utils';

import { useIdempotentAction } from '../core/useIdempotentAction';
import { useUnsavedChangesGuard } from '../core/useUnsavedChangesGuard';

import {
  COUNTRIES_KEY, counterpartyApi, counterpartyHref,
  type CounterpartyCard, type CounterpartyInput,
} from './api';
import { duplicateId, errorFields } from './errors';
import { KINDS, kindLabel, regNumberLabel } from './labels';
import { checkRegNumber, normalizeRegNumber } from './validation';

const EMPTY: CounterpartyInput = {
  name: '',
  short_name: '',
  kind: 'legal',
  country_code: 'KZ',
  reg_number: '',
  is_vat_payer: false,
  vat_cert_series: '',
  vat_cert_number: '',
  legal_address: '',
  contact_person: '',
  phone: '',
  email: '',
};

const FIELDS = Object.keys(EMPTY) as (keyof CounterpartyInput)[];

const fromCard = (card: CounterpartyCard): CounterpartyInput =>
  Object.fromEntries(FIELDS.map((key) => [key, card[key]])) as unknown as CounterpartyInput;

type FieldErrors = Partial<Record<keyof CounterpartyInput, string>>;

interface Props {
  /** Карточка при правке; без неё — создание. */
  card?: CounterpartyCard;
  onSaved: (card: CounterpartyCard) => void;
  onCancel: () => void;
}

/** Не прошла проверка на фронте — запроса не было. */
class FormInvalid extends Error {}

export function CounterpartyForm({ card, onSaved, onCancel }: Props) {
  const { t } = useTranslation();
  const initial = useMemo(() => (card ? fromCard(card) : EMPTY), [card]);
  const [values, setValues] = useState<CounterpartyInput>(initial);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [serverText, setServerText] = useState<string | null>(null);
  const [duplicate, setDuplicate] = useState<string | null>(null);

  const countries = useQuery({
    queryKey: COUNTRIES_KEY,
    queryFn: counterpartyApi.countries,
    staleTime: 10 * 60 * 1000,
  });
  const countryOptions = useMemo(() => {
    const list = countries.data ?? [];
    // Страна карточки могла уйти в архив — она всё равно должна читаться.
    return list.some((c) => c.code === values.country_code) || !values.country_code
      ? list
      : [{ code: values.country_code, name: values.country_code }, ...list];
  }, [countries.data, values.country_code]);

  const changed = useMemo(
    () => FIELDS.filter((key) => values[key] !== initial[key]),
    [values, initial],
  );
  const dirty = changed.length > 0;

  const set = <K extends keyof CounterpartyInput>(key: K, value: CounterpartyInput[K]) => {
    setValues((current) => ({ ...current, [key]: value }));
    setErrors((current) => (current[key] ? { ...current, [key]: undefined } : current));
    if (key === 'reg_number' || key === 'country_code') setDuplicate(null);
  };

  /** Проверки до запроса; `null` — всё в порядке. */
  const validate = (): FieldErrors | null => {
    const found: FieldErrors = {};
    if (!values.name.trim()) {
      found.name = t('bpp.counterparties.nameRequired', 'Укажите наименование контрагента.');
    }
    const numberTouched = !card
      || values.kind !== card.kind
      || values.country_code !== card.country_code
      || normalizeRegNumber(values.reg_number) !== card.reg_number;
    if (numberTouched) {
      const result = checkRegNumber(values.kind, values.country_code, values.reg_number);
      if (!result.ok) found.reg_number = result.message;
    }
    return Object.keys(found).length > 0 ? found : null;
  };

  const action = useIdempotentAction((key) => {
    if (!card) return counterpartyApi.create(key, values);
    const patch: Partial<CounterpartyInput> = {};
    for (const field of changed) (patch as Record<string, unknown>)[field] = values[field];
    return counterpartyApi.update(card.id, key, { version: card.version, ...patch });
  });

  const save = async (): Promise<CounterpartyCard> => {
    setServerText(null);
    setDuplicate(null);
    const invalid = validate();
    if (invalid) {
      setErrors(invalid);
      throw new FormInvalid(t('bpp.counterparties.fixErrors', 'Исправьте ошибки в форме'));
    }
    try {
      const saved = await action.run();
      onSaved(saved);
      return saved;
    } catch (error) {
      const fields = errorFields(error);
      if (fields.length > 0) {
        setErrors(Object.fromEntries(fields.map((item) => [item.field, item.message])));
      }
      if (errorCode(error) === 'E-CTR-02') setDuplicate(duplicateId(error));
      const text = explainedDetail(error);
      if (errorCode(error) && text) setServerText(text);
      else reportApiError(error, t('bpp.counterparties.saveFailed', 'Не удалось сохранить контрагента'));
      throw error;
    }
  };

  const guard = useUnsavedChangesGuard({ dirty, onSaveDraft: save });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    save().catch(() => undefined); // причина уже у полей или в тосте
  };

  const field = (
    key: keyof CounterpartyInput,
    label: string,
    input: ReactNode,
    className?: string,
  ) => (
    <div className={cn('space-y-1.5', className)}>
      <Label htmlFor={`cp-${key}`}>{label}</Label>
      {input}
      {errors[key] && (
        <p id={`cp-${key}-error`} className="text-xs text-destructive">{errors[key]}</p>
      )}
    </div>
  );

  const text = (key: keyof CounterpartyInput, extra?: ComponentProps<typeof Input>) => (
    <Input
      id={`cp-${key}`}
      value={String(values[key] ?? '')}
      onChange={(event) => set(key, event.target.value as never)}
      aria-invalid={errors[key] ? true : undefined}
      aria-describedby={errors[key] ? `cp-${key}-error` : undefined}
      disabled={action.pending}
      {...extra}
    />
  );

  return (
    <form onSubmit={submit} className="space-y-5" noValidate>
      <div className="grid gap-4 sm:grid-cols-2">
        {field('kind', t('bpp.counterparties.kindTitle', 'Тип'), (
          <Select
            value={values.kind}
            onValueChange={(value) => set('kind', value as CounterpartyInput['kind'])}
            disabled={action.pending}
          >
            <SelectTrigger id="cp-kind"><SelectValue /></SelectTrigger>
            <SelectContent>
              {KINDS.map((kind) => (
                <SelectItem key={kind} value={kind}>{kindLabel(t, kind)}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        ))}
        {field('country_code', t('bpp.counterparties.country', 'Страна'), (
          <Select
            value={values.country_code}
            onValueChange={(value) => set('country_code', value)}
            disabled={action.pending}
          >
            <SelectTrigger id="cp-country_code"><SelectValue /></SelectTrigger>
            <SelectContent>
              {countryOptions.map((country) => (
                <SelectItem key={country.code} value={country.code}>
                  {country.code} — {country.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ))}
        {field('reg_number', regNumberLabel(t, values.country_code), text('reg_number', {
          className: 'font-mono',
          inputMode: values.country_code === 'KZ' ? 'numeric' : undefined,
          autoComplete: 'off',
        }))}
        {field('name', t('bpp.counterparties.name', 'Наименование'), text('name'))}
        {field('short_name', t('bpp.counterparties.shortName', 'Краткое наименование'), text('short_name'))}
        {field('email', t('bpp.counterparties.email', 'E-mail'), text('email', { type: 'email' }))}
        {field('contact_person', t('bpp.counterparties.contactPerson', 'Контактное лицо'), text('contact_person'))}
        {field('phone', t('bpp.counterparties.phone', 'Телефон'), text('phone', { type: 'tel' }))}
        {field('legal_address', t('bpp.counterparties.legalAddress', 'Юридический адрес'), (
          <Textarea
            id="cp-legal_address"
            value={values.legal_address}
            onChange={(event) => set('legal_address', event.target.value)}
            rows={2}
            disabled={action.pending}
          />
        ), 'sm:col-span-2')}
      </div>

      <div className="space-y-3 rounded-lg border p-3">
        <label className="flex items-center gap-2 text-sm font-medium">
          <Checkbox
            checked={values.is_vat_payer}
            onCheckedChange={(checked) => set('is_vat_payer', checked === true)}
            disabled={action.pending}
          />
          {t('bpp.counterparties.vatPayer', 'Плательщик НДС')}
        </label>
        {values.is_vat_payer && (
          <div className="grid gap-4 sm:grid-cols-2">
            {field('vat_cert_series', t('bpp.counterparties.vatSeries', 'Серия свидетельства НДС'), text('vat_cert_series'))}
            {field('vat_cert_number', t('bpp.counterparties.vatNumber', 'Номер свидетельства НДС'), text('vat_cert_number'))}
          </div>
        )}
      </div>

      {serverText && (
        <div role="alert" className="flex gap-2 rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-sm">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
          <div className="space-y-1">
            <p>{serverText}</p>
            {duplicate && (
              <Link to={counterpartyHref(duplicate)} className="font-medium text-primary underline underline-offset-2">
                {t('bpp.counterparties.openExisting', 'Открыть карточку существующего контрагента')}
              </Link>
            )}
          </div>
        </div>
      )}

      <div className="flex flex-wrap justify-end gap-2">
        <Button type="button" variant="outline" onClick={onCancel} disabled={action.pending}>
          {t('bpp.document.cancel', 'Отмена')}
        </Button>
        <Button type="submit" disabled={action.pending || (card !== undefined && !dirty)}>
          {action.pending && <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />}
          {card
            ? t('bpp.counterparties.save', 'Сохранить')
            : t('bpp.counterparties.createSubmit', 'Создать контрагента')}
        </Button>
      </div>

      {guard}
    </form>
  );
}

export default CounterpartyForm;
