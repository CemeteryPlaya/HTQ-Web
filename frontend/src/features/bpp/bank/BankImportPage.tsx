/**
 * Экран загрузки выписки (ТЗ §11.2, A4.1): `ВП-ГГГГ-0001`, ход разбора,
 * итог, ошибки строк и сами строки.
 *
 * - пока загрузка «Обрабатывается», карточка опрашивается раз в 2 с
 *   (`IMPORT_POLL_MS`); на «Загружена», «Ошибка загрузки» и «Отменена» опрос
 *   останавливается;
 * - итог: строк в файле, списаний, пропущено дублей (BR-075), ошибок;
 * - ошибки строк — списком «Строка 17: не распознана дата „31.02.2026“»:
 *   остальные строки загружены (ТЗ §11.3 п.1). В файле до 10 000 строк, и
 *   ошибок может быть тысячи, поэтому сразу видны первые
 *   `ROW_ERRORS_VISIBLE`, остальные — кнопкой «Показать ещё N»;
 * - таблица строк — страницами с сервера, вкладки сверки «Сопоставлены /
 *   Требуют проверки / Не сопоставлены / Исключены» со счётчиками из
 *   `card.totals` (A4.2); итог — строк, списаний, дублей, ошибок и четыре
 *   группы с суммами (ТЗ §11.2);
 * - действия ФД (`bpp.bank` edit) — «Сверить» (если автосверка упала),
 *   «Отменить загрузку» с числом затронутых счетов, на строках — вручную /
 *   подтвердить / отменить сопоставление / исключить (комментарий не короче
 *   10 символов, BR-060); «Выгрузить результат» — всем, кто видит экран.
 *   После любого действия перечитываются карточка, строки, реестры счетов и
 *   дашборд «Оплаты» (`invalidateRecon`);
 * - «К списку» возвращает на то место реестра, откуда открыли загрузку
 *   (`useRegistryBackHref`); предупреждения о пересечении периода приходят
 *   с формы загрузки состоянием перехода (карточка загрузки их не хранит —
 *   они есть только в ответе `POST bank/imports`);
 * - строки показываются у «Загружена» и «Сверена»: у отменённой загрузки
 *   действующих строк нет (сервер отдаёт только неотменённые).
 */
import { useEffect, useState } from 'react';
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link, useLocation, useParams } from 'react-router-dom';
import { ArrowLeft, ChevronLeft, ChevronRight, Download, FileWarning, Loader2 } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { usePermissions } from '@/hooks/usePermissions';
import { errorStatus, reportApiError } from '@/lib/apiError';

import { useRegistryBackHref } from '../core/registryBack';
import { useIdempotentAction } from '../core/useIdempotentAction';
import { StatusBadge } from '../core/StatusBadge';
import { formatDate, formatDateTime, formatMoney } from '../format';
import { FORMAT_LABELS } from '../settings/templateFields';

import {
  AUTOMATCH_WINDOW_MS, autoMatchRunning, BANK_BASE, bankImportApi, bankImportKey, IMPORT_POLL_MS, invalidateRecon, RECON_TABS,
  TAB_TOTAL_KEY, type BankImportCard, type LineMatch, type ReconTab, type StatementLine,
} from './api';
import { fromCents, toCents } from './amounts';
import { CancelImportDialog } from './CancelImportDialog';
import { CommentDialog } from './CommentDialog';
import { ManualMatchDialog } from './ManualMatchDialog';
import { ReconLinesTable, type LineAction } from './ReconLinesTable';

const LINES_PAGE_SIZE = 50;

const warningsOf = (state: unknown): string[] => {
  const warnings = (state as { warnings?: unknown } | null)?.warnings;
  return Array.isArray(warnings) ? warnings.filter((item): item is string => typeof item === 'string') : [];
};

function Totals({ card }: { card: BankImportCard }) {
  const { t } = useTranslation();
  const items: [string, number][] = [
    [t('bpp.bank.rowsTotal', 'Строк в файле'), card.rows_total],
    [t('bpp.bank.debits', 'Списаний'), card.debits],
    [t('bpp.bank.duplicatesSkipped', 'Пропущено дублей'), card.duplicates],
    [t('bpp.bank.errorsCount', 'Ошибок'), card.errors_count],
  ];
  return (
    <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4" aria-label={t('bpp.bank.totals', 'Итог загрузки')}>
      {items.map(([label, value]) => (
        <div key={label} className="rounded-lg border p-3">
          <dt className="text-xs text-muted-foreground">{label}</dt>
          <dd className="text-xl font-semibold tabular-nums">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

const TAB_LABELS: Record<ReconTab, [string, string]> = {
  matched: ['bpp.bank.tabMatched', 'Сопоставлены'],
  review: ['bpp.bank.tabReview', 'Требуют проверки'],
  unmatched: ['bpp.bank.tabUnmatched', 'Не сопоставлены'],
  excluded: ['bpp.bank.tabExcluded', 'Исключены'],
};

type GroupKey = 'matched' | 'needs_review' | 'unmatched' | 'excluded';
const groupOf = (card: BankImportCard, tab: ReconTab) => card.totals?.[TAB_TOTAL_KEY[tab] as GroupKey];

/** Четыре группы сверки со счётчиком и Σ (ТЗ §11.2), под итогом загрузки. */
function ReconTotalsView({ card }: { card: BankImportCard }) {
  const { t } = useTranslation();
  if (!card.totals) return null;
  const currency = card.account.currency;
  return (
    <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4" aria-label={t('bpp.bank.reconTotals', 'Итог сверки')}>
      {RECON_TABS.map((tab) => {
        const group = groupOf(card, tab);
        return (
          <div key={tab} className="rounded-lg border p-3">
            <dt className="text-xs text-muted-foreground">{t(...TAB_LABELS[tab])}</dt>
            <dd className="text-xl font-semibold tabular-nums">{group?.count ?? 0}</dd>
            <dd className="text-xs tabular-nums text-muted-foreground">
              {formatMoney(group?.amount ?? '0.00', currency)}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}

/** Сколько ошибок строк видно сразу; остальные — по кнопке. */
const ROW_ERRORS_VISIBLE = 200;

function RowErrors({ errors }: { errors: string[] }) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const shown = expanded ? errors : errors.slice(0, ROW_ERRORS_VISIBLE);
  const rest = errors.length - shown.length;
  const label = t('bpp.bank.rowErrors', 'Строки, которые не удалось разобрать');
  return (
    <>
      {/* Ключ — место в списке: одинаковые тексты ошибок сервер не сворачивает. */}
      <ul className="list-disc space-y-0.5 pl-5 text-sm" aria-label={label}>
        {shown.map((line, index) => <li key={index}>{line}</li>)}
      </ul>
      {rest > 0 && (
        <Button type="button" variant="link" size="sm" className="mt-1 px-0" onClick={() => setExpanded(true)}>
          {t('bpp.bank.rowErrorsMore', 'Показать ещё {{count}}', { count: rest })}
        </Button>
      )}
    </>
  );
}

/** Остатки счетов и предложенное распределение — перед «Подтвердить». */
function ConfirmPreview({ matches, currency }: { matches: LineMatch[]; currency: string }) {
  const { t } = useTranslation();
  if (matches.length === 0) return null;
  return (
    <ul className="space-y-1 rounded-lg border p-3 text-sm" aria-label={t('bpp.bank.confirmPreview', 'Предложенное распределение')}>
      {matches.map((match) => {
        const remainder = (toCents(match.invoice_amount) ?? 0n) - (toCents(match.paid_bank_amount) ?? 0n);
        const overpaid = (toCents(match.amount) ?? 0n) > remainder;
        return (
          <li key={match.id}>
            <span className="font-medium">{match.invoice_number}</span>
            {': '}
            {t('bpp.bank.confirmRemainder', 'остаток счёта {{remainder}}, распределено {{amount}}', {
              remainder: formatMoney(fromCents(remainder > 0n ? remainder : 0n), match.invoice_currency || currency),
              amount: formatMoney(match.amount, match.invoice_currency || currency),
            })}
            {overpaid && (
              <span className="ml-1 font-medium text-destructive">
                {t('bpp.bank.confirmOverpay', '— переплата')}
              </span>
            )}
          </li>
        );
      })}
    </ul>
  );
}

/** Во всех четырёх группах сверки нет ни одной строки. */
const allGroupsEmpty = (card: BankImportCard) => Boolean(card.totals)
  && RECON_TABS.every((tab) => groupOf(card, tab)?.count === 0);

function Lines({ card, tab, canEdit }: { card: BankImportCard; tab: ReconTab; canEdit: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [dialog, setDialog] = useState<{ action: LineAction; line: StatementLine } | null>(null);
  const { data, isLoading, isError } = useQuery({
    // Статус в ключе: когда автосверка закончилась («Сверена»), строки читаются заново.
    queryKey: [...bankImportKey(card.id), 'lines', tab, page, card.status],
    queryFn: () => bankImportApi.lines(card.id, page, LINES_PAGE_SIZE, tab),
    placeholderData: keepPreviousData,
  });
  const items = data?.items ?? [];
  const pages = Math.max(1, Math.ceil((data?.total ?? 0) / LINES_PAGE_SIZE));

  const close = (done: boolean) => {
    setDialog(null);
    if (done) void invalidateRecon(queryClient, card.id);
  };

  if (isLoading) return <Skeleton className="h-32 w-full" />;
  if (isError) {
    return (
      <p className="text-sm text-destructive">
        {t('bpp.bank.linesLoadError', 'Не удалось загрузить строки выписки. Обновите страницу.')}
      </p>
    );
  }
  if (items.length === 0) {
    return (
      <p className="rounded-lg border p-6 text-center text-sm text-muted-foreground">
        {allGroupsEmpty(card)
          ? t('bpp.bank.noLines', 'Новых списаний в выписке нет: строки не распознаны, это поступления или они уже были загружены.')
          : t('bpp.bank.noLinesTab', 'В этой вкладке строк нет.')}
      </p>
    );
  }
  return (
    <div className="space-y-2">
      <ReconLinesTable
        lines={items}
        tab={tab}
        canEdit={canEdit}
        onAction={(action, line) => setDialog({ action, line })}
      />
      {pages > 1 && (
        <div className="flex items-center justify-end gap-2 text-sm">
          <Button
            variant="ghost"
            size="sm"
            disabled={page <= 1}
            onClick={() => setPage(page - 1)}
            aria-label={t('bpp.registry.prevPage', 'Предыдущая страница')}
          >
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <span>{t('bpp.registry.pageOf', 'Страница {{page}} из {{pages}}', { page, pages })}</span>
          <Button
            variant="ghost"
            size="sm"
            disabled={page >= pages}
            onClick={() => setPage(page + 1)}
            aria-label={t('bpp.registry.nextPage', 'Следующая страница')}
          >
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      )}

      {dialog?.action === 'match' && <ManualMatchDialog line={dialog.line} onClose={close} />}
      {dialog?.action === 'confirm' && (
        <CommentDialog
          title={t('bpp.bank.confirmTitle', 'Подтвердить сопоставление')}
          description={t('bpp.bank.confirmDescription', 'Платёж будет учтён в «Оплачено по банку» указанных счетов.')}
          submitLabel={t('bpp.bank.actionConfirm', 'Подтвердить')}
          failureText={t('bpp.bank.confirmFailed', 'Не удалось подтвердить сопоставление')}
          onSubmit={(comment, key) => bankImportApi.confirm(key, dialog.line.id, comment)}
          onClose={close}
        >
          <ConfirmPreview matches={dialog.line.matches ?? []} currency={dialog.line.currency} />
        </CommentDialog>
      )}
      {dialog?.action === 'cancelMatch' && (
        <CommentDialog
          title={dialog.line.match_status === 'excluded'
            ? t('bpp.bank.unexcludeTitle', 'Снять исключение')
            : t('bpp.bank.cancelMatchTitle', 'Отменить сопоставление')}
          description={t('bpp.bank.cancelMatchDescription', 'Строка вернётся в «Не сопоставлены»; автосверка её больше не возьмёт.')}
          submitLabel={dialog.line.match_status === 'excluded'
            ? t('bpp.bank.actionUnexclude', 'Снять исключение')
            : t('bpp.bank.actionCancelMatch', 'Отменить сопоставление')}
          destructive
          failureText={t('bpp.bank.cancelMatchFailed', 'Не удалось отменить сопоставление')}
          onSubmit={(comment, key) => bankImportApi.cancelMatch(key, dialog.line.id, comment)}
          onClose={close}
        />
      )}
      {dialog?.action === 'exclude' && (
        <CommentDialog
          title={t('bpp.bank.excludeTitle', 'Исключить — не относится к закупкам')}
          description={t('bpp.bank.excludeDescription', 'Строка уйдёт во вкладку «Исключены» и не попадёт в показатель «Не сопоставлено».')}
          submitLabel={t('bpp.bank.actionExcludeShort', 'Исключить')}
          destructive
          failureText={t('bpp.bank.excludeFailed', 'Не удалось исключить строку')}
          onSubmit={(comment, key) => bankImportApi.exclude(key, dialog.line.id, comment)}
          onClose={close}
        />
      )}
    </div>
  );
}

/** Вкладки результата сверки со счётчиками и таблица выбранной. */
function ReconResult({ card, canEdit }: { card: BankImportCard; canEdit: boolean }) {
  const { t } = useTranslation();
  const [tab, setTab] = useState<ReconTab>('matched');
  return (
    <div className="space-y-3">
      <Tabs value={tab} onValueChange={(value) => setTab(value as ReconTab)}>
        <TabsList className="h-auto flex-wrap">
          {RECON_TABS.map((item) => {
            const count = groupOf(card, item)?.count;
            return (
              <TabsTrigger key={item} value={item}>
                {t(...TAB_LABELS[item])}{count === undefined ? '' : ` (${count})`}
              </TabsTrigger>
            );
          })}
        </TabsList>
      </Tabs>
      {/* Ключ — вкладка: номер страницы не переходит между вкладками. */}
      <Lines key={tab} card={card} tab={tab} canEdit={canEdit} />
    </div>
  );
}

export function BankImportPage() {
  const { t } = useTranslation();
  const { id = '' } = useParams<{ id: string }>();
  const location = useLocation();
  const backHref = useRegistryBackHref(BANK_BASE);
  const warnings = warningsOf(location.state);
  const permissions = usePermissions();
  const canEdit = permissions.can('bpp.bank', 'edit');
  const queryClient = useQueryClient();
  const [cancelOpen, setCancelOpen] = useState(false);
  const [exporting, setExporting] = useState(false);
  const reconcile = useIdempotentAction((key) => bankImportApi.reconcile(key, id));

  const { data: card, isLoading, error } = useQuery({
    queryKey: bankImportKey(id),
    queryFn: () => bankImportApi.get(id),
    enabled: Boolean(id),
    // Опрос — пока идёт разбор и пока после «Загружена» идёт автосверка
    // (окно от `finished_at`); «Сверена», «Ошибка загрузки», «Отменена» и
    // «Загружена» старше окна его останавливают.
    refetchInterval: (query) => {
      const data = query.state.data;
      return data && (data.status === 'processing' || autoMatchRunning(data)) ? IMPORT_POLL_MS : false;
    },
  });

  // Окно автосверки закрывается само, без ответа сервера: карточка при этом не
  // меняется (данные те же), поэтому перерисовку по истечении окна даёт таймер.
  const [, setTick] = useState(0);
  const status = card?.status;
  const finishedAt = card?.finished_at;
  useEffect(() => {
    if (status !== 'loaded' || !finishedAt) return undefined;
    const left = Date.parse(finishedAt) + AUTOMATCH_WINDOW_MS - Date.now();
    if (!(left > 0)) return undefined;
    const timer = setTimeout(() => setTick((n) => n + 1), left + 50);
    return () => clearTimeout(timer);
  }, [status, finishedAt]);

  const back = (
    <Button asChild variant="ghost" size="sm">
      <Link to={backHref}>
        <ArrowLeft className="mr-1.5 h-4 w-4" />
        {t('bpp.document.backToList', 'К списку')}
      </Link>
    </Button>
  );

  if (isLoading) {
    return (
      <div className="space-y-3">
        {back}
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  // Упавший ОЧЕРЕДНОЙ опрос карточку не прячет: на экране остаётся
  // последнее известное состояние, а опрос повторится сам.
  if (!card) {
    const notFound = errorStatus(error) === 404;
    return (
      <div className="space-y-3">
        {back}
        <Card>
          <CardContent className="flex flex-col items-center gap-3 py-10 text-center text-sm text-muted-foreground">
            <FileWarning className="h-8 w-8" />
            <p>
              {notFound
                ? t('bpp.bank.notFound', 'Загрузка выписки не найдена.')
                : t('bpp.bank.loadError', 'Не удалось загрузить выписку. Обновите страницу.')}
            </p>
          </CardContent>
        </Card>
      </div>
    );
  }

  const processing = card.status === 'processing';
  const cancelled = card.status === 'cancelled';
  const hasLines = card.status === 'loaded' || card.status === 'reconciled';
  const matching = autoMatchRunning(card);

  const runReconcile = () => {
    reconcile.run().then(
      () => { void invalidateRecon(queryClient, id); },
      (error: unknown) => reportApiError(error, t('bpp.bank.reconcileFailed', 'Не удалось сверить выписку')),
    );
  };

  const runExport = () => {
    setExporting(true);
    bankImportApi.exportResult(card.id, card.number).then(
      (outcome) => {
        if (outcome.kind === 'queued') {
          toast.info(outcome.detail || t('bpp.bank.exportQueued', 'Выгрузка готовится, ссылка придёт уведомлением'));
        }
      },
      (error: unknown) => reportApiError(error, t('bpp.bank.exportFailed', 'Не удалось выгрузить результат сверки')),
    ).finally(() => setExporting(false));
  };

  return (
    <div className="space-y-4">
      {back}
      <Card>
        <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3">
          <CardTitle className="text-lg">
            {t('bpp.bank.importTitle', 'Загрузка выписки {{number}}', { number: card.number })}
          </CardTitle>
          <StatusBadge kind="bank_import" status={card.status} />
        </CardHeader>
        <CardContent className="space-y-4 text-sm">
          <dl className="grid gap-x-6 gap-y-1 sm:grid-cols-2">
            <div><dt className="inline text-muted-foreground">{t('bpp.bank.account', 'Счёт')}: </dt>
              <dd className="inline">
                {card.account.bank_name ? `${card.account.bank_name} · ` : ''}
                <span className="font-mono">{card.account.iban}</span>
              </dd>
            </div>
            <div><dt className="inline text-muted-foreground">{t('bpp.bank.format', 'Формат файла')}: </dt>
              <dd className="inline">
                {FORMAT_LABELS[card.format]
                  ? t(FORMAT_LABELS[card.format][0], FORMAT_LABELS[card.format][1])
                  : card.format}
              </dd>
            </div>
            <div><dt className="inline text-muted-foreground">{t('bpp.bank.period', 'Период')}: </dt>
              <dd className="inline">{formatDate(card.period_from)} – {formatDate(card.period_to)}</dd>
            </div>
            <div><dt className="inline text-muted-foreground">{t('bpp.bank.fileName', 'Файл')}: </dt>
              <dd className="inline">{card.filename || '—'}</dd>
            </div>
            <div><dt className="inline text-muted-foreground">{t('bpp.bank.author', 'Кто загрузил')}: </dt>
              <dd className="inline">{card.author_name || '—'}</dd>
            </div>
            <div><dt className="inline text-muted-foreground">{t('bpp.bank.createdAt', 'Дата загрузки')}: </dt>
              <dd className="inline">{formatDateTime(card.created_at)}</dd>
            </div>
            {card.comment && (
              <div className="sm:col-span-2">
                <dt className="inline text-muted-foreground">{t('bpp.bank.comment', 'Комментарий')}: </dt>
                <dd className="inline">{card.comment}</dd>
              </div>
            )}
          </dl>

          {warnings.length > 0 && (
            <div role="note" className="rounded-lg border border-amber-500/50 p-3">
              <ul className="list-disc space-y-0.5 pl-5 text-amber-800 dark:text-amber-200">
                {warnings.map((warning) => <li key={warning}>{warning}</li>)}
              </ul>
            </div>
          )}

          {processing && (
            <div role="status" className="space-y-2">
              <p className="text-muted-foreground">
                {t('bpp.bank.processing', 'Выписка разбирается. Страница обновится сама.')}
              </p>
              <Progress value={card.progress} aria-label={t('bpp.bank.progress', 'Ход разбора')} />
            </div>
          )}

          {card.status === 'failed' && (
            <p role="alert" className="text-destructive">
              {card.failure || t('bpp.bank.failedFallback', 'Выписку не удалось загрузить.')}
            </p>
          )}

          {cancelled && (
            <p role="status" className="text-muted-foreground">
              {t('bpp.bank.cancelledNote', 'Загрузка отменена: её строки сняты и в сверке не участвуют.')}
            </p>
          )}

          <Totals card={card} />
          {matching && (
            <p role="status" className="text-muted-foreground">
              {t('bpp.bank.matching', 'Идёт автосверка со счетами. Страница обновится сама.')}
            </p>
          )}
          {hasLines && <ReconTotalsView card={card} />}

          {hasLines && (
            <div className="flex flex-wrap gap-2">
              {canEdit && card.status === 'loaded' && (
                <Button
                  type="button"
                  size="sm"
                  disabled={reconcile.pending || matching}
                  title={matching ? t('bpp.bank.reconcileWait', 'Автосверка ещё идёт — дождитесь её окончания') : undefined}
                  onClick={runReconcile}
                >
                  {reconcile.pending && <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />}
                  {t('bpp.bank.reconcile', 'Сверить')}
                </Button>
              )}
              <Button type="button" size="sm" variant="outline" disabled={exporting} onClick={runExport}>
                {exporting
                  ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                  : <Download className="mr-1.5 h-4 w-4" />}
                {t('bpp.bank.exportResult', 'Выгрузить результат')}
              </Button>
              {canEdit && (
                <Button type="button" size="sm" variant="outline" onClick={() => setCancelOpen(true)}>
                  {t('bpp.bank.cancelImport', 'Отменить загрузку')}
                </Button>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {card.errors.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              {t('bpp.bank.rowErrors', 'Строки, которые не удалось разобрать')}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="mb-2 text-sm text-muted-foreground">
              {t('bpp.bank.rowErrorsHint', 'Остальные строки загружены. Исправьте эти строки в выписке и загрузите её снова — уже загруженные операции пропустятся как дубли.')}
            </p>
            <RowErrors errors={card.errors} />
          </CardContent>
        </Card>
      )}

      {hasLines && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t('bpp.bank.lines', 'Строки выписки')}</CardTitle>
          </CardHeader>
          <CardContent>
            <ReconResult card={card} canEdit={canEdit} />
          </CardContent>
        </Card>
      )}

      {cancelOpen && (
        <CancelImportDialog
          card={card}
          onClose={(done) => {
            setCancelOpen(false);
            if (done) void invalidateRecon(queryClient, id);
          }}
        />
      )}
    </div>
  );
}

export default BankImportPage;
