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
 * - таблица строк — страницами с сервера; вкладки сверки «Сопоставлены /
 *   Требуют проверки / Не сопоставлены» — со сверкой (A4.2, этап 4);
 * - «К списку» возвращает на то место реестра, откуда открыли загрузку
 *   (`useRegistryBackHref`); предупреждения о пересечении периода приходят
 *   с формы загрузки состоянием перехода (карточка загрузки их не хранит —
 *   они есть только в ответе `POST bank/imports`);
 * - строки показываются только у «Загружена»: у отменённой загрузки
 *   действующих строк нет (сервер отдаёт только неотменённые).
 */
import { useState } from 'react';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link, useLocation, useParams } from 'react-router-dom';
import { ArrowLeft, ChevronLeft, ChevronRight, FileWarning } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { errorStatus } from '@/lib/apiError';

import { useRegistryBackHref } from '../core/registryBack';
import { StatusBadge } from '../core/StatusBadge';
import { formatDate, formatDateTime, formatMoney } from '../format';
import { FORMAT_LABELS } from '../settings/templateFields';

import {
  BANK_BASE, bankImportApi, bankImportKey, IMPORT_POLL_MS, type BankImportCard,
} from './api';

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

function Lines({ importId }: { importId: string }) {
  const { t } = useTranslation();
  const [page, setPage] = useState(1);
  const { data, isLoading, isError } = useQuery({
    queryKey: [...bankImportKey(importId), 'lines', page],
    queryFn: () => bankImportApi.lines(importId, page, LINES_PAGE_SIZE),
    placeholderData: keepPreviousData,
  });
  const items = data?.items ?? [];
  const pages = Math.max(1, Math.ceil((data?.total ?? 0) / LINES_PAGE_SIZE));

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
        {t('bpp.bank.noLines', 'Новых списаний в выписке нет: строки не распознаны, это поступления или они уже были загружены.')}
      </p>
    );
  }
  return (
    <div className="space-y-2">
      <div className="overflow-x-auto rounded-lg border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t('bpp.bank.lineDate', 'Дата')}</TableHead>
              <TableHead>{t('bpp.bank.lineNumber', '№ ПП')}</TableHead>
              <TableHead>{t('bpp.bank.lineRecipient', 'Получатель')}</TableHead>
              <TableHead>{t('bpp.bank.lineBin', 'БИН')}</TableHead>
              <TableHead className="text-right">{t('bpp.bank.lineAmount', 'Сумма')}</TableHead>
              <TableHead>{t('bpp.bank.linePurpose', 'Назначение')}</TableHead>
              <TableHead>{t('bpp.bank.lineStatus', 'Сверка')}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((line) => (
              <TableRow key={line.id}>
                <TableCell>{formatDate(line.doc_date)}</TableCell>
                <TableCell>{line.doc_number}</TableCell>
                <TableCell>
                  <div className="leading-tight">
                    <div>{line.recipient_name || '—'}</div>
                    {line.recipient_iban && (
                      <div className="font-mono text-xs text-muted-foreground">{line.recipient_iban}</div>
                    )}
                  </div>
                </TableCell>
                <TableCell className="font-mono">{line.recipient_bin || '—'}</TableCell>
                <TableCell className="text-right tabular-nums">
                  {formatMoney(line.amount, line.currency)}
                </TableCell>
                <TableCell className="max-w-96 truncate" title={line.purpose}>{line.purpose || '—'}</TableCell>
                <TableCell><StatusBadge kind="bank_line" status={line.match_status} /></TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
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
    </div>
  );
}

export function BankImportPage() {
  const { t } = useTranslation();
  const { id = '' } = useParams<{ id: string }>();
  const location = useLocation();
  const backHref = useRegistryBackHref(BANK_BASE);
  const warnings = warningsOf(location.state);

  const { data: card, isLoading, error } = useQuery({
    queryKey: bankImportKey(id),
    queryFn: () => bankImportApi.get(id),
    enabled: Boolean(id),
    refetchInterval: (query) => (query.state.data?.status === 'processing' ? IMPORT_POLL_MS : false),
  });

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

      {card.status === 'loaded' && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t('bpp.bank.lines', 'Строки выписки')}</CardTitle>
          </CardHeader>
          <CardContent>
            <Lines importId={card.id} />
          </CardContent>
        </Card>
      )}
    </div>
  );
}

export default BankImportPage;
