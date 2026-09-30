/**
 * «Сопоставить вручную» строку «Не сопоставлена» (ТЗ §11.4).
 *
 * - кандидаты приходят с сервера: контрагент с БИН получателя и близкая
 *   сумма; поиск — по номеру счёта, контрагенту или сумме. Выбранные счета
 *   остаются в списке распределения, даже когда поиск их уже не показывает;
 * - платёж можно разложить на несколько счетов; «Остаток к распределению»
 *   считается на лету, Σ больше суммы строки кнопку закрывает — такой запрос
 *   не уходит (сервер ответил бы 422 на `amount`);
 * - отказ сервера по полю (`invoice_id`, `amount`) — у своего места в
 *   диалоге, обычный 422 без полей (кривая сумма) — тостом.
 */
import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Loader2, X } from 'lucide-react';

import { PrerequisiteNotice } from '@/components/common/PrerequisiteNotice';
import { Button } from '@/components/ui/button';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { errorDetail, reportApiError } from '@/lib/apiError';

import { useIdempotentAction } from '../core/useIdempotentAction';
import { errorFields } from '../counterparties/errors';
import { formatMoney } from '../format';

import { centsFromInput, fromCents, toCents } from './amounts';
import { bankImportApi, type MatchCandidate, type StatementLine } from './api';

const SEARCH_DELAY_MS = 300;

interface Picked {
  candidate: MatchCandidate;
  /** Ввод человека («1 250,50»). */
  amount: string;
}

interface Props {
  line: StatementLine;
  onClose: (done: boolean) => void;
}

type Errors = { invoice_id?: string; amount?: string };

export function ManualMatchDialog({ line, onClose }: Props) {
  const { t } = useTranslation();
  const [search, setSearch] = useState('');
  const [query, setQuery] = useState('');
  const [picked, setPicked] = useState<Picked[]>([]);
  const [errors, setErrors] = useState<Errors>({});

  useEffect(() => {
    const timer = setTimeout(() => setQuery(search.trim()), SEARCH_DELAY_MS);
    return () => clearTimeout(timer);
  }, [search]);

  const candidates = useQuery({
    queryKey: ['bpp', 'bank', 'candidates', line.id, query],
    queryFn: () => bankImportApi.candidates(line.id, query),
  });
  const found = candidates.data ?? [];

  const lineCents = toCents(line.amount) ?? 0n;
  const parsed = picked.map((item) => centsFromInput(item.amount));
  const sum = parsed.reduce<bigint>((total, cents) => total + (cents ?? 0n), 0n);
  const rest = lineCents - sum;
  const invalidAmount = parsed.some((cents) => cents === null || cents <= 0n);
  const over = rest < 0n;
  const canSubmit = picked.length > 0 && !invalidAmount && !over;

  const pick = (candidate: MatchCandidate) => {
    if (picked.some((item) => item.candidate.id === candidate.id)) return;
    // Предложение: что осталось от платежа, но не больше остатка счёта.
    let suggested = rest > 0n ? rest : 0n;
    const remainder = toCents(candidate.remainder);
    if (remainder !== null && remainder > 0n && remainder < suggested) suggested = remainder;
    setPicked((current) => [...current, { candidate, amount: fromCents(suggested) }]);
    setErrors({});
  };
  const unpick = (id: string) => {
    setPicked((current) => current.filter((item) => item.candidate.id !== id));
    setErrors({});
  };
  const setAmount = (id: string, amount: string) => {
    setPicked((current) => current.map((item) => (item.candidate.id === id ? { ...item, amount } : item)));
    setErrors((current) => ({ ...current, amount: undefined }));
  };

  const action = useIdempotentAction((key) => bankImportApi.match(
    key,
    line.id,
    picked.map((item) => {
      const cents = centsFromInput(item.amount);
      return { invoice_id: item.candidate.id, amount: cents === null ? item.amount : fromCents(cents) };
    }),
  ));

  const submit = () => {
    if (!canSubmit) return;
    setErrors({});
    action.run().then(
      () => onClose(true),
      (error: unknown) => {
        const fields = errorFields(error);
        const next: Errors = {};
        for (const item of fields) {
          if (item.field === 'invoice_id' || item.field === 'amount') next[item.field] = item.message;
        }
        if (next.invoice_id || next.amount) {
          setErrors(next);
        } else if (fields.length > 0) {
          setErrors({ invoice_id: errorDetail(error) ?? fields[0].message });
        } else {
          reportApiError(error, t('bpp.bank.matchFailed', 'Не удалось сопоставить строку'));
        }
      },
    );
  };

  return (
    <Dialog open onOpenChange={(open) => { if (!open && !action.pending) onClose(false); }}>
      <DialogContent className="max-h-[90vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t('bpp.bank.matchTitle', 'Сопоставить вручную')}</DialogTitle>
          <DialogDescription>
            {t('bpp.bank.matchLine', 'Платёж № {{number}} на {{amount}} · {{recipient}}', {
              number: line.doc_number || '—',
              amount: formatMoney(line.amount, line.currency),
              recipient: line.recipient_name || '—',
            })}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-1.5">
          <Label htmlFor="match-search">{t('bpp.bank.matchSearch', 'Поиск счёта')}</Label>
          <Input
            id="match-search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={t('bpp.bank.matchSearchHint', 'Номер счёта, контрагент или сумма')}
          />
        </div>

        <div className="space-y-2">
          {candidates.isLoading && <Skeleton className="h-16 w-full" />}
          {candidates.isError && (
            <p className="text-sm text-destructive">
              {t('bpp.bank.candidatesError', 'Не удалось загрузить счета. Повторите поиск.')}
            </p>
          )}
          <PrerequisiteNotice
            variant="inline"
            items={[{
              when: candidates.isSuccess && found.length === 0,
              text: query
                ? t('bpp.bank.noCandidatesQuery', 'По запросу счетов в валюте платежа не найдено — уточните номер, контрагента или сумму')
                : t('bpp.bank.noCandidates', 'Подходящих счетов нет: у получателя может не быть БИН или счетов в валюте платежа. Введите номер, контрагента или сумму в поиск'),
            }]}
          />
          {found.length > 0 && (
            <ul className="divide-y rounded-lg border" aria-label={t('bpp.bank.candidates', 'Подходящие счета')}>
              {found.map((candidate) => {
                const chosen = picked.some((item) => item.candidate.id === candidate.id);
                return (
                  <li key={candidate.id} className="flex flex-wrap items-center justify-between gap-2 p-2 text-sm">
                    <div className="min-w-0 leading-tight">
                      <div className="font-medium">
                        {candidate.number}
                        {candidate.same_bin && (
                          <span className="ml-2 text-xs font-normal text-emerald-700 dark:text-emerald-300">
                            {t('bpp.bank.sameBin', 'тот же БИН')}
                          </span>
                        )}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {candidate.counterparty.name} · {candidate.status_label} · {t('bpp.bank.candidateAmount', 'сумма')}{' '}
                        {formatMoney(candidate.amount, candidate.currency_code)} · {t('bpp.bank.candidateRemainder', 'остаток')}{' '}
                        {formatMoney(candidate.remainder, candidate.currency_code)}
                      </div>
                    </div>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      disabled={chosen}
                      onClick={() => pick(candidate)}
                      aria-label={t('bpp.bank.pick', 'Выбрать счёт {{number}}', { number: candidate.number })}
                    >
                      {chosen ? t('bpp.bank.picked', 'Выбран') : t('bpp.bank.pickShort', 'Выбрать')}
                    </Button>
                  </li>
                );
              })}
            </ul>
          )}
          {errors.invoice_id && <p role="alert" className="text-sm text-destructive">{errors.invoice_id}</p>}
        </div>

        {picked.length > 0 && (
          <div className="space-y-2">
            <h3 className="text-sm font-medium">{t('bpp.bank.allocation', 'Распределение платежа')}</h3>
            <ul className="space-y-2">
              {picked.map((item, index) => (
                <li key={item.candidate.id} className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="min-w-0 flex-1 truncate">
                    {item.candidate.number} · {item.candidate.counterparty.name}
                  </span>
                  <Input
                    className="w-40 text-right tabular-nums"
                    inputMode="decimal"
                    value={item.amount}
                    aria-label={t('bpp.bank.allocationAmount', 'Сумма на счёт {{number}}', { number: item.candidate.number })}
                    aria-invalid={parsed[index] === null || (parsed[index] ?? 0n) <= 0n}
                    onChange={(event) => setAmount(item.candidate.id, event.target.value)}
                  />
                  <Button
                    type="button"
                    size="icon"
                    variant="ghost"
                    onClick={() => unpick(item.candidate.id)}
                    aria-label={t('bpp.bank.unpick', 'Убрать счёт {{number}}', { number: item.candidate.number })}
                  >
                    <X className="h-4 w-4" />
                  </Button>
                </li>
              ))}
            </ul>
            <p
              className={over ? 'text-sm font-medium text-destructive' : 'text-sm text-muted-foreground'}
              role={over ? 'alert' : 'status'}
            >
              {over
                ? t('bpp.bank.allocationOver', 'Сумма распределения больше суммы платежа на {{amount}}', {
                  amount: formatMoney(fromCents(-rest), line.currency),
                })
                : t('bpp.bank.allocationRest', 'Остаток к распределению: {{amount}}', {
                  amount: formatMoney(fromCents(rest), line.currency),
                })}
            </p>
            {invalidAmount && (
              <p className="text-sm text-destructive">
                {t('bpp.bank.allocationInvalid', 'Укажите сумму больше нуля в формате 1 250 000,00')}
              </p>
            )}
            {errors.amount && <p role="alert" className="text-sm text-destructive">{errors.amount}</p>}
          </div>
        )}

        <DialogFooter>
          <Button type="button" variant="ghost" disabled={action.pending} onClick={() => onClose(false)}>
            {t('bpp.bank.dialogCancel', 'Отмена')}
          </Button>
          <Button type="button" disabled={!canSubmit || action.pending} onClick={submit}>
            {action.pending && <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />}
            {t('bpp.bank.matchSubmit', 'Сопоставить')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
