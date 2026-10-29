/**
 * Вкладка «Выбор» карточки тендера (TND-022; спека этапа 5, §3 T5.2;
 * S5-05…S5-07, S5-11).
 *
 * - У позиции — один поставщик; количество — не больше предложенного
 *   (пусто — всё предложенное).
 * - Доставку и СМР выбирают только у победителя хотя бы одной позиции;
 *   «в цене» у победителя выбирается сама — подписью, без выбора.
 * - Не самый дешёвый вариант — нужны общий комментарий и комментарий строки
 *   (от 10 символов). Подсказка — по `cheapest_invitation_id` сравнения,
 *   решение — за сервером: 422 `E-TND-12` подсвечивает строки.
 * - «На утверждение» — только сохранённый выбор (`award_submit` приходит,
 *   когда выбор есть); 422 `E-TND-11` — блок дефицита по статьям, `E-TND-10`
 *   (нет курса) и `E-SGN-01` (маршрут) — текстом сервера.
 * - Нет действия `award` (выбор на утверждении, утверждён) — только чтение.
 */
import { useEffect, useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Loader2, Send } from 'lucide-react';

import { newIdempotencyKey } from '@/api/files';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { Textarea } from '@/components/ui/textarea';
import { formatMoney } from '@/features/bpp/format';
import { errorCode } from '@/lib/apiError';

import { isConflict } from '../core/conflict';
import { fieldErrorsOf, reportFormError } from '../core/fieldErrors';
import { tenderKeys, tendersApi, type TenderCard } from './api';
import {
  AWARD_COMMENT_MIN, awardInput, choicesOf, needsLineComment, rowErrors, winnersOf,
  type Comparison, type Deficit, type RowErrors,
} from './comparison';

const NONE = '__none__';

interface Props {
  tenderId: string;
  /** Карточка изменилась (выбор сохранён, ушёл на утверждение) или конфликт версий. */
  onChanged: (card?: TenderCard) => void;
  onConflict: () => void;
}

type Choice = ReturnType<typeof choicesOf>;

export function AwardTab({ tenderId, onChanged, onConflict }: Props) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const comparison = useQuery({
    queryKey: tenderKeys.comparison(tenderId),
    queryFn: () => tendersApi.comparison(tenderId),
  });
  const award = useQuery({
    queryKey: tenderKeys.award(tenderId),
    queryFn: () => tendersApi.getAward(tenderId),
  });

  const [choice, setChoice] = useState<Choice>(() => choicesOf(undefined));
  const [errors, setErrors] = useState<RowErrors>({ lines: {}, extras: {}, rest: {} });
  const [deficits, setDeficits] = useState<Deficit[]>([]);
  const [saving, setSaving] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const stamp = award.data ? `${award.data.tender_id}:${award.data.version}` : '';
  useEffect(() => {
    if (award.data) setChoice(choicesOf(award.data));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stamp]);

  const saved = useMemo(() => choicesOf(award.data), [award.data]);
  const dirty = JSON.stringify(choice) !== JSON.stringify(saved);

  if (comparison.isLoading || award.isLoading) return <Skeleton className="h-48 w-full" />;
  if (!comparison.data || !award.data) {
    return (
      <p className="text-sm text-muted-foreground">
        {t('tender.award.loadFailed', 'Не удалось загрузить выбор поставщиков.')}
      </p>
    );
  }
  const data: Comparison = comparison.data;
  const view = award.data;
  const editable = view.allowed_actions.includes('award');
  const canSubmit = view.allowed_actions.includes('award_submit');
  const winners = winnersOf(choice.lines);
  const supplierName = new Map(data.suppliers.map((row) => [row.invitation_id, row.name]));
  const anyNotCheapest = data.items.some((item) => needsLineComment(item, choice.lines[item.item_id]?.invitationId ?? ''))
    || data.extras.some((extra) => {
      const row = choice.extras[extra.kind];
      return Boolean(row?.invitationId) && extra.cheapest_invitation_id !== null
        && extra.cheapest_invitation_id !== row.invitationId;
    });

  const setLine = (itemId: string, invitationId: string) => setChoice((current) => {
    const lines = { ...current.lines };
    if (invitationId === NONE) delete lines[itemId];
    else lines[itemId] = { invitationId, qty: '', comment: current.lines[itemId]?.comment ?? '' };
    return { ...current, lines };
  });
  const patchLine = (itemId: string, patch: Partial<Choice['lines'][string]>) => setChoice((current) => ({
    ...current, lines: { ...current.lines, [itemId]: { ...current.lines[itemId], ...patch } },
  }));
  const setExtra = (kind: string, invitationId: string) => setChoice((current) => {
    const extras = { ...current.extras };
    if (invitationId === NONE) delete extras[kind];
    else extras[kind] = { invitationId, comment: current.extras[kind]?.comment ?? '' };
    return { ...current, extras };
  });

  const refreshAward = () => {
    void queryClient.invalidateQueries({ queryKey: tenderKeys.award(tenderId) });
  };

  const save = async () => {
    const { body, lineKeys, extraKeys } = awardInput(data, choice, view.version);
    setSaving(true);
    setErrors({ lines: {}, extras: {}, rest: {} });
    setDeficits([]);
    try {
      const next = await tendersApi.saveAward(tenderId, body);
      queryClient.setQueryData(tenderKeys.award(tenderId), next);
      onChanged();
      toast.success(t('tender.award.saved', 'Выбор сохранён'));
    } catch (failure) {
      if (isConflict(failure)) onConflict();
      setErrors(rowErrors(fieldErrorsOf(failure, t('tender.common.invalidFormat', 'Неверный формат значения')),
        lineKeys, extraKeys));
      reportFormError(
        failure,
        t('tender.award.saveFailed', 'Не удалось сохранить выбор'),
        t('tender.common.invalidFormatToast', 'Сервер не принял формат некоторых полей — проверьте выделенные поля.'),
      );
    } finally {
      setSaving(false);
    }
  };

  const submit = async () => {
    setSubmitting(true);
    setDeficits([]);
    try {
      const card = await tendersApi.submitAward(tenderId, newIdempotencyKey(), view.version);
      refreshAward();
      onChanged(card);
      toast.success(t('tender.award.submitted', 'Выбор отправлен на утверждение'));
    } catch (failure) {
      if (isConflict(failure)) onConflict();
      if (errorCode(failure) === 'E-TND-11') {
        const details = (failure as { response?: { data?: { details?: { deficits?: Deficit[] } } } })
          .response?.data?.details;
        setDeficits(details?.deficits ?? []);
      }
      reportFormError(
        failure,
        t('tender.award.submitFailed', 'Не удалось отправить выбор на утверждение'),
        t('tender.common.invalidFormatToast', 'Сервер не принял формат некоторых полей — проверьте выделенные поля.'),
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="space-y-4" data-testid="tender-award">
      {view.status === 'rework' && view.status_comment && (
        <Alert>
          <AlertTitle>{t('tender.award.returned', 'Выбор возвращён на доработку')}</AlertTitle>
          <AlertDescription className="whitespace-pre-wrap">{view.status_comment}</AlertDescription>
        </Alert>
      )}

      <div className="overflow-x-auto rounded-2xl border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t('tender.comparison.item', 'Позиция')}</TableHead>
              <TableHead>{t('tender.award.supplier', 'Поставщик')}</TableHead>
              <TableHead className="text-right">{t('tender.award.qty', 'Количество')}</TableHead>
              <TableHead>{t('tender.award.rowComment', 'Комментарий к строке')}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.items.map((item) => {
              const row = choice.lines[item.item_id];
              const options = data.suppliers.filter((s) => item.offers[s.invitation_id]?.participates);
              const cell = row ? item.offers[row.invitationId] : undefined;
              const needComment = needsLineComment(item, row?.invitationId ?? '');
              const rowError = errors.lines[item.item_id] ?? {};
              const error = rowError.comment;
              return (
                <TableRow key={item.item_id} data-testid={`award-item-${item.line_no}`}>
                  <TableCell className="max-w-xs whitespace-normal">
                    {item.line_no}. {item.name}
                    <span className="block text-xs text-muted-foreground">
                      {item.qty} {item.uom.short_name}
                    </span>
                  </TableCell>
                  <TableCell className="min-w-56">
                    {editable ? (
                      <Select value={row?.invitationId ?? NONE} onValueChange={(value) => setLine(item.item_id, value)}>
                        <SelectTrigger aria-label={t('tender.award.supplierFor', 'Поставщик позиции {{n}}', { n: item.line_no })}>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value={NONE}>{t('tender.award.notChosen', '— не выбран —')}</SelectItem>
                          {options.map((s) => {
                            const offer = item.offers[s.invitation_id];
                            return (
                              <SelectItem key={s.invitation_id} value={s.invitation_id}>
                                {s.name} · {formatMoney(offer?.price ?? '', s.currency_code)}
                                {item.cheapest_invitation_id === s.invitation_id
                                  ? ` · ${t('tender.award.cheapest', 'дешевле всех')}` : ''}
                              </SelectItem>
                            );
                          })}
                        </SelectContent>
                      </Select>
                    ) : (row ? supplierName.get(row.invitationId) ?? '—' : '—')}
                    {rowError.line_id && <p className="mt-1 text-xs text-destructive">{rowError.line_id}</p>}
                  </TableCell>
                  <TableCell className="text-right">
                    {row && cell && (editable ? (
                      <>
                        <Input
                          className="ml-auto w-28 text-right" inputMode="decimal" value={row.qty}
                          placeholder={cell.qty}
                          aria-label={t('tender.award.qtyFor', 'Количество позиции {{n}}', { n: item.line_no })}
                          aria-invalid={Boolean(rowError.qty) || undefined}
                          onChange={(event) => patchLine(item.item_id, { qty: event.target.value })}
                        />
                        {rowError.qty && <p className="mt-1 text-xs text-destructive">{rowError.qty}</p>}
                      </>
                    ) : (row.qty || cell.qty))}
                  </TableCell>
                  <TableCell className="min-w-64">
                    {row && (editable ? (
                      <>
                        <Input
                          value={row.comment}
                          aria-label={t('tender.award.commentFor', 'Комментарий к позиции {{n}}', { n: item.line_no })}
                          aria-invalid={Boolean(error) || undefined}
                          placeholder={needComment
                            ? t('tender.award.whyNotCheapest', 'Почему не самый дешёвый — от {{min}} символов', { min: AWARD_COMMENT_MIN })
                            : ''}
                          onChange={(event) => patchLine(item.item_id, { comment: event.target.value })}
                        />
                        {error && <p className="mt-1 text-xs text-destructive">{error}</p>}
                      </>
                    ) : row.comment || '—')}
                  </TableCell>
                </TableRow>
              );
            })}
            {data.extras.map((extra) => {
              const label = extra.kind === 'delivery'
                ? t('tender.comparison.delivery', 'Доставка') : t('tender.comparison.works', 'СМР');
              const included = [...winners].find((id) => extra.offers[id]?.included_in_price);
              const options = data.suppliers.filter((s) => winners.has(s.invitation_id)
                && extra.offers[s.invitation_id] && !extra.offers[s.invitation_id]?.included_in_price);
              const row = choice.extras[extra.kind];
              const extraError = errors.extras[extra.kind] ?? {};
              const error = extraError.comment ?? extraError.extra_id;
              return (
                <TableRow key={extra.kind} data-testid={`award-extra-${extra.kind}`}>
                  <TableCell>{label}</TableCell>
                  <TableCell colSpan={2}>
                    {included ? (
                      t('tender.award.includedAt', 'в цене у {{name}}', { name: supplierName.get(included) ?? '' })
                    ) : editable ? (
                      <Select
                        value={row && winners.has(row.invitationId) ? row.invitationId : NONE}
                        onValueChange={(value) => setExtra(extra.kind, value)}
                      >
                        <SelectTrigger aria-label={t('tender.award.supplierForExtra', 'Поставщик: {{label}}', { label })}>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value={NONE}>{t('tender.award.notChosen', '— не выбран —')}</SelectItem>
                          {options.map((s) => (
                            <SelectItem key={s.invitation_id} value={s.invitation_id}>
                              {s.name} · {formatMoney(extra.offers[s.invitation_id]?.amount ?? '', s.currency_code)}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    ) : (row ? supplierName.get(row.invitationId) ?? '—' : '—')}
                    {editable && !included && options.length === 0 && (
                      <p className="mt-1 text-xs text-muted-foreground">
                        {t('tender.award.extraNeedsWinner', 'Выбирается у поставщика, выигравшего хотя бы одну позицию.')}
                      </p>
                    )}
                  </TableCell>
                  <TableCell>
                    {row && winners.has(row.invitationId) && !included && (editable ? (
                      <>
                        <Input
                          value={row.comment}
                          aria-label={t('tender.award.commentForExtra', 'Комментарий: {{label}}', { label })}
                          aria-invalid={Boolean(error) || undefined}
                          onChange={(event) => setChoice((current) => ({
                            ...current,
                            extras: { ...current.extras, [extra.kind]: { ...row, comment: event.target.value } },
                          }))}
                        />
                        {error && <p className="mt-1 text-xs text-destructive">{error}</p>}
                      </>
                    ) : row.comment || '—')}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="award-comment">{t('tender.award.comment', 'Комментарий к выбору')}</Label>
        {editable ? (
          <Textarea
            id="award-comment" value={choice.comment} maxLength={4000}
            aria-invalid={Boolean(errors.rest.comment) || undefined}
            placeholder={anyNotCheapest
              ? t('tender.award.commentRequired', 'Выбран не самый дешёвый вариант — объясните выбор, от {{min}} символов', { min: AWARD_COMMENT_MIN })
              : ''}
            onChange={(event) => setChoice({ ...choice, comment: event.target.value })}
          />
        ) : (
          <p className="whitespace-pre-wrap text-sm">{view.comment || '—'}</p>
        )}
        {errors.rest.comment && <p className="text-xs text-destructive">{errors.rest.comment}</p>}
      </div>

      {view.suppliers.length > 0 && (
        <div className="space-y-1">
          <h4 className="text-sm font-semibold">{t('tender.award.savedTotals', 'Сохранённый выбор')}</h4>
          <ul className="text-sm">
            {view.suppliers.map((row) => (
              <li key={row.invitation_id}>
                {row.name}: {formatMoney(row.amount, row.currency_code)}
                {row.currency_code !== 'KZT' && row.amount_kzt && ` (${formatMoney(row.amount_kzt, 'KZT')})`}
              </li>
            ))}
          </ul>
          {view.parts.some((part) => !part.over_plan_kzt.match(/^0(\.0+)?$/)) && (
            <p className="text-xs text-amber-700 dark:text-amber-400">
              {t('tender.award.overPlan', 'Выбор дороже плана — при отправке проверится свободный остаток бюджета статьи.')}
            </p>
          )}
        </div>
      )}

      {deficits.length > 0 && (
        <Alert variant="destructive" data-testid="award-deficits">
          <AlertTitle>{t('tender.award.deficitTitle', 'Не хватает бюджета статьи')}</AlertTitle>
          <AlertDescription>
            <ul className="list-disc pl-5 text-sm">
              {deficits.map((row) => (
                <li key={row.article_id}>
                  {t('tender.award.deficitRow', '{{code}}: сверх плана {{over}} KZT, свободно {{available}} KZT', {
                    code: row.article_code || row.article_id,
                    over: formatMoney(row.over),
                    available: formatMoney(row.available),
                  })}
                </li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      )}

      {(editable || canSubmit) && (
        <div className="flex flex-wrap items-center gap-2">
          {editable && (
            <Button type="button" disabled={saving || submitting || !dirty} onClick={() => { void save(); }}>
              {saving && <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />}
              {t('tender.award.save', 'Сохранить выбор')}
            </Button>
          )}
          {canSubmit && (
            <Button
              type="button" variant="outline" disabled={saving || submitting || dirty}
              onClick={() => { void submit(); }}
            >
              {submitting ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <Send className="mr-1.5 h-4 w-4" />}
              {t('tender.award.submit', 'На утверждение')}
            </Button>
          )}
          {canSubmit && dirty && (
            <span className="text-xs text-muted-foreground">
              {t('tender.award.saveBeforeSubmit', 'Сохраните выбор перед отправкой')}
            </span>
          )}
        </div>
      )}
    </section>
  );
}

export default AwardTab;
