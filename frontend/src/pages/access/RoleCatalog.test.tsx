/**
 * Каталог ролей (§4.1, §4.2).
 *
 * Проверяется то, что отличает этот экран от обычного справочника: он общий
 * для всех компаний. Отсюда три предмета проверки — предупреждение об области
 * действия, отсутствие правки у неплатформенного администратора и читаемый
 * отказ на удаление занятой роли. Плюс главное свойство редактора прав:
 * уходит один `PUT` с полным набором, а не серия точечных правок.
 */
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';
import type { Role, RolePermission } from '@/types/access';

import RoleCatalog from './RoleCatalog';

const listRoles = vi.fn();
const getFunctions = vi.fn();
const getRolePermissions = vi.fn();
const putRolePermissions = vi.fn();
const deleteRole = vi.fn();
const copyRole = vi.fn();
const getRoleHolders = vi.fn();
const renameRole = vi.fn();
const createRole = vi.fn();

vi.mock('@/api/access', () => ({
  accessApi: {
    listRoles: () => listRoles(),
    getFunctions: () => getFunctions(),
    getRolePermissions: (id: number) => getRolePermissions(id),
    putRolePermissions: (id: number, permissions: RolePermission[]) =>
      putRolePermissions(id, permissions),
    deleteRole: (id: number) => deleteRole(id),
    copyRole: (id: number, body: unknown) => copyRole(id, body),
    getRoleHolders: (id: number) => getRoleHolders(id),
    renameRole: (id: number, body: unknown) => renameRole(id, body),
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

const REGISTRY = {
  tree: [
    { path: 'hr', title: 'Кадры', kind: 'module' as const,
      flags: ['view' as const, 'create' as const, 'edit' as const, 'delete' as const],
      presets: ['none' as const, 'view' as const, 'edit' as const], children: [] },
    { path: 'tasks', title: 'Задачи', kind: 'module' as const,
      flags: ['view' as const, 'create' as const, 'edit' as const, 'delete' as const],
      presets: ['none' as const, 'view' as const, 'edit' as const], children: [] },
  ],
  pages: [],
  flags: [
    { key: 'view' as const, title: 'видит' },
    { key: 'create' as const, title: 'вводит' },
    { key: 'edit' as const, title: 'редактирует' },
    { key: 'delete' as const, title: 'удаляет' },
  ],
  presets: [
    { key: 'none' as const, title: 'нет доступа', flags: [] },
    { key: 'view' as const, title: 'видит', flags: ['view' as const] },
    { key: 'edit' as const, title: 'может редактировать',
      flags: ['view' as const, 'create' as const, 'edit' as const] },
  ],
};

const ROLES: Role[] = [
  { id: 12, code: 'hr-admin', title: 'Администратор кадров', is_system: false },
  { id: 3, code: 'system', title: 'Служебная', is_system: true },
];

beforeEach(() => {
  vi.clearAllMocks();
  roles.mockReturnValue(['admin']);
  listRoles.mockResolvedValue({ data: ROLES });
  getRolePermissions.mockResolvedValue({
    data: [{ node: 'hr', flags: ['view'], preset: 'view' }],
  });
  getFunctions.mockResolvedValue({ data: REGISTRY });
  putRolePermissions.mockResolvedValue({ data: [] });
  deleteRole.mockResolvedValue({ data: undefined });
  getRoleHolders.mockResolvedValue({ data: [] });
  renameRole.mockResolvedValue({ data: ROLES[0] });
  copyRole.mockResolvedValue({ data: { id: 99, code: 'hr-admin-copy', title: 'Копия', is_system: false } });
});

describe('RoleCatalog', () => {
  it('обрамлена как остальные страницы: шапка, «назад», подвал', async () => {
    // Страница появилась позже соседних и сначала жила голым блоком без
    // каркаса — попасть на неё можно было только по прямому адресу, и уйти
    // с неё, кроме как кнопкой браузера, тоже было нечем.
    const { container } = renderWithProviders(<RoleCatalog />);

    await screen.findByText('Администратор кадров');
    expect(screen.getByRole('link', { name: /профил/i })).toHaveAttribute('href', '/myprofile');
    expect(container.querySelector('header')).toBeInTheDocument();
    expect(container.querySelector('footer')).toBeInTheDocument();
  });

  it('копирование идёт через форму, где код и название можно поправить', async () => {
    // Прежде копия создавалась сразу и навсегда оставалась «(копия)» с кодом
    // «-copy»: вторая копия того же исходника уже не заводилась — код уникален
    // на всей платформе.
    renderWithProviders(<RoleCatalog />);

    const buttons = await screen.findAllByRole('button', { name: /Копировать роль/i });
    await userEvent.click(buttons[0]);

    // Поиск ограничен диалогом: на самой странице есть своя форма создания
    // роли с теми же подписями полей.
    const dialog = within(await screen.findByRole('dialog'));
    const code = dialog.getByLabelText('Код роли');
    expect(code).toHaveValue('hr-admin-copy');
    await userEvent.clear(code);
    await userEvent.type(code, 'hr-viewer');
    await userEvent.click(dialog.getByRole('button', { name: /Создать роль/i }));

    await waitFor(() => expect(copyRole).toHaveBeenCalledTimes(1));
    expect(copyRole).toHaveBeenCalledWith(12, expect.objectContaining({ code: 'hr-viewer' }));
  });

  it('переименование шлёт и код, и название', async () => {
    renderWithProviders(<RoleCatalog />);

    const buttons = await screen.findAllByRole('button', { name: /Переименовать роль/i });
    await userEvent.click(buttons[0]);

    const dialog = within(await screen.findByRole('dialog'));
    const title = dialog.getByLabelText('Название роли');
    await userEvent.clear(title);
    await userEvent.type(title, 'Кадры: лид');
    await userEvent.click(dialog.getByRole('button', { name: /^Сохранить$/ }));

    await waitFor(() => expect(renameRole).toHaveBeenCalledTimes(1));
    expect(renameRole).toHaveBeenCalledWith(12, { code: 'hr-admin', title: 'Кадры: лид' });
  });

  it('у системной роли код не отправляется — на сервере он заблокирован', async () => {
    renderWithProviders(<RoleCatalog />);

    const buttons = await screen.findAllByRole('button', { name: /Переименовать роль/i });
    await userEvent.click(buttons[1]);

    const dialog = within(await screen.findByRole('dialog'));
    await userEvent.click(dialog.getByRole('button', { name: /^Сохранить$/ }));

    await waitFor(() => expect(renameRole).toHaveBeenCalledTimes(1));
    expect(renameRole).toHaveBeenCalledWith(3, { title: 'Служебная' });
  });

  it('копировать можно и служебную роль — удалять её по-прежнему нельзя', async () => {
    renderWithProviders(<RoleCatalog />);

    await screen.findByText('Служебная');
    expect(await screen.findAllByRole('button', { name: /Копировать роль/i })).toHaveLength(2);
    expect(screen.getAllByRole('button', { name: /Удалить роль/i })).toHaveLength(1);
  });

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

  it('удаление идёт через диалог, а не немедленным запросом', async () => {
    // Прежде кнопка сразу слала DELETE и показывала 409 с числами. Числа не
    // говорят, к кому идти: снять роль по такому ответу нельзя. Теперь сначала
    // показываются держатели, и только свободную роль дают удалить.
    getRoleHolders.mockResolvedValue({
      data: [{
        user_id: 2, full_name: 'Петров Пётр', company: 'htq-kz',
        department: 'Строительство', position: 'Прораб',
        source: 'position', position_id: 7,
      }],
    });
    renderWithProviders(<RoleCatalog />);

    await userEvent.click(await screen.findByRole('button', { name: /Удалить роль/i }));

    expect(await screen.findByText('Петров Пётр')).toBeInTheDocument();
    expect(deleteRole).not.toHaveBeenCalled();
  });

  it('права роли уходят одним PUT с полным набором', async () => {
    renderWithProviders(<RoleCatalog />);

    await userEvent.click(await screen.findByText('Администратор кадров'));
    await screen.findByLabelText('Кадры: Глубина');

    await userEvent.selectOptions(screen.getByLabelText('Задачи: Глубина'), 'edit');
    await userEvent.click(screen.getByRole('button', { name: /Сохранить права/i }));

    await waitFor(() => expect(putRolePermissions).toHaveBeenCalledTimes(1));
    // Наружу уходят пресеты, а не флаги: так тело запроса читается глазами,
    // а сервер разворачивает пресет сам.
    expect(putRolePermissions).toHaveBeenCalledWith(12, [
      { node: 'hr', preset: 'view' },
      { node: 'tasks', preset: 'edit' },
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
