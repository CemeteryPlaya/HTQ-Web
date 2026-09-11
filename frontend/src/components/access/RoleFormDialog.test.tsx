/**
 * Форма кода и названия роли — при копировании и переименовании.
 *
 * Главное, что проверяется: код правится. Без этого копия навсегда оставалась
 * бы «<исходный>-copy», а вторая копия того же исходника вообще не завелась бы
 * — код уникален на всей платформе. Исключение одно: у системной роли код
 * заблокирован, по нему её находят миграции.
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { Role } from '@/types/access';

import { RoleFormDialog } from './RoleFormDialog';

const ROLE: Role = { id: 12, code: 'hr-admin', title: 'Администратор кадров', is_system: false };
const SYSTEM: Role = { id: 1, code: 'platform-admin', title: 'Администратор платформы', is_system: true };

const open = (role: Role, mode: 'copy' | 'rename', onSubmit = vi.fn()) => {
  render(
    <RoleFormDialog role={role} mode={mode} open onOpenChange={vi.fn()} onSubmit={onSubmit} />,
  );
  return onSubmit;
};

describe('RoleFormDialog', () => {
  it('копия открывается с производными кодом и названием', () => {
    open(ROLE, 'copy');

    expect(screen.getByLabelText('Код роли')).toHaveValue('hr-admin-copy');
    expect(screen.getByLabelText('Название роли')).toHaveValue('Администратор кадров (копия)');
  });

  it('предложенные значения можно переписать до создания копии', async () => {
    const onSubmit = open(ROLE, 'copy');

    const code = screen.getByLabelText('Код роли');
    await userEvent.clear(code);
    await userEvent.type(code, 'hr-viewer');
    const title = screen.getByLabelText('Название роли');
    await userEvent.clear(title);
    await userEvent.type(title, 'Кадры: только просмотр');
    await userEvent.click(screen.getByRole('button', { name: /Создать роль/i }));

    expect(onSubmit).toHaveBeenCalledWith({ code: 'hr-viewer', title: 'Кадры: только просмотр' });
  });

  it('переименование открывается с текущими значениями', () => {
    open(ROLE, 'rename');

    expect(screen.getByLabelText('Код роли')).toHaveValue('hr-admin');
    expect(screen.getByLabelText('Название роли')).toHaveValue('Администратор кадров');
  });

  it('код можно сменить — иначе копия навсегда останется «-copy»', async () => {
    const onSubmit = open(ROLE, 'rename');

    const code = screen.getByLabelText('Код роли');
    await userEvent.clear(code);
    await userEvent.type(code, 'hr-lead');
    await userEvent.click(screen.getByRole('button', { name: /Сохранить/i }));

    expect(onSubmit).toHaveBeenCalledWith({ code: 'hr-lead', title: 'Администратор кадров' });
  });

  it('у системной роли код заблокирован и объяснён, а не спрятан', () => {
    open(SYSTEM, 'rename');

    expect(screen.getByLabelText('Код роли')).toBeDisabled();
    expect(screen.getByText(/по нему её находят миграции/i)).toBeInTheDocument();
  });

  it('системную роль всё равно можно переименовать', async () => {
    const onSubmit = open(SYSTEM, 'rename');

    const title = screen.getByLabelText('Название роли');
    await userEvent.clear(title);
    await userEvent.type(title, 'Главный администратор');
    await userEvent.click(screen.getByRole('button', { name: /Сохранить/i }));

    expect(onSubmit).toHaveBeenCalledWith({
      code: 'platform-admin', title: 'Главный администратор',
    });
  });

  it('пустое поле не даёт сохранить', async () => {
    open(ROLE, 'rename');

    await userEvent.clear(screen.getByLabelText('Название роли'));

    expect(screen.getByRole('button', { name: /Сохранить/i })).toBeDisabled();
  });
});
