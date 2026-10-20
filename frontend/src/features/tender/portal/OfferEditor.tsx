/**
 * Предложение поставщика (T3.5; план этапа 3, T3.3): тендер для поставщика
 * (без плановых цен заказчика), позиции, доставка и СМР, НДС, валюта, срок
 * действия, схема оплаты 1–3, дополнительные условия, файлы КП, реквизиты,
 * согласие на ПДн перед первой отправкой; «Сохранить черновик»,
 * «Отправить», «Отозвать», «Отказаться».
 *
 * Только чтение — если приём закрыт (срок прошёл, тендер не принимает
 * предложения или сервер ответил 409 `E-TND-05`): тогда итог «Ожидается
 * решение». Отказы, после которых форма жить не может (устройство, ссылка),
 * поднимаются странице (`onFatal`) — она показывает экран целиком.
 */
import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { AlertTriangle, CheckCircle2, Clock, Download, Loader2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { DateInput } from '@/components/ui/date-input';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { formatDate, formatDateTime, formatMoney } from '@/features/bpp/format';

import { PaymentSchemeField } from '../tenders/PaymentSchemeField';
import { describeScheme } from '../tenders/schemes';
import { PortalError, portalApi, portalKeys } from './client';
import { ConfirmDialog } from './ConfirmDialog';
import { FilesSection } from './FilesSection';
import { LineCard } from './LineCard';
import {
  formOf, offerErrors, offerInput, offerTotal, type ExtraForm, type OfferForm,
} from './offerForm';
import {
  CLOSED_CODE, CONFLICT_CODE, isFatal, portalFieldErrors, screenOf,
} from './portalErrors';
import { RequisitesSection } from './RequisitesSection';
import type { PortalOffer, PortalTender } from './types';

const REASON_MIN = 10;
const today = () => new Date().toISOString().slice(0, 10);

interface Props {
  token: string;
  tender: PortalTender;
  offer: PortalOffer;
  onFatal: (error: unknown) => void;
  onDeclined: () => void;
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-3 rounded-2xl border bg-card p-4">
      <h2 className="text-lg font-semibold">{title}</h2>
      {children}
    </section>
  );
}

export function OfferEditor({ token, tender, offer, onFatal, onDeclined }: Props) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [form, setForm] = useState<OfferForm>(() => formOf(tender, offer));
  const [baseline, setBaseline] = useState(() => JSON.stringify(formOf(tender, offer)));
  const [showErrors, setShowErrors] = useState(false);
  const [serverErrors, setServerErrors] = useState<Record<string, string>>({});
  const [consent, setConsent] = useState(false);
  const [closed, setClosed] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const [dialog, setDialog] = useState<'withdraw' | 'decline' | null>(null);

  const stamp = `${offer.id}:${offer.version}:${offer.status}`;
  useEffect(() => {
    const next = formOf(tender, offer);
    setForm(next);
    setBaseline(JSON.stringify(next));
    setServerErrors({});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stamp]);

  const readOnly = closed || !tender.intake_open || !offer.editable;
  // Правка открыта только у предложения со строкой (черновик заводится на
  // GET, пока идёт приём) — `null` бывает лишь у пустого ответа «только чтение».
  const offerVersion = offer.version ?? 0;
  const requisitesEditable = !offer.requisites_readonly && !readOnly;
  const dirty = JSON.stringify(form) !== baseline;
  const errors = useMemo(
    () => offerErrors(form, tender, today(), { requisitesEditable }),
    [form, tender, requisitesEditable],
  );
  const shown = (key: string) => serverErrors[key] ?? (showErrors ? errors[key] : undefined);
  const needsConsent = !offer.pd_consent_at;
  const submitted = offer.status === 'submitted'
    ? offer.number
    : [...offer.history].reverse().find((row) => row.status === 'submitted')?.number ?? null;
  const submittedAt = offer.status === 'submitted'
    ? offer.history.find((row) => row.number === offer.number)?.submitted_at ?? null
    : [...offer.history].reverse().find((row) => row.status === 'submitted')?.submitted_at ?? null;
  const currency = form.currency_code || tender.currency_code;
  const set = <K extends keyof OfferForm>(key: K, value: OfferForm[K]) =>
    setForm((current) => ({ ...current, [key]: value }));

  const apply = (saved: PortalOffer) => {
    queryClient.setQueryData(portalKeys.offer(token), saved);
    // Первое сохранение после отправки заводит черновик-копию — у её файлов
    // свои ключи, и список на экране (ключи версии) устарел.
    void queryClient.invalidateQueries({ queryKey: portalKeys.files(token) });
    setBaseline(JSON.stringify(formOf(tender, saved)));
  };

  /** Разбор отказа: `true` — разобран (экран, плашка), иначе — текст. */
  const handled = (error: unknown): boolean => {
    const screen = screenOf(error);
    if (isFatal(screen)) {
      onFatal(error);
      return true;
    }
    if (error instanceof PortalError && error.code === CLOSED_CODE) {
      setClosed(true);
      setNotice(null);
      return true;
    }
    if (screen === 'rate') {
      const seconds = error instanceof PortalError ? error.retryAfter : null;
      setNotice(seconds
        ? t('tender.portal.rateText', 'Слишком много запросов, повторите через {{seconds}} с', { seconds })
        : t('tender.portal.rateTextLater', 'Слишком много запросов, повторите чуть позже'));
      return true;
    }
    if (error instanceof PortalError && error.code === CONFLICT_CODE) {
      setNotice(t('tender.portal.conflict', 'Предложение изменилось в другой вкладке. Обновите страницу.'));
      void queryClient.invalidateQueries({ queryKey: portalKeys.offer(token) });
      return true;
    }
    return false;
  };

  const report = (error: unknown) => {
    if (handled(error)) return;
    setServerErrors(portalFieldErrors(error, form.lines.map((line) => line.item_id)));
    setShowErrors(true);
    toast.error(error instanceof PortalError && error.detail
      ? error.detail : t('tender.portal.actionFailed', 'Не удалось выполнить действие. Повторите попытку.'));
  };

  const run = async (name: string, action: () => Promise<void>) => {
    setPending(name);
    setNotice(null);
    setServerErrors({});
    try {
      await action();
    } catch (error) {
      report(error);
    } finally {
      setPending(null);
    }
  };

  const save = () => run('save', async () => {
    apply(await portalApi.saveOffer(token, offerInput(form, offerVersion, { requisitesEditable })));
    toast.success(t('tender.portal.saved', 'Черновик сохранён'));
  });

  const submit = () => {
    setShowErrors(true);
    if (Object.keys(errors).length > 0) return;
    void run('submit', async () => {
      let version = offerVersion;
      // Отправляют только черновик: на экране отправленная или отозванная
      // версия — сперва PUT заводит из неё черновик (без него submit — 409).
      if (dirty || offer.status !== 'draft') {
        const saved = await portalApi.saveOffer(token, offerInput(form, offerVersion, { requisitesEditable }));
        apply(saved);
        version = saved.version ?? offerVersion;
      }
      apply(await portalApi.submit(token, needsConsent ? { version, pd_consent: true } : { version }));
      setShowErrors(false);
      toast.success(t('tender.portal.submittedToast', 'Предложение отправлено'));
    });
  };

  const withdraw = () => run('withdraw', async () => {
    apply(await portalApi.withdraw(token, { version: offerVersion }));
    setDialog(null);
  });

  const decline = (reason: string) => run('decline', async () => {
    await portalApi.decline(token, { reason });
    setDialog(null);
    onDeclined();
  });

  const extraEditor = (key: 'delivery' | 'works', extra: ExtraForm) => {
    const included = key === 'delivery'
      ? t('tender.portal.deliveryIncluded', 'Доставка включена в цену')
      : t('tender.portal.worksIncluded', 'СМР включены в цену');
    const amountLabel = key === 'delivery'
      ? t('tender.portal.deliveryCost', 'Стоимость доставки, {{currency}}', { currency })
      : t('tender.portal.worksCost', 'Стоимость СМР, {{currency}}', { currency });
    if (readOnly) {
      return (
        <p className="text-sm">
          {extra.included_in_price ? included : `${amountLabel}: ${extra.amount || '—'}`}
          {extra.note && <span className="block text-muted-foreground">{extra.note}</span>}
        </p>
      );
    }
    const update = (change: Partial<ExtraForm>) => set(key, { ...extra, ...change });
    return (
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <Checkbox
            id={`portal-${key}-included`} checked={extra.included_in_price}
            onCheckedChange={(value) => update({ included_in_price: value === true })}
          />
          <Label htmlFor={`portal-${key}-included`} className="text-base font-normal">{included}</Label>
        </div>
        {!extra.included_in_price && (
          <div className="space-y-1.5">
            <Label htmlFor={`portal-${key}-amount`}>{amountLabel}</Label>
            <Input
              id={`portal-${key}-amount`} inputMode="decimal" className="h-11 text-base" value={extra.amount}
              onChange={(event) => update({ amount: event.target.value })}
            />
          </div>
        )}
        {key === 'works' && (
          <div className="space-y-1.5">
            <Label htmlFor="portal-works-note">{t('tender.portal.worksNote', 'Состав работ')}</Label>
            <Textarea
              id="portal-works-note" className="text-base" value={extra.note} maxLength={2000}
              onChange={(event) => update({ note: event.target.value })}
            />
          </div>
        )}
        {shown(key) && <p className="text-sm text-destructive">{shown(key)}</p>}
      </div>
    );
  };

  return (
    <div className="space-y-5">
      <header className="space-y-1">
        <p className="text-sm text-muted-foreground">{tender.customer}</p>
        <h1 className="text-2xl font-bold">
          {t('tender.portal.tenderNumber', 'Тендер {{number}}', { number: tender.number })}
        </h1>
        <p className="text-base">
          {t('tender.portal.deadline', 'Приём предложений до {{deadline}}', { deadline: formatDateTime(tender.deadline_at) })}
        </p>
      </header>

      {closed && (
        <div role="alert" className="flex gap-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-base dark:border-amber-800 dark:bg-amber-950/40">
          <Clock className="mt-1 h-4 w-4 shrink-0" />
          <span>{t('tender.portal.closedTitle', 'Приём предложений завершён')}</span>
        </div>
      )}
      {readOnly && (
        <div role="status" className="space-y-1 rounded-2xl border bg-muted/40 p-4">
          <p className="text-lg font-semibold">
            {tender.result === 'awaiting' || !tender.result
              ? t('tender.portal.awaiting', 'Ожидается решение')
              : tender.result}
          </p>
          <p className="text-sm text-muted-foreground">
            {submitted
              ? t('tender.portal.awaitingSubmitted', 'Ваше предложение № {{number}} принято. О решении сообщит закупщик.', { number: submitted })
              : t('tender.portal.awaitingNone', 'Приём предложений завершён. О решении сообщит закупщик.')}
          </p>
        </div>
      )}
      {!readOnly && submitted && (
        <div role="status" className="flex gap-2 rounded-lg border border-emerald-300 bg-emerald-50 p-3 text-sm dark:border-emerald-800 dark:bg-emerald-950/40">
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            {t('tender.portal.submittedBanner',
              'Предложение № {{number}} отправлено {{date}}. До срока его можно изменить и отправить заново или отозвать.',
              { number: submitted, date: formatDateTime(submittedAt) })}
          </span>
        </div>
      )}
      {notice && (
        <div role="alert" className="flex gap-2 rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-sm">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{notice}</span>
        </div>
      )}

      <Section title={t('tender.portal.conditions', 'Условия заказчика')}>
        <dl className="grid gap-2 text-sm">
          <div><dt className="text-muted-foreground">{t('tender.portal.currency', 'Валюта')}</dt><dd>{tender.currency_code}</dd></div>
          <div>
            <dt className="text-muted-foreground">{t('tender.portal.desiredScheme', 'Желаемая схема оплаты')}</dt>
            <dd>{describeScheme(tender.payment_scheme, (key, fallback, options) => t(key, fallback, options))}</dd>
          </div>
          {tender.delivery_terms && (
            <div><dt className="text-muted-foreground">{t('tender.portal.deliveryTerms', 'Условия поставки')}</dt><dd className="whitespace-pre-wrap">{tender.delivery_terms}</dd></div>
          )}
          {tender.delivery_address && (
            <div><dt className="text-muted-foreground">{t('tender.portal.deliveryAddress', 'Адрес доставки')}</dt><dd>{tender.delivery_address}</dd></div>
          )}
          {tender.needs_works && (
            <div><dt className="text-muted-foreground">{t('tender.portal.worksScope', 'Нужны работы (СМР)')}</dt><dd className="whitespace-pre-wrap">{tender.works_scope || '—'}</dd></div>
          )}
          <div>
            <dt className="text-muted-foreground">{t('tender.portal.rules', 'Правила')}</dt>
            <dd>
              {tender.allow_analogs
                ? t('tender.portal.analogsAllowed', 'Аналоги допускаются')
                : t('tender.portal.analogsForbidden', 'Аналоги не допускаются')}
              {' · '}
              {tender.allow_partial
                ? t('tender.portal.partialAllowed', 'можно предложить часть позиций')
                : t('tender.portal.partialForbidden', 'нужно предложить все позиции полностью')}
            </dd>
          </div>
        </dl>
        {tender.files.length > 0 && (
          <ul className="space-y-1.5">
            {tender.files.map((file) => (
              <li key={file.id}>
                <a href={portalApi.fileHref(token, file.id)} className="inline-flex items-center gap-1.5 text-sm text-primary hover:underline">
                  <Download className="h-4 w-4" />
                  {file.name}
                </a>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">{t('tender.portal.items', 'Позиции')}</h2>
        {tender.items.map((item, index) => (
          <LineCard
            key={item.id}
            item={item}
            line={form.lines[index]}
            onChange={(line) => set('lines', form.lines.map((other, i) => (i === index ? line : other)))}
            readOnly={readOnly}
            allowAnalogs={tender.allow_analogs}
            currency={currency}
            error={shown(`line:${item.id}`)}
          />
        ))}
        {shown('lines') && <p className="text-sm text-destructive">{shown('lines')}</p>}
      </section>

      {form.delivery && <Section title={t('tender.portal.delivery', 'Доставка до объекта')}>{extraEditor('delivery', form.delivery)}</Section>}
      {form.works && <Section title={t('tender.portal.works', 'СМР')}>{extraEditor('works', form.works)}</Section>}

      <Section title={t('tender.portal.terms', 'Условия предложения')}>
        {readOnly ? (
          <dl className="grid gap-2 text-sm">
            <div><dt className="text-muted-foreground">{t('tender.portal.offerCurrency', 'Валюта предложения')}</dt><dd>{form.currency_code}</dd></div>
            <div><dt className="text-muted-foreground">{t('tender.portal.vat', 'НДС')}</dt><dd>{form.with_vat ? `${form.vat_rate} %` : t('tender.portal.noVat', 'Без НДС')}</dd></div>
            <div><dt className="text-muted-foreground">{t('tender.portal.validUntil', 'Предложение действует до')}</dt><dd>{formatDate(form.valid_until || null)}</dd></div>
            <div><dt className="text-muted-foreground">{t('tender.portal.scheme', 'Схема оплаты')}</dt><dd>{describeScheme(offer.payment_scheme, (key, fallback, options) => t(key, fallback, options))}</dd></div>
            {form.extra_terms && <div><dt className="text-muted-foreground">{t('tender.portal.extraTerms', 'Дополнительные условия')}</dt><dd className="whitespace-pre-wrap">{form.extra_terms}</dd></div>}
          </dl>
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="portal-currency">{t('tender.portal.offerCurrency', 'Валюта предложения')}</Label>
                <Input
                  id="portal-currency" className="h-11 text-base uppercase" maxLength={3} value={form.currency_code}
                  onChange={(event) => set('currency_code', event.target.value.toUpperCase())}
                />
              </div>
              <div className="space-y-1.5">
                <Label>{t('tender.portal.validUntil', 'Предложение действует до')}</Label>
                <DateInput
                  value={form.valid_until} min={today()} invalid={Boolean(shown('valid_until'))}
                  aria-label={t('tender.portal.validUntil', 'Предложение действует до')}
                  onChange={(value) => set('valid_until', value)}
                />
              </div>
            </div>
            {shown('valid_until') && <p className="text-sm text-destructive">{shown('valid_until')}</p>}
            <div className="flex items-center gap-2">
              <Checkbox id="portal-with-vat" checked={form.with_vat} onCheckedChange={(value) => set('with_vat', value === true)} />
              <Label htmlFor="portal-with-vat" className="text-base font-normal">{t('tender.portal.withVat', 'Цены с НДС')}</Label>
            </div>
            {form.with_vat && (
              <div className="max-w-40 space-y-1.5">
                <Label htmlFor="portal-vat-rate">{t('tender.portal.vatRate', 'Ставка НДС, %')}</Label>
                <Input
                  id="portal-vat-rate" inputMode="decimal" className="h-11 text-base" value={form.vat_rate}
                  onChange={(event) => set('vat_rate', event.target.value)}
                />
                {shown('vat_rate') && <p className="text-sm text-destructive">{shown('vat_rate')}</p>}
              </div>
            )}
            <div className="space-y-1.5">
              <Label>{t('tender.portal.scheme', 'Схема оплаты')}</Label>
              <PaymentSchemeField
                value={form.scheme}
                onChange={(scheme) => set('scheme', scheme)}
                errors={{
                  ...(showErrors ? errors : {}),
                  ...Object.fromEntries(['kind', 'advance_pct', 'postpay_days']
                    .filter((key) => serverErrors[key]).map((key) => [key, serverErrors[key]])),
                }}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="portal-extra-terms">{t('tender.portal.extraTerms', 'Дополнительные условия')}</Label>
              <Textarea
                id="portal-extra-terms" className="text-base" value={form.extra_terms} maxLength={4000}
                onChange={(event) => set('extra_terms', event.target.value)}
              />
            </div>
          </div>
        )}
        <p className="text-base font-semibold">
          {t('tender.portal.total', 'Итого по предложению')}: {formatMoney(offerTotal(form), currency)}
        </p>
      </Section>

      <FilesSection token={token} readOnly={readOnly} onFailure={handled} />

      <RequisitesSection
        value={form.requisites}
        onChange={(requisites) => set('requisites', requisites)}
        readOnly={!requisitesEditable}
        errors={showErrors ? { ...errors, ...serverErrors } : serverErrors}
      />

      {!readOnly && (
        <div className="space-y-3">
          {needsConsent && (
            <div className="flex items-start gap-2 rounded-lg border p-3">
              <Checkbox id="portal-consent" checked={consent} onCheckedChange={(value) => setConsent(value === true)} className="mt-1" />
              <Label htmlFor="portal-consent" className="text-sm font-normal leading-relaxed">
                {t('tender.portal.consent',
                  'Согласен на обработку персональных данных, указанных в предложении, для участия в тендере.')}
              </Label>
            </div>
          )}
          <div className="grid gap-2">
            <Button
              type="button" size="lg" className="w-full"
              disabled={Boolean(pending) || (needsConsent && !consent)}
              onClick={submit}
            >
              {pending === 'submit' && <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />}
              {t('tender.portal.submit', 'Отправить предложение')}
            </Button>
            <Button type="button" size="lg" variant="outline" className="w-full" disabled={Boolean(pending)} onClick={() => { void save(); }}>
              {pending === 'save' && <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />}
              {t('tender.portal.saveDraft', 'Сохранить черновик')}
            </Button>
            {submitted && (
              <Button type="button" size="lg" variant="outline" className="w-full" disabled={Boolean(pending)} onClick={() => setDialog('withdraw')}>
                {t('tender.portal.withdraw', 'Отозвать предложение')}
              </Button>
            )}
            <Button type="button" size="lg" variant="ghost" className="w-full" disabled={Boolean(pending)} onClick={() => setDialog('decline')}>
              {t('tender.portal.decline', 'Отказаться от участия')}
            </Button>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={dialog === 'withdraw'}
        onOpenChange={(open) => setDialog(open ? 'withdraw' : null)}
        title={t('tender.portal.withdrawConfirm', 'Отозвать отправленное предложение?')}
        description={t('tender.portal.withdrawHint', 'Заказчик не увидит его при вскрытии. До срока можно отправить новое.')}
        confirmLabel={t('tender.portal.withdrawShort', 'Отозвать')}
        pending={pending === 'withdraw'}
        onConfirm={() => { void withdraw(); }}
      />
      <ConfirmDialog
        open={dialog === 'decline'}
        onOpenChange={(open) => setDialog(open ? 'decline' : null)}
        title={t('tender.portal.declineConfirm', 'Отказаться от участия в тендере?')}
        description={t('tender.portal.declineHint', 'Черновик предложения будет удалён. Причина поможет заказчику.')}
        confirmLabel={t('tender.portal.declineShort', 'Отказаться')}
        variant="destructive"
        commentMin={REASON_MIN}
        commentLabel={t('tender.portal.declineReason', 'Причина отказа')}
        pending={pending === 'decline'}
        onConfirm={(reason) => { void decline(reason); }}
      />
    </div>
  );
}
