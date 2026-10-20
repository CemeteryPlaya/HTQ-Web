/**
 * Позиция тендера в предложении поставщика — карточкой, а не строкой
 * таблицы: на телефоне таблица из семи колонок нечитаема. Плановой цены
 * заказчика здесь нет (её нет и в ответе сервера).
 */
import { useTranslation } from 'react-i18next';

import { Checkbox } from '@/components/ui/checkbox';
import { DateInput } from '@/components/ui/date-input';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { formatDate, formatMoney } from '@/features/bpp/format';
import { lineAmount } from '@/features/bpp/requests/requestForm';

import { formatQty, type LineForm } from './offerForm';
import type { PortalItem } from './types';

interface Props {
  item: PortalItem;
  line: LineForm;
  onChange: (line: LineForm) => void;
  readOnly: boolean;
  allowAnalogs: boolean;
  currency: string;
  error?: string;
}

export function LineCard({ item, line, onChange, readOnly, allowAnalogs, currency, error }: Props) {
  const { t } = useTranslation();
  const uom = item.uom?.short_name ?? '';
  const id = `portal-line-${item.id}`;
  const amount = line.participates ? lineAmount(line.qty, line.price) : null;
  const set = (change: Partial<LineForm>) => onChange({ ...line, ...change });

  return (
    <article className="space-y-3 rounded-2xl border bg-card p-4" aria-labelledby={`${id}-title`}>
      <div>
        <h3 id={`${id}-title`} className="text-base font-semibold">
          <span className="text-muted-foreground">{item.line_no}. </span>{item.name}
        </h3>
        {item.specs && <p className="text-sm text-muted-foreground">{item.specs}</p>}
        <p className="text-sm">
          {t('tender.portal.requested', 'Нужно: {{qty}} {{uom}}', { qty: formatQty(item.qty), uom })}
          {item.need_date && ` · ${t('tender.portal.needBy', 'к {{date}}', { date: formatDate(item.need_date) })}`}
        </p>
      </div>

      {readOnly ? (
        <dl className="grid grid-cols-2 gap-2 text-sm">
          {line.participates ? (
            <>
              <div><dt className="text-muted-foreground">{t('tender.portal.price', 'Цена за единицу')}</dt><dd>{line.price || '—'}</dd></div>
              <div><dt className="text-muted-foreground">{t('tender.portal.qty', 'Количество')}</dt><dd>{line.qty || '—'}</dd></div>
              <div><dt className="text-muted-foreground">{t('tender.portal.deliveryDate', 'Срок поставки')}</dt><dd>{formatDate(line.delivery_date || null)}</dd></div>
              <div><dt className="text-muted-foreground">{t('tender.portal.lineAmount', 'Сумма')}</dt><dd>{amount ? formatMoney(amount, currency) : '—'}</dd></div>
              {line.is_analog && (
                <div className="col-span-2"><dt className="text-muted-foreground">{t('tender.portal.analog', 'Аналог')}</dt><dd>{line.analog_note}</dd></div>
              )}
            </>
          ) : (
            <p className="col-span-2 text-muted-foreground">{t('tender.portal.notParticipating', 'Не участвую')}</p>
          )}
        </dl>
      ) : (
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <Checkbox
              id={`${id}-part`} checked={line.participates}
              onCheckedChange={(value) => set({ participates: value === true })}
            />
            <Label htmlFor={`${id}-part`} className="text-base font-normal">
              {t('tender.portal.participates', 'Предлагаю эту позицию')}
            </Label>
          </div>
          {line.participates && (
            <>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label htmlFor={`${id}-price`}>{t('tender.portal.priceUnit', 'Цена за ед., {{currency}}', { currency })}</Label>
                  <Input
                    id={`${id}-price`} inputMode="decimal" className="h-11 text-base" value={line.price}
                    aria-label={t('tender.portal.priceFor', 'Цена за единицу: {{name}}', { name: item.name })}
                    onChange={(event) => set({ price: event.target.value })}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor={`${id}-qty`}>{t('tender.portal.qtyUnit', 'Кол-во, {{uom}}', { uom })}</Label>
                  <Input
                    id={`${id}-qty`} inputMode="decimal" className="h-11 text-base" value={line.qty}
                    aria-label={t('tender.portal.qtyFor', 'Количество: {{name}}', { name: item.name })}
                    onChange={(event) => set({ qty: event.target.value })}
                  />
                </div>
              </div>
              <div className="space-y-1.5">
                <Label>{t('tender.portal.deliveryDate', 'Срок поставки')}</Label>
                <DateInput
                  value={line.delivery_date}
                  aria-label={t('tender.portal.deliveryDateFor', 'Срок поставки: {{name}}', { name: item.name })}
                  onChange={(value) => set({ delivery_date: value })}
                />
              </div>
              {allowAnalogs && (
                <div className="space-y-2">
                  <div className="flex items-center gap-2">
                    <Checkbox
                      id={`${id}-analog`} checked={line.is_analog}
                      aria-label={t('tender.portal.analogFor', 'Предлагаю аналог: {{name}}', { name: item.name })}
                      onCheckedChange={(value) => set({ is_analog: value === true })}
                    />
                    <Label htmlFor={`${id}-analog`} className="font-normal">
                      {t('tender.portal.analogOffer', 'Предлагаю аналог')}
                    </Label>
                  </div>
                  {line.is_analog && (
                    <Textarea
                      value={line.analog_note} maxLength={2000} className="text-base"
                      aria-label={t('tender.portal.analogNote', 'Описание аналога')}
                      placeholder={t('tender.portal.analogHint', 'Марка, производитель, чем отличается')}
                      onChange={(event) => set({ analog_note: event.target.value })}
                    />
                  )}
                </div>
              )}
              <Input
                value={line.comment} maxLength={1000} className="h-11 text-base"
                aria-label={t('tender.portal.commentFor', 'Комментарий: {{name}}', { name: item.name })}
                placeholder={t('tender.portal.comment', 'Комментарий (необязательно)')}
                onChange={(event) => set({ comment: event.target.value })}
              />
              {amount && (
                <p className="text-sm text-muted-foreground">
                  {t('tender.portal.lineAmount', 'Сумма')}: {formatMoney(amount, currency)}
                </p>
              )}
            </>
          )}
        </div>
      )}
      {error && <p className="text-sm text-destructive">{error}</p>}
    </article>
  );
}
