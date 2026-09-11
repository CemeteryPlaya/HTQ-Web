/**
 * Роли должности (§4.3) и личные назначения (§4.4).
 *
 * Главное свойство обоих окон — набор уходит ЦЕЛИКОМ одним запросом. Серия
 * «добавить/убрать» прошла бы через состояния, которых администратор не
 * выбирал, а обрыв посередине оставил бы половину набора; на поверхности прав
 * это означает «часть людей осталась без доступа» без единой ошибки на экране.
 *
 * Второе — личные назначения обязаны выглядеть исключением. Как только они
 * начнут смотреться вторым равноправным способом раздать права, права
 * перестанут следовать за должностью, и замена человека будет означать ручную
 * перевыдачу.
 */
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';
import type { PositionRole, Role, RoleAssignment } from '@/types/access';

import { PositionRolesDialog } from './PositionRolesDialog';
import { UserAssignmentsDialog } from './UserAssignmentsDialog';

const listRoles = vi.fn();
const getPositionRoles = vi.fn();
const putPositionRoles = vi.fn();
const getAssignments = vi.fn();
const putAssignments = vi.fn();

vi.mock('@/api/access', () => ({
  accessApi: {
    listRoles: () => listRoles(),
    getPositionRoles: (id: number) => getPositionRoles(id),
    putPositionRoles: (id: number, roleIds: number[]) => putPositionRoles(id, roleIds),
    getAssignments: (id: number) => getAssignments(id),
    putAssignments: (id: number, items: RoleAssignment[]) => putAssignments(id, items),
  },
}));

vi.mock('@/api/client', () => ({
  default: { get: vi.fn().mockResolvedValue({ data: [{ id: 3, name: 'ИТ' }] }) },
}));

vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

const ROLES: Role[] = [
  { id: 12, code: 'hr-admin', title: 'Администратор кадров', is_system: false },
  { id: 7, code: 'tasks-read', title: 'Чтение задач', is_system: false },
];

const CURRENT: PositionRole[] = [{ role_id: 12, code: 'hr-admin', title: 'Администратор кадров' }];

beforeEach(() => {
  vi.clearAllMocks();
  listRoles.mockResolvedValue({ data: ROLES });
  getPositionRoles.mockResolvedValue({ data: CURRENT });
  putPositionRoles.mockResolvedValue({ data: [] });
  getAssignments.mockResolvedValue({ data: [] });
  putAssignments.mockResolvedValue({ data: [] });
});

describe('PositionRolesDialog', () => {
  const open = () =>
    renderWithProviders(
      <PositionRolesDialog
        positionId={5}
        positionTitle="Инженер"
        open
        onOpenChange={vi.fn()}
      />,
    );

  it('отмечает уже выданные роли', async () => {
    open();
    expect(await screen.findByLabelText(/Администратор кадров/)).toBeChecked();
    expect(screen.getByLabelText(/Чтение задач/)).not.toBeChecked();
  });

  it('набор уходит одним запросом целиком, а не серией добавлений', async () => {
    open();
    await userEvent.click(await screen.findByLabelText(/Чтение задач/));
    await userEvent.click(screen.getByRole('button', { name: /Сохранить/i }));

    await waitFor(() => expect(putPositionRoles).toHaveBeenCalledTimes(1));
    expect(putPositionRoles).toHaveBeenCalledWith(5, [12, 7]);
  });

  it('снятая роль исчезает из набора', async () => {
    open();
    await userEvent.click(await screen.findByLabelText(/Администратор кадров/));
    await userEvent.click(screen.getByRole('button', { name: /Сохранить/i }));

    await waitFor(() => expect(putPositionRoles).toHaveBeenCalledWith(5, []));
  });

  it('без права правки кнопка сохранения не показывается', async () => {
    renderWithProviders(
      <PositionRolesDialog
        positionId={5}
        positionTitle="Инженер"
        open
        onOpenChange={vi.fn()}
        canEdit={false}
      />,
    );

    await screen.findByLabelText(/Администратор кадров/);
    expect(screen.queryByRole('button', { name: /^Сохранить$/i })).not.toBeInTheDocument();
  });
});

describe('UserAssignmentsDialog', () => {
  const open = () =>
    renderWithProviders(
      <UserAssignmentsDialog userId={42} userLabel="ivanov" open onOpenChange={vi.fn()} />,
    );

  it('помечает личные назначения исключением', async () => {
    open();
    expect(await screen.findByText(/Это исключение, а не штатный путь/i)).toBeInTheDocument();
  });

  it('пустой список объясняет, откуда тогда берутся права', async () => {
    open();
    expect(await screen.findByText(/права идут от должности/i)).toBeInTheDocument();
  });

  it('назначение без выбора отдела уходит с областью «вся компания» и scope_id: null', async () => {
    open();
    // Дожидаемся именно ОПЦИИ: селект появляется сразу, а роли приезжают
    // запросом, и выбор до их загрузки падал бы на пустом списке.
    await screen.findByRole('option', { name: 'Администратор кадров' });
    await userEvent.selectOptions(screen.getByLabelText(/Добавить роль/i), '12');
    await userEvent.click(screen.getByRole('button', { name: /^Добавить$/i }));
    await userEvent.click(screen.getByRole('button', { name: /^Сохранить$/i }));

    await waitFor(() => expect(putAssignments).toHaveBeenCalledTimes(1));
    expect(putAssignments).toHaveBeenCalledWith(42, [
      { role_id: 12, scope_kind: 'company', scope_id: null },
    ]);
  });

  it('выбор отдела даёт область department с его идентификатором', async () => {
    open();
    await screen.findByRole('option', { name: 'Чтение задач' });
    await userEvent.selectOptions(screen.getByLabelText(/Добавить роль/i), '7');
    await screen.findByRole('option', { name: 'ИТ' });
    await userEvent.selectOptions(screen.getByLabelText(/Область/i), '3');
    await userEvent.click(screen.getByRole('button', { name: /^Добавить$/i }));
    await userEvent.click(screen.getByRole('button', { name: /^Сохранить$/i }));

    await waitFor(() => expect(putAssignments).toHaveBeenCalledWith(42, [
      { role_id: 7, scope_kind: 'department', scope_id: 3 },
    ]));
  });

  it('объектной области в выборе нет: фильтра по ней стадия не делает', async () => {
    open();
    const scope = await screen.findByLabelText(/Область/i);
    expect(scope).not.toHaveTextContent(/объект/i);
  });
});
