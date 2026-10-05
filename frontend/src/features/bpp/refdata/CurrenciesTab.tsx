/**
 * «Валюты и курсы» (ТЗ §18): справочник валют (архивируемый) плюс курсы к
 * KZT на дату.
 *
 * Курсы грузит Celery-beat из НБРК каждый день (`refdata.load_nbrk_rates`);
 * у курса нет правки и архива (`apps/refdata/urls.py`). ФД добавляет только
 * РУЧНОЙ курс на дату, которой нет в загрузке, — отсюда и название кнопки;
 * загрузка ручной курс не перезаписывает. Курс на уже занятую дату сервер
 * отвергнет (уникальность «валюта + дата»).
 */
import { useMemo, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import { Badge } from '@/components/ui/badge';
import { DateInput } from '@/components/ui/date-input';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { TableCell, TableRow } from '@/components/ui/table';
import { reportApiError } from '@/lib/apiError';

import { formatDate } from '../format';
import { refdataApi, refdataKeys, type Currency } from './api';
import { ArchivableTable } from './ArchivableTable';
import { formatDecimal, isPositiveDecimal, parseDecimalInput } from './decimal';
import { PeriodicSection } from './PeriodicSection';
import type { RefField } from './refFields';
import { useActiveRefdata, useRefdataList } from './useRefdataList';

/** Знаков после запятой у курса — `Decimal(18,6)` на сервере. */
const RATE_PLACES = 6;
/** Сколько последних курсов показывать: загрузка НБРК добавляет строки
 * каждый день по каждой валюте, и за год их тысячи. */
const RATES_SHOWN = 100;
const ALL = '__all__';
const BASE_CURRENCY = 'KZT';

function RatesPanel({ currenciesCanEdit }: { currenciesCanEdit: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { data: currencies } = useActiveRefdata('currencies');
  const { data: rates, isLoading } = useRefdataList('rates');

  const [filter, setFilter] = useState(ALL);
  const [open, setOpen] = useState(false);
  const [currencyCode, setCurrencyCode] = useState('');
  const [onDate, setOnDate] = useState('');
  const [rateText, setRateText] = useState('');

  const rate = parseDecimalInput(rateText, RATE_PLACES);
  const rateValid = rate !== null && isPositiveDecimal(rate);
  const formReady = Boolean(currencyCode && onDate && rateValid);
  // Пустой список курсов (загрузки ещё не было) не должен запирать ввод:
  // признак тот же на всех справочниках запроса, берём его и у валют.
  const canEdit = currenciesCanEdit || (rates ?? []).some((row) => row.can_edit);

  const foreign = (currencies ?? []).filter((c) => c.code !== BASE_CURRENCY);
  const filtered = useMemo(
    () => (rates ?? []).filter((row) => filter === ALL || row.currency_code === filter),
    [rates, filter],
  );
  const shown = filtered.slice(0, RATES_SHOWN);

  const openChange = (next: boolean) => {
    if (next) {
      setCurrencyCode(filter === ALL ? '' : filter);
      setOnDate('');
      setRateText('');
    }
    setOpen(next);
  };

  const submit = async () => {
    try {
      await refdataApi.rates.create({ currency_code: currencyCode, on_date: onDate, rate: rate! });
      await queryClient.invalidateQueries({ queryKey: refdataKeys.collection('rates') });
    } catch (error) {
      reportApiError(error, t('bpp.refdata.createFailed', 'Не удалось добавить запись'));
      throw error;
    }
  };

  return (
    <PeriodicSection
      title={t('bpp.refdata.rates.title', 'Курсы валют к KZT')}
      addLabel={t('bpp.refdata.rates.addManual', 'Добавить ручной курс')}
      canEdit={canEdit}
      isLoading={isLoading}
      columns={[
        t('bpp.refdata.rates.currency', 'Валюта'),
        t('bpp.refdata.rates.date', 'Дата'),
        t('bpp.refdata.rates.rate', 'Курс'),
        t('bpp.refdata.rates.source', 'Источник'),
      ]}
      rows={shown.map((row) => (
        <TableRow key={row.id}>
          <TableCell>{row.currency_code}</TableCell>
          <TableCell>{formatDate(row.on_date)}</TableCell>
          <TableCell className="tabular-nums">{formatDecimal(row.rate)}</TableCell>
          <TableCell>
            {row.source === 'manual' ? (
              <Badge variant="outline">{t('bpp.refdata.rates.manual', 'Вручную')}</Badge>
            ) : (
              <Badge variant="secondary">{t('bpp.refdata.rates.nbrk', 'НБРК')}</Badge>
            )}
          </TableCell>
        </TableRow>
      ))}
      toolbarExtra={(
        <Select value={filter} onValueChange={setFilter}>
          <SelectTrigger
            className="h-9 w-36"
            aria-label={t('bpp.refdata.rates.filter', 'Фильтр по валюте')}
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>{t('bpp.refdata.rates.allCurrencies', 'Все валюты')}</SelectItem>
            {foreign.map((c) => <SelectItem key={c.id} value={c.code}>{c.code}</SelectItem>)}
          </SelectContent>
        </Select>
      )}
      footer={filtered.length > RATES_SHOWN ? (
        <p className="text-xs text-muted-foreground">
          {t('bpp.refdata.rates.shownLast', 'Показаны последние {{count}} из {{total}}', {
            count: RATES_SHOWN, total: filtered.length,
          })}
        </p>
      ) : null}
      open={open}
      onOpenChange={openChange}
      formReady={formReady}
      onSubmit={submit}
      form={(
        <>
          <div className="space-y-1.5">
            <Label htmlFor="rate-currency">{t('bpp.refdata.rates.currency', 'Валюта')}</Label>
            <Select value={currencyCode || undefined} onValueChange={setCurrencyCode}>
              <SelectTrigger id="rate-currency">
                <SelectValue placeholder={t('bpp.refdata.choose', 'Выберите')} />
              </SelectTrigger>
              <SelectContent>
                {foreign.map((c) => (
                  <SelectItem key={c.id} value={c.code}>{c.code} — {c.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="rate-date">{t('bpp.refdata.rates.date', 'Дата')}</Label>
            <DateInput id="rate-date" value={onDate} onChange={setOnDate} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="rate-value">{t('bpp.refdata.rates.rateToKzt', 'Курс, KZT за единицу')}</Label>
            <Input
              id="rate-value"
              inputMode="decimal"
              value={rateText}
              onChange={(event) => setRateText(event.target.value)}
              placeholder="475,12"
              aria-invalid={rateText !== '' && !rateValid}
            />
            {rateText !== '' && !rateValid && (
              <p className="text-xs text-destructive">
                {t('bpp.refdata.rates.invalid', 'Введите курс больше нуля, не более 6 знаков после запятой')}
              </p>
            )}
          </div>
        </>
      )}
    />
  );
}

export default function CurrenciesTab() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { data, isLoading } = useRefdataList('currencies');
  const canEdit = (data ?? []).some((row) => row.can_edit);

  const fields: RefField<Currency>[] = [
    { key: 'code', label: t('bpp.refdata.currencies.code', 'Код'), editable: false, maxLength: 3 },
    { key: 'name', label: t('bpp.refdata.currencies.name', 'Наименование'), maxLength: 64 },
    {
      key: 'symbol', label: t('bpp.refdata.currencies.symbol', 'Символ'), maxLength: 8,
      optional: true,
    },
  ];

  return (
    <div className="space-y-8">
      <ArchivableTable
        title={t('bpp.refdata.currencies.title', 'Валюты')}
        rows={data}
        isLoading={isLoading}
        fields={fields}
        onCreate={(values) => refdataApi.currencies.create({
          code: values.code.trim().toUpperCase(), name: values.name.trim(),
          symbol: (values.symbol ?? '').trim(),
        })}
        onPatch={(id, values) => refdataApi.currencies.patch(id, {
          name: values.name.trim(), symbol: (values.symbol ?? '').trim(),
        })}
        onToggleActive={(row, is_active) => refdataApi.currencies.patch(row.id, { is_active })}
        onChanged={() => queryClient.invalidateQueries({ queryKey: refdataKeys.collection('currencies') })}
      />
      <RatesPanel currenciesCanEdit={canEdit} />
    </div>
  );
}
