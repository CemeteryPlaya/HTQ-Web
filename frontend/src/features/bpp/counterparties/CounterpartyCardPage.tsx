/**
 * Карточка контрагента (ТЗ §18): реквизиты, банковские счета, история
 * изменений; действия ФД — блокировка с причиной (≥ 10 символов, BR-060),
 * разблокировка, архив и ручная метка «Проверенный».
 *
 * Кнопки — из `allowed_actions` карточки (сервер решает по правам и
 * статусу), и дополнительно по узлам прав на фронте: СН и ПМ заводят
 * контрагентов, но блокировать не могут, и кнопку им не показываем, даже
 * если бы сервер ошибся в списке. Судья всё равно сервер (403 E-ACC-01).
 *
 * `BppDocumentShell` здесь не подходит: у справочника нет согласования и
 * файлов, а вкладка «Файлы» оболочки неотключаема (владельца файлов
 * `bpp.counterparty` в `apps.files` нет). Шапка и кнопки собраны из тех же
 * частей — `StatusBadge`, `DocumentActionButton`, `HistoryTab`.
 */
import { useCallback, useMemo, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft, Ban, Pencil } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { usePermissions } from '@/hooks/usePermissions';
import { errorStatus, reportApiError } from '@/lib/apiError';

import { DocumentActionButton, type BppDocumentAction } from '../core/DocumentActionButton';
import { HistoryTab } from '../core/HistoryTab';
import { StatusBadge } from '../core/StatusBadge';
import { useRegistryBackHref } from '../core/registryBack';
import { useIdempotentAction } from '../core/useIdempotentAction';
import { formatDateTime } from '../format';

import {
  COUNTERPARTIES_BASE, counterpartyApi, counterpartyKey,
  type CounterpartyAction, type CounterpartyCard,
} from './api';
import { BankAccountsPanel } from './BankAccountsPanel';
import { CounterpartyForm } from './CounterpartyForm';
import { historyFieldLabels, kindLabel, regNumberLabel } from './labels';
import { VerifiedMark } from './VerifiedMark';

/** Тип объекта журнала изменений контрагента (`audit` сервера). */
const HISTORY_TYPE = 'bpp.counterparty';
const BLOCK_REASON_MIN = 10;

type VerifiedChoice = 'auto' | 'yes' | 'no';
const choiceOf = (value: boolean | null): VerifiedChoice =>
  value === null || value === undefined ? 'auto' : value ? 'yes' : 'no';
const valueOf = (choice: VerifiedChoice): boolean | null =>
  choice === 'auto' ? null : choice === 'yes';

function VerifiedControl({ card, onSaved }: { card: CounterpartyCard; onSaved: (c: CounterpartyCard) => void }) {
  const { t } = useTranslation();
  const [choice, setChoice] = useState<VerifiedChoice | null>(null);
  // Выбранное значение — через ref: `run` хука не принимает аргументов, а
  // состояние к моменту запроса ещё не применилось бы.
  const target = useRef<boolean | null>(null);
  const action = useIdempotentAction((key) =>
    counterpartyApi.setVerified(card.id, key, { version: card.version, verified: target.current }));

  const change = (next: VerifiedChoice) => {
    setChoice(next);
    target.current = valueOf(next);
    action.run().then(
      (saved) => { setChoice(null); onSaved(saved); },
      (error: unknown) => {
        setChoice(null);
        reportApiError(error, t('bpp.counterparties.verifiedFailed', 'Не удалось изменить метку'));
      },
    );
  };

  return (
    <div className="flex items-center gap-2">
      <span className="text-sm text-muted-foreground">
        {t('bpp.counterparties.verifiedTitle', 'Метка')}
      </span>
      <Select
        value={choice ?? choiceOf(card.verified_override)}
        onValueChange={(value) => change(value as VerifiedChoice)}
        disabled={action.pending}
      >
        <SelectTrigger className="h-9 w-72" aria-label={t('bpp.counterparties.verifiedControl', 'Метка «Проверенный»')}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="auto">
            {t('bpp.counterparties.verifiedAuto', 'По порогу ({{count}} удачных документа)', {
              count: card.verified_threshold,
            })}
          </SelectItem>
          <SelectItem value="yes">{t('bpp.counterparties.verifiedYes', 'Проверенный — решение ФД')}</SelectItem>
          <SelectItem value="no">{t('bpp.counterparties.verifiedNo', 'Не проверен — решение ФД')}</SelectItem>
        </SelectContent>
      </Select>
    </div>
  );
}

function Detail({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="text-sm">{value || '—'}</dd>
    </div>
  );
}

export function CounterpartyCardPage() {
  const { t } = useTranslation();
  const { id = '' } = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const permissions = usePermissions();
  const [tab, setTab] = useState('details');
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  // Назад — на то место реестра, откуда открыли карточку (`registryBack.ts`).
  const backHref = useRegistryBackHref(COUNTERPARTIES_BASE);

  const { data: card, isLoading, error } = useQuery({
    queryKey: counterpartyKey(id),
    queryFn: () => counterpartyApi.get(id),
    enabled: Boolean(id),
  });

  const apply = useCallback((saved: CounterpartyCard) => {
    queryClient.setQueryData(counterpartyKey(saved.id), saved);
    void queryClient.invalidateQueries({ queryKey: ['bpp', 'history', HISTORY_TYPE, saved.id] });
    void queryClient.invalidateQueries({ queryKey: ['bpp', 'registry', 'counterparties'] });
  }, [queryClient]);

  const reload = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: counterpartyKey(id) });
    void queryClient.invalidateQueries({ queryKey: ['bpp', 'history', HISTORY_TYPE, id] });
  }, [queryClient, id]);

  const onPendingChange = useCallback((key: string, pending: boolean) => {
    setBusy((current) => (current[key] === pending ? current : { ...current, [key]: pending }));
  }, []);
  const onDone = useCallback(() => undefined, []);
  const countryCode = card?.country_code ?? '';
  const fieldLabels = useMemo(() => historyFieldLabels(t, countryCode), [t, countryCode]);

  const back = (
    <Link to={backHref} className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
      <ArrowLeft className="h-4 w-4" />
      {t('bpp.counterparties.backToList', 'К списку контрагентов')}
    </Link>
  );

  if (isLoading) return <Skeleton className="h-64 w-full" />;
  if (error || !card) {
    return (
      <div className="space-y-4">
        {back}
        <p className="rounded-2xl border bg-card p-8 text-center text-sm text-muted-foreground">
          {errorStatus(error) === 404
            ? t('bpp.counterparties.notFound', 'Контрагент не найден')
            : t('bpp.counterparties.loadError', 'Не удалось загрузить карточку. Обновите страницу.')}
        </p>
      </div>
    );
  }

  // Сервер назвал действия; фронт дополнительно сверяет узлы прав.
  const canBlockNode = permissions.can('bpp.counterparties.block', 'edit');
  const canEditNode = permissions.can('bpp.counterparties', 'edit');
  const allowed = (action: CounterpartyAction) => card.allowed_actions.includes(action) && (
    action === 'edit' || action === 'add_account' ? canEditNode : canBlockNode
  );

  const statusActions: Partial<Record<CounterpartyAction, BppDocumentAction>> = {
    block: {
      label: t('bpp.counterparties.block', 'Заблокировать'),
      variant: 'destructive',
      confirm: {
        title: t('bpp.counterparties.blockTitle', 'Заблокировать контрагента?'),
        description: t(
          'bpp.counterparties.blockHint',
          'Заблокированного контрагента нельзя выбрать в новых договорах и счетах. Укажите причину — её увидят авторы документов.',
        ),
        commentMin: BLOCK_REASON_MIN,
      },
      run: (key, reason) => counterpartyApi
        .block(card.id, key, { version: card.version, reason: reason ?? '' }).then(apply),
    },
    unblock: {
      label: t('bpp.counterparties.unblock', 'Разблокировать'),
      variant: 'outline',
      confirm: { title: t('bpp.counterparties.unblockTitle', 'Разблокировать контрагента?') },
      run: (key) => counterpartyApi.unblock(card.id, key, { version: card.version }).then(apply),
    },
    archive: {
      label: t('bpp.counterparties.archive', 'В архив'),
      variant: 'outline',
      confirm: {
        title: t('bpp.counterparties.archiveTitle', 'Перевести контрагента в архив?'),
        description: t(
          'bpp.counterparties.archiveHint',
          'Архивный контрагент не предлагается в новых документах и остаётся в старых. Вернуть его из архива нельзя.',
        ),
      },
      run: (key) => counterpartyApi.archive(card.id, key, { version: card.version }).then(apply),
    },
  };
  const visibleStatusActions = (Object.keys(statusActions) as CounterpartyAction[]).filter(allowed);
  const anyBusy = Object.values(busy).some(Boolean);

  return (
    <div className="space-y-6">
      {back}
      <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-2xl font-bold tracking-tight">{card.short_name || card.name}</h2>
            <StatusBadge kind="counterparty" status={card.status} />
            <VerifiedMark isVerified={card.is_verified} override={card.verified_override} />
          </div>
          <p className="text-sm text-muted-foreground">
            {regNumberLabel(t, card.country_code)}{' '}
            <span className="font-mono">{card.reg_number}</span>
            {' · '}{card.country_code}{' · '}{kindLabel(t, card.kind)}
          </p>
        </div>

        <div className="flex flex-wrap gap-2 sm:justify-end">
          {allowed('edit') && !editing && (
            <Button
              variant="outline"
              disabled={anyBusy}
              onClick={() => { setTab('details'); setEditing(true); }}
            >
              <Pencil className="mr-1.5 h-4 w-4" />
              {t('bpp.counterparties.edit', 'Изменить')}
            </Button>
          )}
          {visibleStatusActions.map((key) => (
            <DocumentActionButton
              key={key}
              actionKey={key}
              action={statusActions[key]!}
              disabled={anyBusy && !busy[key]}
              onPendingChange={onPendingChange}
              onDone={onDone}
            />
          ))}
        </div>
      </header>

      {card.status === 'blocked' && (
        <div role="note" className="flex gap-2 rounded-lg border border-red-300 bg-red-50 p-3 text-sm dark:border-red-900 dark:bg-red-950/40">
          <Ban className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
          <p>
            {t('bpp.counterparties.blockedNote', 'Заблокирован {{date}}: {{reason}}', {
              date: formatDateTime(card.blocked_at),
              reason: card.block_reason || '—',
            })}
          </p>
        </div>
      )}

      {allowed('verified') && <VerifiedControl card={card} onSaved={apply} />}

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="details">{t('bpp.counterparties.tabDetails', 'Реквизиты')}</TabsTrigger>
          <TabsTrigger value="accounts">
            {t('bpp.counterparties.tabAccounts', 'Банковские счета')}
          </TabsTrigger>
          <TabsTrigger value="history">{t('bpp.document.tabHistory', 'История изменений')}</TabsTrigger>
        </TabsList>

        <TabsContent value="details">
          <div className="rounded-2xl border bg-card p-4 sm:p-6">
            {editing ? (
              <CounterpartyForm
                card={card}
                onSaved={(saved) => { apply(saved); setEditing(false); }}
                onCancel={() => setEditing(false)}
              />
            ) : (
              <dl className="grid gap-4 sm:grid-cols-2">
                <Detail label={t('bpp.counterparties.name', 'Наименование')} value={card.name} />
                <Detail label={t('bpp.counterparties.shortName', 'Краткое наименование')} value={card.short_name} />
                <Detail
                  label={t('bpp.counterparties.vatPayer', 'Плательщик НДС')}
                  value={card.is_vat_payer
                    ? [t('bpp.common.yes', 'Да'), card.vat_cert_series, card.vat_cert_number]
                      .filter(Boolean).join(' · ')
                    : t('bpp.common.no', 'Нет')}
                />
                <Detail
                  label={t('bpp.counterparties.successful', 'Удачных документов')}
                  value={`${card.successful_documents} / ${card.verified_threshold}`}
                />
                <Detail label={t('bpp.counterparties.contactPerson', 'Контактное лицо')} value={card.contact_person} />
                <Detail label={t('bpp.counterparties.phone', 'Телефон')} value={card.phone} />
                <Detail label={t('bpp.counterparties.email', 'E-mail')} value={card.email} />
                <Detail label={t('bpp.counterparties.legalAddress', 'Юридический адрес')} value={card.legal_address} />
                <Detail label={t('bpp.counterparties.updatedAt', 'Изменён')} value={formatDateTime(card.updated_at)} />
                <Detail label={t('bpp.counterparties.ext1c', 'Код в 1С')} value={card.ext_1c_ref} />
              </dl>
            )}
          </div>
        </TabsContent>

        <TabsContent value="accounts">
          <BankAccountsPanel
            counterpartyId={card.id}
            accounts={card.bank_accounts}
            canEdit={allowed('add_account')}
            onChanged={reload}
          />
        </TabsContent>

        <TabsContent value="history">
          <HistoryTab objectType={HISTORY_TYPE} objectId={card.id} fieldLabels={fieldLabels} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

export default CounterpartyCardPage;
