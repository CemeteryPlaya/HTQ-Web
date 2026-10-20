/**
 * Таблица сравнения: строки — позиции или показатели, колонки — предложения
 * (поставщики, альтернативы). Общая для блока «Альтернативы» БЗО (ТЗ §12.4)
 * и сравнения предложений тендера (TND-020).
 *
 * - `leading` — постоянные колонки между заголовком строки и предложениями
 *   (исходный документ, количество, план).
 * - `highlight(row, column) === 'cheapest'` — клетка самого дешёвого
 *   варианта строки подсвечивается и подписана для читалки экрана.
 * - `dim(column)` — класс приглушения колонки (отозванное, неучаствующее).
 * - `footer(column)` — последняя строка под каждым предложением (кнопка
 *   «Выбрать», итоги); нет `footer` — строки нет.
 */
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { cn } from '@/lib/utils';

export type Highlight = 'cheapest' | null;

export interface LeadingColumn<Row> {
  key: string;
  header: ReactNode;
  cell: (row: Row) => ReactNode;
  className?: string;
}

export interface ComparisonGridProps<Row, Column> {
  columns: Column[];
  columnKey: (column: Column) => string;
  renderColumn: (column: Column) => ReactNode;
  rows: Row[];
  rowKey: (row: Row) => string;
  renderRow: (row: Row) => ReactNode;
  /** Заголовок колонки строк (например, «Позиция»). */
  rowHeader?: ReactNode;
  leading?: LeadingColumn<Row>[];
  cell: (row: Row, column: Column) => ReactNode;
  cellClassName?: string;
  highlight?: (row: Row, column: Column) => Highlight;
  dim?: (column: Column) => string | undefined;
  footer?: (column: Column) => ReactNode;
  footerLabel?: ReactNode;
  testId?: string;
}

export function ComparisonGrid<Row, Column>({
  columns, columnKey, renderColumn, rows, rowKey, renderRow, rowHeader, leading = [], cell,
  cellClassName, highlight, dim, footer, footerLabel, testId,
}: ComparisonGridProps<Row, Column>) {
  const { t } = useTranslation();
  return (
    <Table data-testid={testId}>
      <TableHeader>
        <TableRow>
          <TableHead>{rowHeader}</TableHead>
          {leading.map((col) => <TableHead key={col.key} className={col.className}>{col.header}</TableHead>)}
          {columns.map((column) => (
            <TableHead key={columnKey(column)} className={cn(cellClassName, dim?.(column))}>
              {renderColumn(column)}
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <TableRow key={rowKey(row)}>
            <TableHead scope="row" className="whitespace-nowrap font-normal text-foreground">
              {renderRow(row)}
            </TableHead>
            {leading.map((col) => <TableCell key={col.key} className={col.className}>{col.cell(row)}</TableCell>)}
            {columns.map((column) => {
              const cheapest = highlight?.(row, column) === 'cheapest';
              return (
                <TableCell
                  key={columnKey(column)}
                  data-cheapest={cheapest || undefined}
                  className={cn(cellClassName, dim?.(column),
                    cheapest && 'bg-emerald-50 font-medium dark:bg-emerald-950/40')}
                >
                  {cell(row, column)}
                  {cheapest && (
                    <span className="sr-only"> — {t('bpp.comparison.cheapest', 'самый дешёвый')}</span>
                  )}
                </TableCell>
              );
            })}
          </TableRow>
        ))}
        {footer && (
          <TableRow>
            <TableHead scope="row">{footerLabel}</TableHead>
            {leading.map((col) => <TableCell key={col.key} />)}
            {columns.map((column) => (
              <TableCell key={columnKey(column)} className={cn(cellClassName, dim?.(column))}>
                {footer(column)}
              </TableCell>
            ))}
          </TableRow>
        )}
      </TableBody>
    </Table>
  );
}

export default ComparisonGrid;
