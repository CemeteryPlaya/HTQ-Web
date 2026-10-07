/**
 * Выбор желаемой схемы оплаты тендера (шаблоны 1–3, план §4.1): радио
 * вида и поле параметра у аванса (процент) и постоплаты (дни).
 */
import { useTranslation } from 'react-i18next';

import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';

import type { SchemeKind } from './api';
import type { SchemeDraft } from './schemes';

interface Props {
  value: SchemeDraft;
  onChange: (value: SchemeDraft) => void;
  errors: Record<string, string>;
}

export function PaymentSchemeField({ value, onChange, errors }: Props) {
  const { t } = useTranslation();
  const options: [SchemeKind, string, string][] = [
    ['prepay', t('tender.tenders.schemePrepay', '1 · Предоплата 100 %'),
      t('tender.tenders.schemePrepayHint', 'Вся сумма до отгрузки')],
    ['advance', t('tender.tenders.schemeAdvance', '2 · Аванс + остаток по приёмке'),
      t('tender.tenders.schemeAdvanceHint', 'Часть до отгрузки, остальное после приёмки')],
    ['postpay', t('tender.tenders.schemePostpay', '3 · Постоплата'),
      t('tender.tenders.schemePostpayHint', 'Вся сумма через N дней после приёмки')],
  ];

  return (
    <div className="space-y-3">
      <RadioGroup
        value={value.kind}
        onValueChange={(kind) => onChange({ ...value, kind: kind as SchemeKind })}
        className="grid gap-2"
      >
        {options.map(([kind, label, hint]) => (
          <label key={kind} className="flex items-start gap-2 text-sm">
            <RadioGroupItem value={kind} className="mt-0.5" />
            <span>
              <span className="font-medium">{label}</span>
              <span className="block text-xs text-muted-foreground">{hint}</span>
            </span>
          </label>
        ))}
      </RadioGroup>
      {errors.kind && <p className="text-xs text-destructive">{errors.kind}</p>}

      {value.kind === 'advance' && (
        <div className="max-w-40 space-y-1.5">
          <Label htmlFor="tender-scheme-advance">{t('tender.tenders.advancePct', 'Аванс, %')}</Label>
          <Input
            id="tender-scheme-advance" inputMode="decimal" value={value.advance_pct}
            aria-invalid={errors.advance_pct ? true : undefined}
            onChange={(event) => onChange({ ...value, advance_pct: event.target.value })}
          />
          {errors.advance_pct && <p className="text-xs text-destructive">{errors.advance_pct}</p>}
        </div>
      )}
      {value.kind === 'postpay' && (
        <div className="max-w-40 space-y-1.5">
          <Label htmlFor="tender-scheme-days">{t('tender.tenders.postpayDays', 'Отсрочка, дней')}</Label>
          <Input
            id="tender-scheme-days" inputMode="numeric" value={value.postpay_days}
            aria-invalid={errors.postpay_days ? true : undefined}
            onChange={(event) => onChange({ ...value, postpay_days: event.target.value })}
          />
          {errors.postpay_days && <p className="text-xs text-destructive">{errors.postpay_days}</p>}
        </div>
      )}
    </div>
  );
}
