/**
 * «Переместить» из окна карточки (этап S4b, спецификация логики автоматизаций
 * §5): скрытые колонки доски вручную не предлагаются, отмена задачи — отдельной
 * строкой, даже когда колонка «Отменена» скрыта.
 */
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';
import type { TaskStatus } from '@/types/tasks';

import { MovePopover } from '../MovePopover';

const HTQ_COLUMNS = [
  { status: 'backlog', title: 'Постановка задачи', color: null, hidden: false },
  { status: 'todo', title: 'Ожидающие исполнения', color: null, hidden: false },
  { status: 'in_progress', title: 'Исполнение', color: null, hidden: false },
  { status: 'in_review', title: null, color: null, hidden: true },
  { status: 'blocked', title: 'В ожидании', color: null, hidden: false },
  { status: 'done', title: 'Готово', color: null, hidden: false },
  { status: 'cancelled', title: null, color: null, hidden: true },
] as Array<{ status: TaskStatus; title: string | null; color: null; hidden: boolean }>;

function open(onMove = vi.fn()) {
  renderWithProviders(
    <MovePopover status="in_progress" columns={HTQ_COLUMNS} onMove={onMove}
      trigger={<button type="button">Колонка</button>} />,
  );
  return userEvent.click(screen.getByRole('button', { name: 'Колонка' })).then(() => onMove);
}

describe('MovePopover', () => {
  it('скрытые колонки не предлагаются, отмена — отдельной строкой', async () => {
    const onMove = await open();
    expect(screen.getByRole('button', { name: /В ожидании/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Готово/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /ревью/i })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Отменить задачу' }));
    expect(onMove).toHaveBeenCalledWith('cancelled');
  });
});
