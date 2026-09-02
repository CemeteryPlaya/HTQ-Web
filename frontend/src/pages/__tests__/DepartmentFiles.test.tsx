/**
 * Файлы отдела: папок в отделе может быть много.
 *
 * Регресс, ради которого написан тест: страница проваливалась внутрь только
 * что созданной папки и закрывала окно. Папки отдела ПЛОСКИЕ, а внутри папки
 * в пустом состоянии не было кнопки «Создать папку» — пользователь заводил
 * одну папку и упирался в тупик, считая, что больше и не бывает.
 */
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import DepartmentFiles from '@/pages/DepartmentFiles';
import { renderWithProviders } from '@/test/renderWithProviders';
import type { DepartmentFileFolder } from '@/types/fileManager';

const api = vi.hoisted(() => ({
    fetchMyFolders: vi.fn(),
    fetchDepartmentFileFolders: vi.fn(),
    fetchFolderFiles: vi.fn(),
    createDepartmentFileFolder: vi.fn(),
    uploadFile: vi.fn(),
    deleteFile: vi.fn(),
    downloadFileUrl: vi.fn(),
}));
vi.mock('@/api/fileManager', () => api);

const DEPARTMENT = {
    id: 7,
    department: 7,
    department_name: 'ИТ',
    files_count: 0,
    created_at: '2026-08-01T10:00:00Z',
};

const folder = (id: number, name: string): DepartmentFileFolder => ({
    id,
    department: 7,
    name,
    files_count: 0,
    created_by: 1,
    created_by_name: 'Руслан Амиров',
    created_at: '2026-08-01T10:00:00Z',
});

/** Сервер хранит папки отдела — мок ведёт себя как он: создание добавляет
 *  строку, следующий список её возвращает. */
function serverWithFolders(initial: DepartmentFileFolder[] = []) {
    const stored = [...initial];
    api.fetchMyFolders.mockResolvedValue([DEPARTMENT]);
    api.fetchDepartmentFileFolders.mockImplementation(async () => [...stored]);
    api.fetchFolderFiles.mockResolvedValue([]);
    api.createDepartmentFileFolder.mockImplementation(async (_id: number, name: string) => {
        const created = folder(stored.length + 100, name);
        stored.push(created);
        return created;
    });
    return stored;
}

beforeEach(() => {
    Object.values(api).forEach((fn) => fn.mockReset());
});

describe('DepartmentFiles — папки отдела', () => {
    it('позволяет создать несколько папок подряд, не закрывая окно', async () => {
        const user = userEvent.setup();
        serverWithFolders();
        renderWithProviders(<DepartmentFiles />);

        await user.click(await screen.findByRole('button', { name: /Создать папку/ }));
        const dialog = await screen.findByRole('dialog');

        await user.type(within(dialog).getByPlaceholderText(/Например/), 'Регламенты');
        await user.click(within(dialog).getByRole('button', { name: 'Создать' }));

        // Окно осталось открытым и поле пустое — вторая папка набирается сразу.
        await waitFor(() => expect(within(dialog).getByPlaceholderText(/Например/)).toHaveValue(''));
        expect(screen.getByRole('dialog')).toBeInTheDocument();

        await user.type(within(dialog).getByPlaceholderText(/Например/), 'Договоры');
        await user.click(within(dialog).getByRole('button', { name: 'Создать' }));

        await waitFor(() => expect(api.createDepartmentFileFolder).toHaveBeenCalledTimes(2));
        expect(api.createDepartmentFileFolder.mock.calls.map((call) => call[1]))
            .toEqual(['Регламенты', 'Договоры']);
    });

    it('после создания остаётся в корне отдела, а не проваливается в новую папку', async () => {
        const user = userEvent.setup();
        serverWithFolders();
        renderWithProviders(<DepartmentFiles />);

        await user.click(await screen.findByRole('button', { name: /Создать папку/ }));
        const dialog = await screen.findByRole('dialog');
        await user.type(within(dialog).getByPlaceholderText(/Например/), 'Регламенты');
        await user.click(within(dialog).getByRole('button', { name: 'Создать' }));
        await waitFor(() => expect(api.createDepartmentFileFolder).toHaveBeenCalled());

        await user.click(within(dialog).getByRole('button', { name: 'Готово' }));

        // Обе папки видны в сетке корня отдела: значит, страница не ушла внутрь.
        expect(await screen.findByText('Регламенты')).toBeInTheDocument();
        expect(screen.getByRole('heading', { name: 'ИТ' })).toBeInTheDocument();
    });

    it('не даёт создать папку с уже занятым названием', async () => {
        const user = userEvent.setup();
        serverWithFolders([folder(1, 'Регламенты')]);
        renderWithProviders(<DepartmentFiles />);

        await user.click(await screen.findByRole('button', { name: /Создать папку/ }));
        const dialog = await screen.findByRole('dialog');
        await user.type(within(dialog).getByPlaceholderText(/Например/), 'регламенты');

        expect(await within(dialog).findByText(/уже есть/)).toBeInTheDocument();
        expect(within(dialog).getByRole('button', { name: 'Создать' })).toBeDisabled();
        await user.click(within(dialog).getByRole('button', { name: 'Создать' }));
        expect(api.createDepartmentFileFolder).not.toHaveBeenCalled();
    });

    it('предлагает создать папку и из пустой папки — там пользователь и застревал', async () => {
        const user = userEvent.setup();
        serverWithFolders([folder(1, '123')]);
        renderWithProviders(<DepartmentFiles />);

        await user.click(await screen.findByText('123'));

        // Внутри пустой папки: раньше оставалась только загрузка файла.
        const emptyState = await screen.findByText('Папка пуста');
        expect(emptyState).toBeInTheDocument();
        const createButtons = await screen.findAllByRole('button', { name: /Создать папку/ });
        expect(createButtons.length).toBeGreaterThan(1);

        // И диалог честно говорит, что папка ляжет в отдел, а не внутрь «123».
        await user.click(createButtons[createButtons.length - 1]);
        const dialog = await screen.findByRole('dialog');
        expect(within(dialog).getByText(/появится в отделе «ИТ»/)).toBeInTheDocument();
    });
});
