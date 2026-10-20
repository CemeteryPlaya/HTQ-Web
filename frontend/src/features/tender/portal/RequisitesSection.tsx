/**
 * Реквизиты поставщика в предложении: у известного контрагента БЗО их
 * подставляет сервер и править нельзя (только чтение); у потенциального —
 * поля формы.
 */
import { useTranslation } from 'react-i18next';

import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

import type { Requisites } from './types';

interface Props {
  value: Requisites;
  onChange: (value: Requisites) => void;
  readOnly: boolean;
  errors: Record<string, string>;
}

export function RequisitesSection({ value, onChange, readOnly, errors }: Props) {
  const { t } = useTranslation();
  const fields: [keyof Requisites, string, string][] = [
    ['name', t('tender.portal.reqName', 'Наименование организации'), 'organization'],
    ['country_code', t('tender.portal.reqCountry', 'Страна (код)'), 'country'],
    ['reg_number', t('tender.portal.reqRegNumber', 'БИН/ИИН или рег. номер'), 'off'],
    ['contact_name', t('tender.portal.reqContact', 'Контактное лицо'), 'name'],
    ['phone', t('tender.portal.reqPhone', 'Телефон'), 'tel'],
    ['email', t('tender.portal.reqEmail', 'E-mail'), 'email'],
  ];

  return (
    <section className="space-y-3 rounded-2xl border bg-card p-4">
      <h2 className="text-lg font-semibold">{t('tender.portal.requisites', 'Реквизиты поставщика')}</h2>
      {readOnly ? (
        <>
          <dl className="grid gap-2 text-sm">
            {fields.map(([key, label]) => (
              <div key={key}>
                <dt className="text-muted-foreground">{label}</dt>
                <dd>{String(value[key] || '—')}</dd>
              </div>
            ))}
            <div>
              <dt className="text-muted-foreground">{t('tender.portal.reqVat', 'Плательщик НДС')}</dt>
              <dd>{value.is_vat_payer ? t('tender.portal.yes', 'Да') : t('tender.portal.no', 'Нет')}</dd>
            </div>
          </dl>
          <p className="text-xs text-muted-foreground">
            {t('tender.portal.reqReadonly', 'Реквизиты взяты из карточки вашей организации у заказчика. Чтобы их изменить, обратитесь к закупщику.')}
          </p>
        </>
      ) : (
        <div className="grid gap-3">
          {fields.map(([key, label, autoComplete]) => (
            <div key={key} className="space-y-1.5">
              <Label htmlFor={`portal-req-${key}`}>{label}</Label>
              <Input
                id={`portal-req-${key}`} className="h-11 text-base" autoComplete={autoComplete}
                value={String(value[key] ?? '')}
                maxLength={key === 'country_code' ? 2 : 255}
                onChange={(event) => onChange({ ...value, [key]: event.target.value })}
              />
              {errors[`requisites.${key}`] && (
                <p className="text-xs text-destructive">{errors[`requisites.${key}`]}</p>
              )}
            </div>
          ))}
          <div className="flex items-center gap-2">
            <Checkbox
              id="portal-req-vat" checked={value.is_vat_payer}
              onCheckedChange={(checked) => onChange({ ...value, is_vat_payer: checked === true })}
            />
            <Label htmlFor="portal-req-vat" className="font-normal">{t('tender.portal.reqVat', 'Плательщик НДС')}</Label>
          </div>
        </div>
      )}
    </section>
  );
}
