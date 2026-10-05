/**
 * «НДС и МРП» (ТЗ §18): ставки НДС по странам на период и МРП с даты.
 *
 * Документ берёт значение на свою дату (`refdata.interface.vat_rate`,
 * `mrp`; порог договора = 1000 × МРП), поэтому записи не правятся и не
 * архивируются: новое значение — новой записью с датой начала.
 */
import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import { DateInput } from '@/components/ui/date-input';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { TableCell, TableRow } from '@/components/ui/table';
import { reportApiError } from '@/lib/apiError';

import { formatDate, formatMoney, parseMoneyInput } from '../format';
import { refdataApi, refdataKeys } from './api';
import {
  formatDecimal, isPositiveDecimal, notAboveWhole, parseDecimalInput, thousandTimes,
} from './decimal';
import { PeriodicSection } from './PeriodicSection';
import { useActiveRefdata, useRefdataList } from './useRefdataList';

function VatPanel({ canEditFallback }: { canEditFallback: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { data: rows, isLoading } = useRefdataList('vat');
  const { data: allCountries } = useRefdataList('countries');
  const { data: countries } = useActiveRefdata('countries');

  const [open, setOpen] = useState(false);
  const [countryCode, setCountryCode] = useState('');
  const [rateText, setRateText] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');

  const rate = parseDecimalInput(rateText, 2);
  const rateValid = rate !== null && notAboveWhole(rate, 100);
  // ISO-даты сравниваются как строки.
  const periodValid = !dateTo || !dateFrom || dateTo >= dateFrom;
  const formReady = Boolean(countryCode && dateFrom && rateValid && periodValid);
  const canEdit = canEditFallback || (rows ?? []).some((row) => row.can_edit);

  const countryName = (code: string) =>
    (allCountries ?? []).find((c) => c.code === code)?.name ?? code;

  const openChange = (next: boolean) => {
    if (next) {
      setCountryCode('');
      setRateText('');
      setDateFrom('');
      setDateTo('');
    }
    setOpen(next);
  };

  const submit = async () => {
    try {
      await refdataApi.vat.create({
        country_code: countryCode, rate: rate!, date_from: dateFrom, date_to: dateTo || null,
      });
      await queryClient.invalidateQueries({ queryKey: refdataKeys.collection('vat') });
    } catch (error) {
      reportApiError(error, t('bpp.refdata.createFailed', 'Не удалось добавить запись'));
      throw error;
    }
  };

  return (
    <PeriodicSection
      title={t('bpp.refdata.vat.title', 'Ставки НДС')}
      addLabel={t('bpp.refdata.vat.add', 'Добавить ставку')}
      canEdit={canEdit}
      isLoading={isLoading}
      columns={[
        t('bpp.refdata.vat.country', 'Страна'),
        t('bpp.refdata.vat.rate', 'Ставка, %'),
        t('bpp.refdata.vat.dateFrom', 'Действует с'),
        t('bpp.refdata.vat.dateTo', 'Действует по'),
      ]}
      rows={(rows ?? []).map((row) => (
        <TableRow key={row.id}>
          <TableCell>{countryName(row.country_code)} ({row.country_code})</TableCell>
          <TableCell className="tabular-nums">{formatDecimal(row.rate)}</TableCell>
          <TableCell>{formatDate(row.date_from)}</TableCell>
          <TableCell>
            {row.date_to ? formatDate(row.date_to) : t('bpp.refdata.vat.open', 'бессрочно')}
          </TableCell>
        </TableRow>
      ))}
      open={open}
      onOpenChange={openChange}
      formReady={formReady}
      onSubmit={submit}
      form={(
        <>
          <div className="space-y-1.5">
            <Label htmlFor="vat-country">{t('bpp.refdata.vat.country', 'Страна')}</Label>
            <Select value={countryCode || undefined} onValueChange={setCountryCode}>
              <SelectTrigger id="vat-country">
                <SelectValue placeholder={t('bpp.refdata.choose', 'Выберите')} />
              </SelectTrigger>
              <SelectContent>
                {(countries ?? []).map((c) => (
                  <SelectItem key={c.id} value={c.code}>{c.name} ({c.code})</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="vat-rate">{t('bpp.refdata.vat.rate', 'Ставка, %')}</Label>
            <Input
              id="vat-rate"
              inputMode="decimal"
              value={rateText}
              onChange={(event) => setRateText(event.target.value)}
              placeholder="12"
              aria-invalid={rateText !== '' && !rateValid}
            />
            {rateText !== '' && !rateValid && (
              <p className="text-xs text-destructive">
                {t('bpp.refdata.vat.invalid', 'Ставка — от 0 до 100, не более 2 знаков после запятой')}
              </p>
            )}
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="vat-from">{t('bpp.refdata.vat.dateFrom', 'Действует с')}</Label>
              <DateInput id="vat-from" value={dateFrom} onChange={setDateFrom} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="vat-to">
                {t('bpp.refdata.vat.dateToOptional', 'Действует по (необязательно)')}
              </Label>
              <DateInput id="vat-to" value={dateTo} onChange={setDateTo} />
            </div>
          </div>
          {!periodValid && (
            <p className="text-xs text-destructive">
              {t('bpp.refdata.vat.badPeriod', 'Дата окончания раньше даты начала')}
            </p>
          )}
        </>
      )}
    />
  );
}

function MrpPanel({ canEditFallback }: { canEditFallback: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { data: rows, isLoading } = useRefdataList('mrp');

  const [open, setOpen] = useState(false);
  const [dateFrom, setDateFrom] = useState('');
  const [valueText, setValueText] = useState('');

  const value = parseMoneyInput(valueText);
  const valueValid = value !== null && isPositiveDecimal(value) && !value.startsWith('-');
  const formReady = Boolean(dateFrom && valueValid);
  const canEdit = canEditFallback || (rows ?? []).some((row) => row.can_edit);

  const openChange = (next: boolean) => {
    if (next) {
      setDateFrom('');
      setValueText('');
    }
    setOpen(next);
  };

  const submit = async () => {
    try {
      await refdataApi.mrp.create({ date_from: dateFrom, value: value! });
      await queryClient.invalidateQueries({ queryKey: refdataKeys.collection('mrp') });
    } catch (error) {
      reportApiError(error, t('bpp.refdata.createFailed', 'Не удалось добавить запись'));
      throw error;
    }
  };

  // Новые значения — сверху: действующее видно без прокрутки. Сервер отдаёт
  // по возрастанию даты, ISO-даты сортируются как строки.
  const ordered = [...(rows ?? [])].sort((a, b) => b.date_from.localeCompare(a.date_from));

  return (
    <PeriodicSection
      title={t('bpp.refdata.mrp.title', 'МРП')}
      addLabel={t('bpp.refdata.mrp.add', 'Добавить значение МРП')}
      canEdit={canEdit}
      isLoading={isLoading}
      columns={[
        t('bpp.refdata.mrp.dateFrom', 'Действует с'),
        t('bpp.refdata.mrp.value', 'Значение'),
        t('bpp.refdata.mrp.threshold', 'Порог договора (1000 МРП)'),
      ]}
      rows={ordered.map((row) => (
        <TableRow key={row.id}>
          <TableCell>{formatDate(row.date_from)}</TableCell>
          <TableCell className="tabular-nums">{formatMoney(row.value, 'KZT')}</TableCell>
          {/* ×1000 — сдвиг запятой на три знака в строке, без float. */}
          <TableCell className="tabular-nums">{formatMoney(thousandTimes(row.value), 'KZT')}</TableCell>
        </TableRow>
      ))}
      open={open}
      onOpenChange={openChange}
      formReady={formReady}
      onSubmit={submit}
      form={(
        <>
          <div className="space-y-1.5">
            <Label htmlFor="mrp-from">{t('bpp.refdata.mrp.dateFrom', 'Действует с')}</Label>
            <DateInput id="mrp-from" value={dateFrom} onChange={setDateFrom} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="mrp-value">{t('bpp.refdata.mrp.valueKzt', 'Значение, KZT')}</Label>
            <Input
              id="mrp-value"
              inputMode="decimal"
              value={valueText}
              onChange={(event) => setValueText(event.target.value)}
              placeholder="4 325,00"
              aria-invalid={valueText !== '' && !valueValid}
            />
            {valueText !== '' && !valueValid && (
              <p className="text-xs text-destructive">
                {t('bpp.refdata.mrp.invalid', 'Введите сумму больше нуля в формате 4 325,00')}
              </p>
            )}
          </div>
        </>
      )}
    />
  );
}

export default function VatMrpTab() {
  // Признак «правит управляющая компания» один на все справочники запроса:
  // пустая таблица НДС или МРП не должна запирать первый ввод, поэтому
  // запасной источник признака — страны (их сидит миграция).
  const { data: countries } = useRefdataList('countries');
  const canEditFallback = (countries ?? []).some((row) => row.can_edit);
  return (
    <div className="space-y-8">
      <VatPanel canEditFallback={canEditFallback} />
      <MrpPanel canEditFallback={canEditFallback} />
    </div>
  );
}
