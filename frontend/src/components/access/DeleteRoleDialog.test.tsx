/**
 * Диалог удаления роли.
 *
 * Правило «удалять только свободную» бесполезно, если отказ называет одно
 * число: «назначена трём должностям» не говорит, к кому идти. Поэтому
 * проверяется, что держатели показаны поимённо — с компанией, отделом и
 * должностью — и что кнопка удаления при них недоступна.
 */
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';
import type { Role, RoleHolder } from '@/types/access';

import { DeleteRoleDialog } from './DeleteRoleDialog';

const getRoleHolders = vi.fn();

vi.mock('@/api/access', () => ({
  accessApi: { getRoleHolders: (id: number) => getRoleHolders(id) },
}));

const ROLE: Role = { id: 12, code: 'hr-admin', title: 'Администратор кадров', is_system: false };

const HOLDERS: RoleHolder[] = [
  {
    user_id: 2, full_name: 'Петров Пётр', company: 'htq-kz',
    department: 'Строительство', position: 'Прораб',
    source: 'position', position_id: 7,
  },
  {
    user_id: 5, full_name: 'Директоров Иван', company: 'kurly-kg',
    department: null, position: null, source: 'personal', position_id: null,
  },
];

const open = (onConfirm = vi.fn()) => {
  renderWithProviders(
    <DeleteRoleDialog role={ROLE} open onOpenChange={vi.fn()} onConfirm={onConfirm} />,
  );
  return onConfirm;
};

beforeEach(() => {
  vi.clearAllMocks();
  getRoleHolders.mockResolvedValue({ data: [] });
});

describe('DeleteRoleDialog', () => {
  it('свободную роль разрешает удалить', async () => {
    const onConfirm = open();

    await screen.findByText(/ни у кого не задействована/i);
    await userEvent.click(screen.getByRole('button', { name: /^Удалить$/ }));

    expect(onConfirm).toHaveBeenCalledWith(ROLE);
  });

  it('перечисляет держателей: имя, компания, отдел, должность', async () => {
    getRoleHolders.mockResolvedValue({ data: HOLDERS });
    open();

    expect(await screen.findByText('Петров Пётр')).toBeInTheDocument();
    expect(screen.getByText('htq-kz')).toBeInTheDocument();
    expect(screen.getByText('Строительство')).toBeInTheDocument();
    expect(screen.getByText('Прораб')).toBeInTheDocument();
  });

  it('при держателях удаление недоступно', async () => {
    getRoleHolders.mockResolvedValue({ data: HOLDERS });
    const onConfirm = open();

    await screen.findByText('Петров Пётр');
    expect(screen.getByRole('button', { name: /^Удалить$/ })).toBeDisabled();
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it('личное назначение помечено — его снимают у человека, а не у должности', async () => {
    getRoleHolders.mockResolvedValue({ data: HOLDERS });
    open();

    await screen.findByText('Директоров Иван');
    expect(screen.getByText('лично')).toBeInTheDocument();
  });

  it('держатель без кадровой карточки показан с прочерками, а не пропущен', async () => {
    getRoleHolders.mockResolvedValue({ data: [HOLDERS[1]] });
    open();

    await screen.findByText('Директоров Иван');
    expect(screen.getAllByText('—')).toHaveLength(2);
  });

  it('пока держатели грузятся, удаление недоступно', () => {
    getRoleHolders.mockReturnValue(new Promise(() => {}));
    open();

    expect(screen.getByRole('button', { name: /^Удалить$/ })).toBeDisabled();
  });
});
