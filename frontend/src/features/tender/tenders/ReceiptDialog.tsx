/**
 * «Отметить получение» по поставщику (TND-041; спека этапа 5, §3 T5.5).
 *
 * - Вид — «Товар получен» (позиции; доставка принимается вместе с товаром)
 *   или «Работы приняты» (СМР). Строки — только те, что ждут приёмки.
 * - Количество — не больше остатка (выбрано − уже принято): иначе ошибка у
 *   строки, и запрос не уходит; сервер проверяет то же (422 `E-TND-13`).
 * - Дата — не позже сегодняшней. Оригиналы можно отметить сразу или позже
 *   в списке приёмок. Сканы и фото прикладываются к сохранённой приёмке.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { DateInput } from '@/components/ui/date-input';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Textarea } from '@/components/ui/textarea';
import { useIdempotentAction } from '@/features/bpp/core/useIdempotentAction';
import { todayIso } from '@/lib/dates';

import { fieldErrorsOf } from '../core/fieldErrors';
import {
  remainingOf, type DeliveryAward, type DeliverySupplier, type ReceiptInput, type ReceiptKind,
} from './delivery';

interface Props {
  supplier: DeliverySupplier;
  onOpenChange: (open: boolean) => void;
  onSave: (key: string, body: ReceiptInput) => Promise<unknown>;
  onError: (error: unknown) => void;
}

const rowsOf = (supplier: DeliverySupplier, kind: ReceiptKind): DeliveryAward[] =>
  supplier.awards.filter((award) => award.needs_receipt && remainingOf(award) > 0
    && (kind === 'works' ? award.kind === 'works' : award.kind === 'line'));

export function ReceiptDialog({ supplier, onOpenChange, onSave, onError }: Props) {
  const { t } = useTranslation();
  const today = todayIso();
  const hasGoods = rowsOf(supplier, 'goods').length > 0;
  const [kind, setKind] = useState<ReceiptKind>(hasGoods ? 'goods' : 'works');
  const [receivedAt, setReceivedAt] = useState(today);
  const [qty, setQty] = useState<Record<string, string>>({});
  const [comment, setComment] = useState('');
  const [originalsAt, setOriginalsAt] = useState('');
  const [originalsTo, setOriginalsTo] = useState('');
  const [serverErrors, setServerErrors] = useState<Record<string, string>>({});

  const rows = rowsOf(supplier, kind);
  const chosen = rows.filter((row) => (qty[row.award_id] ?? '').trim() !== '');
  const body: ReceiptInput = {
    invitation_id: supplier.invitation_id, received_at: receivedAt, kind,
    lines: chosen.map((row) => ({ award_id: row.award_id, qty: qty[row.award_id].trim().replace(',', '.') })),
    ...(comment.trim() ? { comment: comment.trim() } : {}),
    ...(originalsAt ? { originals_at: originalsAt, originals_to: originalsTo.trim() } : {}),
  };
  const action = useIdempotentAction((key) => onSave(key, body));

  const rowError = (row: DeliveryAward): string | null => {
    const raw = (qty[row.award_id] ?? '').trim().replace(',', '.');
    if (!raw) return null;
    const value = Number(raw);
    if (!Number.isFinite(value) || value <= 0) return t('tender.delivery.qtyPositive', 'Количество — больше нуля');
    if (value > remainingOf(row)) {
      return t('tender.delivery.qtyTooMuch', 'Не больше {{left}} — остальное уже принято', { left: remainingOf(row) });
    }
    return null;
  };
  // Ошибки сервера адресуют строки индексом тела (`lines[0].qty`).
  const serverRowError = (row: DeliveryAward) => {
    const index = chosen.findIndex((item) => item.award_id === row.award_id);
    return index >= 0 ? serverErrors[`lines[${index}].qty`] ?? serverErrors[`lines[${index}].award_id`] : undefined;
  };
  const problem = !receivedAt
    ? t('tender.delivery.pickDate', 'Укажите дату приёмки')
    : receivedAt > today
      ? t('tender.delivery.notFuture', 'Дата приёмки — не позже сегодняшней')
      : chosen.length === 0
        ? t('tender.delivery.pickRows', 'Укажите, сколько принято')
        : rows.some((row) => rowError(row))
          ? t('tender.delivery.fixRows', 'Исправьте количество в строках')
          : null;

  const save = () => action.run().then(() => onOpenChange(false), (failure: unknown) => {
    setServerErrors(fieldErrorsOf(failure, t('tender.common.invalidFormat', 'Неверный формат значения')));
    onError(failure);
  });

  return (
    <Dialog open onOpenChange={(next) => { if (!action.pending) onOpenChange(next); }}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t('tender.delivery.receiptTitle', 'Отметить получение — {{name}}', { name: supplier.supplier })}</DialogTitle>
          <DialogDescription>
            {t('tender.delivery.receiptHint', 'Сканы накладной, акта, счёт-фактуры и фото прикладываются к приёмке после сохранения.')}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <RadioGroup
            value={kind} className="flex gap-4"
            onValueChange={(value) => { setKind(value as ReceiptKind); setQty({}); setServerErrors({}); }}
          >
            <div className="flex items-center gap-2">
              <RadioGroupItem id="receipt-goods" value="goods" disabled={!hasGoods} />
              <Label htmlFor="receipt-goods">{t('tender.delivery.kindGoods', 'Товар получен')}</Label>
            </div>
            <div className="flex items-center gap-2">
              <RadioGroupItem id="receipt-works" value="works" disabled={rowsOf(supplier, 'works').length === 0} />
              <Label htmlFor="receipt-works">{t('tender.delivery.kindWorks', 'Работы приняты')}</Label>
            </div>
          </RadioGroup>

          <div className="space-y-1.5">
            <Label htmlFor="receipt-date">{t('tender.delivery.receivedAt', 'Дата приёмки')}</Label>
            <DateInput id="receipt-date" value={receivedAt} max={today} onChange={setReceivedAt} />
            {serverErrors.received_at && <p className="text-xs text-destructive">{serverErrors.received_at}</p>}
          </div>

          <ul className="space-y-2">
            {rows.map((row) => {
              const error = rowError(row) ?? serverRowError(row);
              return (
                <li key={row.award_id} className="grid gap-2 sm:grid-cols-[1fr_9rem] sm:items-start">
                  <div className="text-sm">
                    {row.name}
                    <span className="block text-xs text-muted-foreground">
                      {t('tender.delivery.left', 'выбрано {{qty}}, принято {{received}}, осталось {{left}}', {
                        qty: row.qty, received: row.received, left: remainingOf(row),
                      })}
                    </span>
                  </div>
                  <div>
                    <Input
                      inputMode="decimal" value={qty[row.award_id] ?? ''}
                      aria-label={t('tender.delivery.qtyFor', 'Принято: {{name}}', { name: row.name })}
                      aria-invalid={Boolean(error) || undefined}
                      onChange={(event) => setQty({ ...qty, [row.award_id]: event.target.value })}
                    />
                    {error && <p className="mt-1 text-xs text-destructive">{error}</p>}
                  </div>
                </li>
              );
            })}
          </ul>

          <div className="space-y-1.5">
            <Label htmlFor="receipt-comment">{t('tender.delivery.comment', 'Комментарий')}</Label>
            <Textarea id="receipt-comment" value={comment} maxLength={2000} onChange={(event) => setComment(event.target.value)} />
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="receipt-originals-at">{t('tender.delivery.originalsAt', 'Оригиналы переданы')}</Label>
              <DateInput id="receipt-originals-at" value={originalsAt} max={today} onChange={setOriginalsAt} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="receipt-originals-to">{t('tender.delivery.originalsTo', 'Кому')}</Label>
              <Input
                id="receipt-originals-to" value={originalsTo} maxLength={255} disabled={!originalsAt}
                onChange={(event) => setOriginalsTo(event.target.value)}
              />
            </div>
          </div>

          {problem && <p className="text-xs text-muted-foreground">{problem}</p>}
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" disabled={action.pending} onClick={() => onOpenChange(false)}>
            {t('tender.common.cancel', 'Отмена')}
          </Button>
          <Button type="button" disabled={Boolean(problem) || action.pending} onClick={() => { void save(); }}>
            {action.pending && <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />}
            {t('tender.delivery.saveReceipt', 'Сохранить приёмку')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default ReceiptDialog;
