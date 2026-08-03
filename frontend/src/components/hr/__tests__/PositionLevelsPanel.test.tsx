import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { renderWithProviders } from '@/test/renderWithProviders';

vi.mock('@/api/client', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

import api from '@/api/client';
import PositionLevelsPanel from '../PositionLevelsPanel';

const mockedApi = vi.mocked(api, true);

const LEVELS = [
  { id: 1, level_number: 1, weight_from: 0, weight_to: 99, label: 'Руководство', color: '#8b5cf6' },
  { id: 3, level_number: 3, weight_from: 300, weight_to: 599, label: 'Руководители', color: '#10b981' },
];

const POSITIONS = [
  { id: 1, level: 1 },
  { id: 2, level: 1 },
  { id: 3, level: 3 },
];

beforeEach(() => {
  vi.clearAllMocks();
  mockedApi.get.mockImplementation(((url: string) => {
    if (url.includes('positions/levels')) return Promise.resolve({ data: LEVELS });
    return Promise.resolve({ data: POSITIONS });
  }) as never);
});

describe('PositionLevelsPanel — создание без диапазонов', () => {
  it('не спрашивает у HR диапазон весов', async () => {
    renderWithProviders(<PositionLevelsPanel />);
    await screen.findByDisplayValue('Руководство');

    // Форма создания: только номер, название и цвет.
    expect(screen.getByLabelText(/номер уровня/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/название уровня/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/цвет нового уровня/i)).toBeInTheDocument();
    expect(screen.queryByPlaceholderText(/^от$/i)).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText(/^до$/i)).not.toBeInTheDocument();
  });

  it('шлёт POST без weight_from/weight_to — диапазон подбирает сервер', async () => {
    const user = userEvent.setup();
    mockedApi.post.mockResolvedValue({ data: {} });

    renderWithProviders(<PositionLevelsPanel />);
    await screen.findByDisplayValue('Руководство');

    await user.type(screen.getByLabelText(/номер уровня/i), '4');
    await user.type(screen.getByLabelText(/название уровня/i), 'Специалисты');
    await user.click(screen.getByRole('button', { name: /добавить/i }));

    await waitFor(() => expect(mockedApi.post).toHaveBeenCalled());
    const [url, payload] = mockedApi.post.mock.calls[0];
    expect(url).toContain('positions/levels');
    expect(payload).toMatchObject({ level_number: 4, label: 'Специалисты' });
    expect(payload).not.toHaveProperty('weight_from');
    expect(payload).not.toHaveProperty('weight_to');
  });

  it('показывает объяснение сервера при 409', async () => {
    const user = userEvent.setup();
    mockedApi.post.mockRejectedValue({
      response: {
        status: 409,
        data: { detail: 'Между L1 (0-99) и L3 (300-599) нет свободных весов' },
      },
    });

    renderWithProviders(<PositionLevelsPanel />);
    await screen.findByDisplayValue('Руководство');

    await user.type(screen.getByLabelText(/номер уровня/i), '2');
    await user.click(screen.getByRole('button', { name: /добавить/i }));

    // Раньше ошибка терялась целиком: у мутаций не было onError.
    expect(await screen.findByText(/нет свободных весов/i)).toBeInTheDocument();
  });
});

describe('PositionLevelsPanel — удаление', () => {
  it('называет число затронутых должностей в подтверждении', async () => {
    const user = userEvent.setup();
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);

    renderWithProviders(<PositionLevelsPanel />);
    await screen.findByDisplayValue('Руководство');

    // На L1 две должности из фикстуры.
    await user.click(screen.getAllByTitle('Удалить')[0]);

    expect(confirmSpy).toHaveBeenCalledWith(expect.stringContaining('2 должн'));
    expect(mockedApi.delete).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it('на пустом уровне спрашивает без запугивания', async () => {
    const user = userEvent.setup();
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);

    mockedApi.get.mockImplementation(((url: string) => {
      if (url.includes('positions/levels')) return Promise.resolve({ data: LEVELS });
      return Promise.resolve({ data: [] });   // должностей нет вовсе
    }) as never);

    renderWithProviders(<PositionLevelsPanel />);
    await screen.findByDisplayValue('Руководство');
    await user.click(screen.getAllByTitle('Удалить')[0]);

    expect(confirmSpy).toHaveBeenCalledWith('Удалить уровень L1?');
    confirmSpy.mockRestore();
  });

  it('показывает счётчик должностей по каждому уровню', async () => {
    renderWithProviders(<PositionLevelsPanel />);
    await screen.findByDisplayValue('Руководство');

    expect(screen.getByText('2 должн.')).toBeInTheDocument();
    expect(screen.getByText('1 должн.')).toBeInTheDocument();
  });
});
