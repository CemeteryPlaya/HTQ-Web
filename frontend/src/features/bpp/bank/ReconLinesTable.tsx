/**
 * Таблица строк выписки с результатом сверки (ТЗ §11.2): дата, № ПП,
 * получатель, БИН, сумма, назначение с подсветкой найденного номера, счёт
 * (ссылка), сумма счёта, «Оплачено по банку всего», статус сверки счёта и
 * причина. У платежа на несколько счетов счёта идут столбиком — по строке на
 * сопоставление, в одном порядке во всех четырёх ячейках счёта.
 *
 * Кнопки действий — только с правом `bpp.bank` edit (`canEdit`), набор
 * зависит от вкладки: «Не сопоставлены» — вручную / исключить, «Требуют
 * проверки» — подтвердить / отменить сопоставление, «Сопоставлены» — отменить
 * сопоставление, «Исключены» — снять исключение (та же ручка отмены).
 */
import { Fragment, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';

import { StatusBadge } from '../core/StatusBadge';
import { formatDate, formatMoney } from '../format';

import { splitPurpose } from './amounts';
import type { LineMatch, ReconTab, StatementLine } from './api';

export type LineAction = 'match' | 'confirm' | 'cancelMatch' | 'exclude';

interface Props {
  lines: StatementLine[];
  tab: ReconTab;
  canEdit: boolean;
  onAction: (action: LineAction, line: StatementLine) => void;
}

/** Назначение с выделенными найденными номерами счетов. */
export function Purpose({ line }: { line: StatementLine }) {
  const parts = splitPurpose(line.purpose, line.found_numbers ?? []);
  return (
    <span title={line.purpose}>
      {parts.map((part, index) => (
        <Fragment key={index}>
          {part.hit
            ? <mark className="rounded bg-amber-200 px-0.5 text-foreground dark:bg-amber-800">{part.text}</mark>
            : part.text}
        </Fragment>
      ))}
    </span>
  );
}

/** Ячейки счетов строки: по одному элементу на сопоставление. */
function Stack({ matches, render }: { matches: LineMatch[]; render: (match: LineMatch) => ReactNode }) {
  if (matches.length === 0) return <>—</>;
  return (
    <ul className="space-y-1">
      {matches.map((match) => <li key={match.id} className="leading-tight">{render(match)}</li>)}
    </ul>
  );
}

const ACTIONS: Record<ReconTab, LineAction[]> = {
  unmatched: ['match', 'exclude'],
  review: ['confirm', 'cancelMatch'],
  matched: ['cancelMatch'],
  excluded: ['cancelMatch'],
};

export function ReconLinesTable({ lines, tab, canEdit, onAction }: Props) {
  const { t } = useTranslation();
  const labels: Record<LineAction, string> = {
    match: t('bpp.bank.actionMatch', 'Сопоставить вручную'),
    confirm: t('bpp.bank.actionConfirm', 'Подтвердить'),
    cancelMatch: tab === 'excluded'
      ? t('bpp.bank.actionUnexclude', 'Снять исключение')
      : t('bpp.bank.actionCancelMatch', 'Отменить сопоставление'),
    exclude: t('bpp.bank.actionExclude', 'Исключить — не относится к закупкам'),
  };

  return (
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
            <TableHead>{t('bpp.bank.lineInvoice', 'Счёт')}</TableHead>
            <TableHead className="text-right">{t('bpp.bank.lineInvoiceAmount', 'Сумма счёта')}</TableHead>
            <TableHead className="text-right">{t('bpp.bank.linePaidBank', 'Оплачено по банку всего')}</TableHead>
            <TableHead>{t('bpp.bank.lineStatus', 'Сверка')}</TableHead>
            <TableHead>{t('bpp.bank.lineReason', 'Причина')}</TableHead>
            {canEdit && <TableHead><span className="sr-only">{t('bpp.bank.lineActions', 'Действия')}</span></TableHead>}
          </TableRow>
        </TableHeader>
        <TableBody>
          {lines.map((line) => {
            const matches = line.matches ?? [];
            const reason = line.review_reason_label || line.excluded_comment || '';
            return (
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
                <TableCell className="max-w-72"><Purpose line={line} /></TableCell>
                <TableCell>
                  <Stack
                    matches={matches}
                    render={(match) => (
                      <Link to={match.invoice_url} className="underline underline-offset-2">
                        {match.invoice_number}
                      </Link>
                    )}
                  />
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  <Stack matches={matches} render={(m) => formatMoney(m.invoice_amount, m.invoice_currency)} />
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  <Stack matches={matches} render={(m) => formatMoney(m.paid_bank_amount, m.invoice_currency)} />
                </TableCell>
                <TableCell>
                  {matches.length > 0
                    ? <Stack matches={matches} render={(m) => m.recon_status_label} />
                    : <StatusBadge kind="bank_line" status={line.match_status} />}
                </TableCell>
                <TableCell className="max-w-64 text-sm">{reason || '—'}</TableCell>
                {canEdit && (
                  <TableCell>
                    <div className="flex flex-col items-start gap-1">
                      {ACTIONS[tab].map((action) => (
                        <Button
                          key={action}
                          type="button"
                          size="sm"
                          variant="outline"
                          onClick={() => onAction(action, line)}
                        >
                          {labels[action]}
                        </Button>
                      ))}
                    </div>
                  </TableCell>
                )}
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
