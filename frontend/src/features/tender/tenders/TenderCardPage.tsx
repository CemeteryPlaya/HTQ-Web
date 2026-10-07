/**
 * Карточка тендера (`/tender/tenders/:id`, T2.3; план §4.2–4.4).
 *
 * - Действия — по `allowed_actions` сервера: `edit` — правка черновика
 *   (срок, валюта, условия, проверяющий качества, схема оплаты 1–3);
 *   `publish` — публикация с диалогом ссылок; `extend` — продление срока;
 *   `cancel` — отмена с причиной от 10 символов; `invite` — участники и
 *   действия по приглашению (отзыв, перевыпуск, сброс устройства).
 * - Ссылки видны один раз (`LinksDialog`): в кэш не кладутся.
 * - Счётчики «отправлено / открыто / подано» — из ответа сервера (TND-013).
 * - Отказ 409 `E-CON-01` — плашка «тендер уже изменили» с «Обновить».
 */
import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router-dom';
import { toast } from 'sonner';
import { ArrowLeft, CalendarClock, Loader2, UserPlus } from 'lucide-react';

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
import { DocumentActionButton, type BppDocumentAction } from '@/features/bpp/core/DocumentActionButton';
import { formatDateTime } from '@/features/bpp/format';
import { refdataApi, refdataKeys } from '@/features/bpp/refdata/api';
import { errorStatus } from '@/lib/apiError';

import { ConflictAlert } from '../core/ConflictAlert';
import { isConflict } from '../core/conflict';
import { fieldErrorsOf, reportFormError } from '../core/fieldErrors';
import { isoToLocalInput, localInputToIso } from '../core/datetime';
import { TenderStatusBadge } from '../core/TenderStatusBadge';
import { tenderRequestHref } from '../requests/api';
import {
  TENDERS_BASE, tenderKeys, tendersApi, type Invitation, type TenderCard, type TenderPatch,
} from './api';
import { AddParticipantDialog } from './AddParticipantDialog';
import { ExtendDialog } from './ExtendDialog';
import { LinksDialog, type ShownLink } from './LinksDialog';
import { PaymentSchemeField } from './PaymentSchemeField';
import { ReviewerPicker } from './ReviewerPicker';
import {
  describeScheme, schemeDraftOf, schemeErrors, schemeInput, type SchemeDraft,
} from './schemes';

const REASON_MIN = 10;
/** Приглашения в этих статусах действий не имеют. */
const CLOSED_INVITATIONS = ['revoked', 'expired', 'declined', 'awarded', 'not_awarded'];

interface DraftForm {
  deadline: string;
  currency_code: string;
  delivery_terms: string;
  reviewer_id: number | null;
}

const draftOf = (card: TenderCard): DraftForm => ({
  deadline: isoToLocalInput(card.deadline_at),
  currency_code: card.currency_code || 'KZT',
  delivery_terms: card.delivery_terms,
  reviewer_id: card.quality_reviewer_user_id,
});

function Detail({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="space-y-0.5">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="text-sm">{children}</dd>
    </div>
  );
}

function BackToTenders() {
  const { t } = useTranslation();
  return (
    <Link to={TENDERS_BASE} className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
      <ArrowLeft className="h-4 w-4" />
      {t('tender.tenders.back', 'К тендерам')}
    </Link>
  );
}

export function TenderCardPage() {
  const { t } = useTranslation();
  const { id = '' } = useParams<{ id: string }>();
  const queryClient = useQueryClient();

  const { data: card, isLoading, error, refetch } = useQuery({
    queryKey: tenderKeys.card(id),
    queryFn: () => tendersApi.get(id),
    enabled: Boolean(id),
  });
  const editable = Boolean(card?.allowed_actions.includes('edit'));
  const currencies = useQuery({
    queryKey: refdataKeys.list('currencies', { active: true }),
    queryFn: () => refdataApi.currencies.list({ active: true }),
    enabled: editable,
    staleTime: 10 * 60 * 1000,
  });

  const [form, setForm] = useState<DraftForm | null>(null);
  const [scheme, setScheme] = useState<SchemeDraft>(() => schemeDraftOf(null));
  const [reviewerLabel, setReviewerLabel] = useState<string | null>(null);
  const [showErrors, setShowErrors] = useState(false);
  const [saving, setSaving] = useState(false);
  // Отказ сервера по полям шапки и схемы (`deadline_at`, `kind`, …).
  const [serverErrors, setServerErrors] = useState<Record<string, string>>({});
  const [conflict, setConflict] = useState(false);
  const [links, setLinks] = useState<ShownLink[]>([]);
  const [adding, setAdding] = useState(false);
  const [extending, setExtending] = useState(false);
  const [busy, setBusy] = useState<Record<string, boolean>>({});

  const stamp = card ? `${card.id}:${card.version}` : '';
  useEffect(() => {
    if (!card) return;
    setForm(draftOf(card));
    setScheme(schemeDraftOf(card.payment_scheme));
    setReviewerLabel(card.quality_reviewer_name ?? null);
    setShowErrors(false);
    setServerErrors({});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stamp]);

  const onPendingChange = useCallback((key: string, pending: boolean) => {
    setBusy((current) => (current[key] === pending ? current : { ...current, [key]: pending }));
  }, []);
  const onDone = useCallback(() => undefined, []);

  if (isLoading) return <Skeleton className="h-64 w-full" />;
  if (error || !card) {
    return (
      <div className="space-y-2">
        <BackToTenders />
        <p className="text-sm text-muted-foreground">
          {errorStatus(error) === 404
            ? t('tender.tenders.notFound', 'Тендер не найден или недоступен.')
            : t('tender.tenders.loadFailed', 'Не удалось загрузить тендер.')}
        </p>
      </div>
    );
  }

  const allowed = card.allowed_actions;
  const anyBusy = saving || Object.values(busy).some(Boolean);
  const nameOf = new Map(card.invitations.map((row) => [row.id, row]));

  const refresh = (saved?: unknown) => {
    setConflict(false);
    if (saved && typeof saved === 'object' && 'invitations' in saved) {
      queryClient.setQueryData(tenderKeys.card(card.id), saved);
    }
    void queryClient.invalidateQueries({ queryKey: tenderKeys.card(card.id) });
    void queryClient.invalidateQueries({ queryKey: [...tenderKeys.all, 'list'] });
  };
  const fail = (failure: unknown) => {
    if (isConflict(failure)) setConflict(true);
    setServerErrors(fieldErrorsOf(failure, t('tender.common.invalidFormat', 'Неверный формат значения')));
    reportFormError(
      failure,
      t('tender.tenders.actionFailed', 'Не удалось выполнить действие'),
      t('tender.common.invalidFormatToast', 'Сервер не принял формат некоторых полей — проверьте выделенные поля.'),
    );
  };
  const guarded = (run: BppDocumentAction['run']): BppDocumentAction['run'] => async (key, comment) => {
    try {
      return await run(key, comment);
    } catch (failure) {
      if (isConflict(failure)) setConflict(true);
      throw failure;
    }
  };
  const showLinks = (issued: { invitation_id: string; link: string }[]) =>
    setLinks(issued.map(({ invitation_id: invitationId, link }) => ({
      invitationId,
      link,
      name: nameOf.get(invitationId)?.name ?? '',
      email: nameOf.get(invitationId)?.email ?? '',
    })));

  // ── Правка черновика ────────────────────────────────────────────────
  const baseline = draftOf(card);
  const formDirty = form !== null && JSON.stringify(form) !== JSON.stringify(baseline);
  const schemeDirty = JSON.stringify(scheme) !== JSON.stringify(schemeDraftOf(card.payment_scheme));
  const translate = (key: string, fallback: string, options?: Record<string, unknown>) =>
    t(key, fallback, options);
  const errors = schemeDirty ? schemeErrors(scheme, translate) : {};

  const save = async () => {
    if (!form) return;
    setShowErrors(true);
    if (Object.keys(errors).length > 0) return;
    setSaving(true);
    setServerErrors({});
    try {
      let saved: TenderCard = card;
      if (formDirty) {
        const body: TenderPatch = { version: card.version };
        if (form.deadline !== baseline.deadline) body.deadline_at = localInputToIso(form.deadline);
        if (form.currency_code !== baseline.currency_code) body.currency_code = form.currency_code;
        if (form.delivery_terms !== baseline.delivery_terms) body.delivery_terms = form.delivery_terms.trim();
        if (form.reviewer_id !== baseline.reviewer_id) body.quality_reviewer_user_id = form.reviewer_id;
        saved = await tendersApi.save(card.id, body);
      }
      if (schemeDirty) saved = await tendersApi.setScheme(card.id, schemeInput(scheme));
      refresh(saved);
      toast.success(t('tender.tenders.saved', 'Тендер сохранён'));
    } catch (failure) {
      fail(failure);
    } finally {
      setSaving(false);
    }
  };

  // ── Действия жизненного цикла ───────────────────────────────────────
  const publishBlockers = [
    card.invitations.every((row) => row.status === 'revoked')
      && t('tender.tenders.needParticipant', 'Добавьте хотя бы одного участника'),
    !card.payment_scheme && t('tender.tenders.needScheme', 'Задайте и сохраните схему оплаты'),
    !card.deadline_at && t('tender.tenders.needDeadline', 'Укажите и сохраните срок приёма предложений'),
    (formDirty || schemeDirty) && t('tender.tenders.saveFirst', 'Сохраните изменения перед публикацией'),
  ].filter((item): item is string => Boolean(item));

  const publish: BppDocumentAction = {
    label: t('tender.tenders.publish', 'Опубликовать'),
    confirm: {
      title: t('tender.tenders.publishConfirm', 'Опубликовать тендер?'),
      description: t('tender.tenders.publishHint',
        'Участникам будут выпущены ссылки на подачу предложений. Ссылки покажутся один раз — скопируйте их сразу.'),
    },
    run: guarded(async (key) => {
      const issued = await tendersApi.publish(card.id, key, card.version);
      refresh();
      showLinks(issued);
    }),
  };
  const cancel: BppDocumentAction = {
    label: t('tender.tenders.cancel', 'Отменить тендер'),
    variant: 'outline',
    confirm: {
      title: t('tender.tenders.cancelConfirm', 'Отменить тендер? Все ссылки участников перестанут работать.'),
      commentMin: REASON_MIN,
    },
    run: guarded(async (key, comment) =>
      refresh(await tendersApi.cancel(card.id, key, comment ?? '', card.version))),
  };

  const invitationActions = (row: Invitation): [string, BppDocumentAction][] => {
    if (!allowed.includes('invite') || CLOSED_INVITATIONS.includes(row.status)) return [];
    const actions: [string, BppDocumentAction][] = [];
    if (card.status === 'intake' && row.status !== 'created') {
      actions.push([`reissue:${row.id}`, {
        label: t('tender.tenders.reissue', 'Перевыпустить ссылку'),
        variant: 'outline',
        confirm: {
          title: t('tender.tenders.reissueConfirm', 'Перевыпустить ссылку для {{name}}? Прежняя перестанет работать.', { name: row.name }),
        },
        run: guarded(async (key) => {
          const link = await tendersApi.reissue(card.id, row.id, key);
          refresh();
          setLinks([{ invitationId: row.id, name: row.name, email: row.email, link }]);
        }),
      }]);
      actions.push([`reset:${row.id}`, {
        label: t('tender.tenders.resetDevice', 'Сбросить устройство'),
        variant: 'outline',
        confirm: {
          title: t('tender.tenders.resetDeviceConfirm', 'Сбросить привязку устройства для {{name}}?', { name: row.name }),
          description: t('tender.tenders.resetDeviceHint',
            'Участник сможет открыть ту же ссылку на другом устройстве.'),
        },
        run: guarded(async (key) => {
          await tendersApi.resetDevice(card.id, row.id, key);
          refresh();
          toast.success(t('tender.tenders.resetDone', 'Привязка устройства сброшена'));
        }),
      }]);
    }
    actions.push([`revoke:${row.id}`, {
      label: t('tender.tenders.revoke', 'Отозвать'),
      variant: 'outline',
      confirm: {
        title: t('tender.tenders.revokeConfirm', 'Отозвать приглашение {{name}}? Его ссылка перестанет работать.', { name: row.name }),
      },
      run: guarded(async (key) => {
        await tendersApi.revoke(card.id, row.id, key);
        refresh();
      }),
    }]);
    return actions;
  };

  const canInvite = allowed.includes('invite') && ['draft', 'intake'].includes(card.status);
  const counters: [string, number][] = [
    [t('tender.tenders.countSent', 'Отправлено'), card.counters.sent],
    [t('tender.tenders.countOpened', 'Открыто'), card.counters.opened],
    [t('tender.tenders.countSubmitted', 'Подано'), card.counters.submitted],
  ];

  return (
    <div className="space-y-6">
      <BackToTenders />

      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-2xl font-bold">
          {t('tender.tenders.cardTitle', 'Тендер {{number}}', { number: card.number })}
        </h2>
        <TenderStatusBadge kind="tender" status={card.status} />
        {card.round > 1 && (
          <span className="text-sm text-muted-foreground">
            {t('tender.tenders.round', 'Раунд {{round}}', { round: card.round })}
          </span>
        )}
      </div>
      <p className="text-sm">
        {t('tender.tenders.request', 'Заявка')}:{' '}
        <Link to={tenderRequestHref(card.request_id)} className="text-primary hover:underline">
          {card.request_number}
        </Link>
      </p>

      {conflict && (
        <ConflictAlert
          message={t('tender.tenders.conflict',
            'Тендер уже изменили — в другом окне или другой пользователь. Обновите его и повторите действие.')}
          onReload={() => { setConflict(false); void refetch(); }}
        />
      )}
      {card.cancel_reason && (
        <p className="text-sm text-muted-foreground">
          {t('tender.tenders.cancelReason', 'Причина отмены')}: {card.cancel_reason}
        </p>
      )}

      <dl data-testid="tender-counters" className="grid grid-cols-3 gap-3">
        {counters.map(([label, value]) => (
          <div key={label} className="rounded-2xl border bg-card p-3">
            <dt className="text-xs text-muted-foreground">{label}</dt>
            <dd className="text-2xl font-semibold">{value}</dd>
          </div>
        ))}
      </dl>

      <div className="flex flex-wrap items-center gap-2">
        {allowed.includes('publish') && (
          <DocumentActionButton
            actionKey="publish" action={publish}
            disabled={publishBlockers.length > 0 || (anyBusy && !busy.publish)}
            onPendingChange={onPendingChange} onDone={onDone}
          />
        )}
        {allowed.includes('extend') && (
          <Button type="button" variant="outline" disabled={anyBusy} onClick={() => setExtending(true)}>
            <CalendarClock className="mr-1.5 h-4 w-4" />
            {t('tender.tenders.extendButton', 'Продлить срок')}
          </Button>
        )}
        {allowed.includes('cancel') && (
          <DocumentActionButton
            actionKey="cancel" action={cancel} disabled={anyBusy && !busy.cancel}
            onPendingChange={onPendingChange} onDone={onDone}
          />
        )}
      </div>
      {allowed.includes('publish') && publishBlockers.length > 0 && (
        <ul className="list-disc space-y-0.5 pl-5 text-xs text-muted-foreground">
          {publishBlockers.map((text) => <li key={text}>{text}</li>)}
        </ul>
      )}

      {editable && form ? (
        <section className="space-y-4 rounded-2xl border bg-card p-4">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <div className="space-y-1.5">
              <Label htmlFor="tender-deadline">{t('tender.tenders.deadline', 'Срок приёма предложений')}</Label>
              <Input
                id="tender-deadline" type="datetime-local" value={form.deadline}
                onChange={(event) => setForm({ ...form, deadline: event.target.value })}
              />
              {serverErrors.deadline_at && <p className="text-xs text-destructive">{serverErrors.deadline_at}</p>}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="tender-currency">{t('tender.tenders.currency', 'Валюта')}</Label>
              <Select value={form.currency_code} onValueChange={(value) => setForm({ ...form, currency_code: value })}>
                <SelectTrigger id="tender-currency"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {[...new Set([form.currency_code, ...(currencies.data ?? []).map((row) => row.code)])].map((code) => (
                    <SelectItem key={code} value={code}>{code}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {serverErrors.currency_code && <p className="text-xs text-destructive">{serverErrors.currency_code}</p>}
            </div>
            <div className="space-y-1.5">
              <Label>{t('tender.tenders.reviewer', 'Проверяющий качества выбора')}</Label>
              <ReviewerPicker
                value={form.reviewer_id}
                valueLabel={reviewerLabel}
                onChange={(reviewerId, label) => { setForm({ ...form, reviewer_id: reviewerId }); setReviewerLabel(label); }}
              />
              {serverErrors.quality_reviewer_user_id && (
                <p className="text-xs text-destructive">{serverErrors.quality_reviewer_user_id}</p>
              )}
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="tender-terms">{t('tender.tenders.deliveryTerms', 'Условия поставки')}</Label>
            <Textarea
              id="tender-terms" value={form.delivery_terms} maxLength={2000}
              onChange={(event) => setForm({ ...form, delivery_terms: event.target.value })}
            />
            {serverErrors.delivery_terms && <p className="text-xs text-destructive">{serverErrors.delivery_terms}</p>}
          </div>
          <div className="space-y-1.5">
            <Label>{t('tender.tenders.scheme', 'Желаемая схема оплаты')}</Label>
            <PaymentSchemeField
              value={scheme}
              onChange={setScheme}
              errors={{
                ...(showErrors ? errors : {}),
                ...Object.fromEntries(['kind', 'advance_pct', 'postpay_days']
                  .filter((key) => serverErrors[key]).map((key) => [key, serverErrors[key]])),
              }}
            />
          </div>
          <Button type="button" disabled={anyBusy || (!formDirty && !schemeDirty)} onClick={() => { void save(); }}>
            {saving && <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />}
            {t('tender.tenders.save', 'Сохранить')}
          </Button>
        </section>
      ) : (
        <dl className="grid gap-4 rounded-2xl border bg-card p-4 sm:grid-cols-2 lg:grid-cols-3">
          <Detail label={t('tender.tenders.deadline', 'Срок приёма предложений')}>{formatDateTime(card.deadline_at)}</Detail>
          <Detail label={t('tender.tenders.currency', 'Валюта')}>{card.currency_code}</Detail>
          <Detail label={t('tender.tenders.reviewer', 'Проверяющий качества выбора')}>
            {card.quality_reviewer_user_id === null
              ? t('tender.tenders.reviewerDefault', 'Технический директор (по должности)')
              : card.quality_reviewer_name
                ?? t('tender.tenders.reviewerUser', 'Пользователь № {{id}}', { id: card.quality_reviewer_user_id })}
          </Detail>
          <Detail label={t('tender.tenders.scheme', 'Желаемая схема оплаты')}>
            {describeScheme(card.payment_scheme, translate)}
          </Detail>
          <div className="sm:col-span-2">
            <Detail label={t('tender.tenders.deliveryTerms', 'Условия поставки')}>
              <span className="whitespace-pre-wrap">{card.delivery_terms || '—'}</span>
            </Detail>
          </div>
        </dl>
      )}

      <section className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-lg font-semibold">{t('tender.tenders.participants', 'Участники')}</h3>
          {canInvite && (
            <Button type="button" variant="outline" disabled={anyBusy} onClick={() => setAdding(true)}>
              <UserPlus className="mr-1.5 h-4 w-4" />
              {t('tender.tenders.addParticipant', 'Добавить участника')}
            </Button>
          )}
        </div>
        {card.invitations.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {t('tender.tenders.noParticipants', 'Участников пока нет.')}
          </p>
        ) : (
          <div className="overflow-x-auto rounded-2xl border bg-card">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('tender.tenders.participant', 'Участник')}</TableHead>
                  <TableHead>{t('tender.tenders.email', 'E-mail')}</TableHead>
                  <TableHead>{t('tender.tenders.invitationStatus', 'Статус')}</TableHead>
                  <TableHead>{t('tender.tenders.sentAt', 'Ссылка выпущена')}</TableHead>
                  <TableHead>{t('tender.tenders.openedAt', 'Первое открытие')}</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {card.invitations.map((row) => (
                  <TableRow key={row.id}>
                    <TableCell>
                      <div className="font-medium">{row.name}</div>
                      <div className="text-xs text-muted-foreground">
                        {row.prospect_id
                          ? t('tender.tenders.sourceProspect', 'потенциальный поставщик')
                          : t('tender.tenders.sourceCounterparty', 'контрагент')}
                      </div>
                    </TableCell>
                    <TableCell>{row.email}</TableCell>
                    <TableCell><TenderStatusBadge kind="invitation" status={row.status} /></TableCell>
                    <TableCell>{formatDateTime(row.sent_at)}</TableCell>
                    <TableCell>{formatDateTime(row.first_opened_at)}</TableCell>
                    <TableCell>
                      <div className="flex flex-wrap justify-end gap-1.5">
                        {invitationActions(row).map(([key, action]) => (
                          <DocumentActionButton
                            key={key} actionKey={key} action={action}
                            disabled={anyBusy && !busy[key]}
                            onPendingChange={onPendingChange} onDone={onDone}
                          />
                        ))}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </section>

      <AddParticipantDialog
        open={adding}
        onOpenChange={setAdding}
        onError={fail}
        onInvite={async (key, body) => {
          const added = await tendersApi.invite(card.id, key, body);
          refresh();
          if (added.link) {
            setLinks([{ invitationId: added.id, name: added.name, email: added.email, link: added.link }]);
          }
        }}
      />
      {extending && (
        <ExtendDialog
          open
          currentDeadline={card.deadline_at}
          onOpenChange={setExtending}
          onError={fail}
          onExtend={async (key, deadlineAt) =>
            refresh(await tendersApi.extend(card.id, key, deadlineAt, card.version))}
        />
      )}
      <LinksDialog links={links} onClose={() => setLinks([])} />
    </div>
  );
}

export default TenderCardPage;
