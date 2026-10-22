/**
 * Общая таблица сравнения (блок «Альтернативы» БЗО и сравнение тендера):
 * колонки — предложения, постоянные колонки, подсветка самого дешёвого,
 * приглушение колонки и строка-слот под предложениями.
 */
import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { ComparisonGrid } from './ComparisonGrid';

interface Row { id: string; name: string; plan: string; prices: Record<string, string> }
interface Col { id: string; name: string; off?: boolean }

const ROWS: Row[] = [
  { id: 'r1', name: 'Арматура', plan: '100', prices: { a: '90', b: '120' } },
  { id: 'r2', name: 'Швеллер', plan: '50', prices: { a: '60', b: '40' } },
];
const COLS: Col[] = [{ id: 'a', name: 'Альфа' }, { id: 'b', name: 'Бета', off: true }];

function renderGrid(footer?: (col: Col) => string) {
  return render(
    <ComparisonGrid
      testId="grid"
      columns={COLS}
      columnKey={(col) => col.id}
      renderColumn={(col) => col.name}
      rows={ROWS}
      rowKey={(row) => row.id}
      renderRow={(row) => row.name}
      rowHeader="Позиция"
      leading={[{ key: 'plan', header: 'План', cell: (row: Row) => row.plan }]}
      cell={(row, col) => row.prices[col.id]}
      highlight={(row, col) => {
        const best = Object.entries(row.prices).sort((x, y) => Number(x[1]) - Number(y[1]))[0][0];
        return best === col.id ? 'cheapest' : null;
      }}
      dim={(col) => (col.off ? 'opacity-50' : undefined)}
      footer={footer}
      footerLabel="Выбор"
    />,
  );
}

describe('ComparisonGrid', () => {
  it('колонки — предложения после постоянных колонок', () => {
    renderGrid();
    const heads = within(screen.getByTestId('grid')).getAllByRole('columnheader').map((cell) => cell.textContent);
    expect(heads).toEqual(['Позиция', 'План', 'Альфа', 'Бета']);
  });

  it('самый дешёвый в строке подсвечен и подписан для читалки', () => {
    renderGrid();
    const [first, second] = within(screen.getByTestId('grid')).getAllByRole('row').slice(1);
    const cheapFirst = within(first).getByText('90').closest('td');
    expect(cheapFirst).toHaveAttribute('data-cheapest', 'true');
    expect(within(cheapFirst as HTMLElement).getByText(/самый дешёвый/)).toBeInTheDocument();
    expect(within(first).getByText('120').closest('td')).not.toHaveAttribute('data-cheapest');
    expect(within(second).getByText('40').closest('td')).toHaveAttribute('data-cheapest', 'true');
  });

  it('приглушённая колонка — класс у заголовка и клеток', () => {
    renderGrid();
    expect(screen.getByRole('columnheader', { name: 'Бета' }).className).toContain('opacity-50');
    expect(screen.getByText('120').closest('td')?.className).toContain('opacity-50');
  });

  it('строка-слот под предложениями — только с footer', () => {
    const { unmount } = renderGrid();
    expect(screen.queryByText('Выбор')).toBeNull();
    unmount();
    renderGrid((col) => `Выбрать ${col.name}`);
    expect(screen.getByRole('rowheader', { name: 'Выбор' })).toBeInTheDocument();
    expect(screen.getByText('Выбрать Альфа')).toBeInTheDocument();
    expect(screen.getByText('Выбрать Бета')).toBeInTheDocument();
  });
});
