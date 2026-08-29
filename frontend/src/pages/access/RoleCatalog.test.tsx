/**
 * Каталог ролей (§4.1, §4.2).
 *
 * Проверяется то, что отличает этот экран от обычного справочника: он общий
 * для всех компаний. Отсюда три предмета проверки — предупреждение об области
 * действия, отсутствие правки у неплатформенного администратора и читаемый
 * отказ на удаление занятой роли. Плюс главное свойство редактора прав:
 * уходит один `PUT` с полным набором, а не серия точечных правок.
 */
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';
import type { Role, RolePermission } from '@/types/access';

import RoleCatalog from './RoleCatalog';

const listRoles = vi.fn();
const getRolePermissions = vi.fn();
const putRolePermissions = vi.fn();
const deleteRole = vi.fn();
const createRole = vi.fn();

vi.mock('@/api/access', () => ({
  accessApi: {
    listRoles: () => listRoles(),
    getRolePermissions: (id: number) => getRolePermissions(id),
    putRolePermissions: (id: number, permissions: RolePermission[]) =>
      putRolePermissions(id, permissions),
    deleteRole: (id: number) => deleteRole(id),
    createRole: (body: unknown) => createRole(body),
  },
}));

const roles = vi.fn<[], string[]>();

vi.mock('@/hooks/useActiveProfile', () => ({
  useActiveProfile: () => ({ activeProfile: { roles: roles() } }),
}));

const toastError = vi.fn();
const toastSuccess = vi.fn();

vi.mock('sonner', () => ({
  toast: { error: (msg: string) => toastError(msg), success: (msg: string) => toastSuccess(msg) },
}));

const ROLES: Role[] = [
  { id: 12, code: 'hr-admin', title: 'Администратор кадров', is_system: false },
  { id: 3, code: 'system', title: 'Служебная', is_system: true },
];

beforeEach(() => {
  vi.clearAllMocks();
  roles.mockReturnValue(['admin']);
  listRoles.mockResolvedValue({ data: ROLES });
  getRolePermissions.mockResolvedValue({ data: [{ module: 'hr', level: 'read' }] });
  putRolePermissions.mockResolvedValue({ data: [] });
  deleteRole.mockResolvedValue({ data: undefined });
});

describe('RoleCatalog', () => {
  it('предупреждает, что правка действует во всех компаниях', async () => {
    renderWithProviders(<RoleCatalog />);

    expect(
      await screen.findByText(/общий для всех компаний группы/i),
    ).toBeInTheDocument();
  });

  it('не платформенному администратору правка не показывается', async () => {
    roles.mockReturnValue(['staff']);
    renderWithProviders(<RoleCatalog />);

    expect(await screen.findByText('Администратор кадров')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Создать роль/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Удалить роль/i })).not.toBeInTheDocument();
    expect(screen.getByText(/Менять общий каталог может только/i)).toBeInTheDocument();
  });

  it('служебную роль не предлагает удалить даже администратору', async () => {
    renderWithProviders(<RoleCatalog />);

    await screen.findByText('Служебная');
    // Кнопка удаления ровно одна — у несистемной роли.
    expect(screen.getAllByRole('button', { name: /Удалить роль/i })).toHaveLength(1);
  });

  it('отказ на удаление занятой роли показывает, у скольких он отнимет права', async () => {
    deleteRole.mockRejectedValue({
      response: { status: 409, data: { detail: 'in_use', positions: 3, users: 2 } },
    });
    renderWithProviders(<RoleCatalog />);

    await userEvent.click(await screen.findByRole('button', { name: /Удалить роль/i }));

    await waitFor(() => expect(toastError).toHaveBeenCalled());
    const message = toastError.mock.calls[0][0] as string;
    expect(message).toContain('3');
    expect(message).toContain('2');
  });

  it('права роли уходят одним PUT с полным набором', async () => {
    renderWithProviders(<RoleCatalog />);

    await userEvent.click(await screen.findByText('Администратор кадров'));
    await screen.findByLabelText('Кадры: Чтение');

    await userEvent.click(screen.getByLabelText('Задачи и проекты: Запись'));
    await userEvent.click(screen.getByRole('button', { name: /Сохранить права/i }));

    await waitFor(() => expect(putRolePermissions).toHaveBeenCalledTimes(1));
    expect(putRolePermissions).toHaveBeenCalledWith(12, [
      { module: 'hr', level: 'read' },
      { module: 'tasks', level: 'write' },
    ]);
  });

  it('занятый код роли объясняется, а не выглядит общей ошибкой', async () => {
    createRole.mockRejectedValue({ response: { status: 422 } });
    renderWithProviders(<RoleCatalog />);

    await userEvent.type(await screen.findByLabelText('Код роли'), 'hr-admin');
    await userEvent.type(screen.getByLabelText('Название роли'), 'Дубль');
    await userEvent.click(screen.getByRole('button', { name: /Создать роль/i }));

    await waitFor(() => expect(toastError).toHaveBeenCalled());
    expect(toastError.mock.calls[0][0] as string).toMatch(/уникален на всей платформе/i);
  });
});
