/**
 * Выбор контрагента: пустой список объясняет, почему он пуст — «нет
 * действующих» (без поиска), «ничего не найдено по запросу» (с поиском) или
 * отказ сервера (403/503: текст сервера всплывающим сообщением, а не
 * «ничего не найдено», читающееся как «таких нет»).
 */
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';

import { CounterpartyPicker } from './CounterpartyPicker';

const get = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get } }));

const toastError = vi.hoisted(() => vi.fn());
vi.mock('sonner', () => ({ toast: { error: toastError, success: vi.fn(), info: vi.fn() } }));

const ALPHA = { id: 'cp-alpha', name: 'ТОО «Альфа»', reg_number: '123456789012', status: 'active' };

let user: ReturnType<typeof userEvent.setup>;

beforeEach(() => {
  user = userEvent.setup({ pointerEventsCheck: 0 });
  get.mockReset();
  toastError.mockReset();
});

const open = async () => {
  renderWithProviders(<CounterpartyPicker value={null} onChange={() => {}} />);
  await user.click(screen.getByRole('combobox'));
};

describe('CounterpartyPicker — пустой список', () => {
  it('без поиска — «Нет действующих контрагентов» и ссылка на заведение', async () => {
    get.mockResolvedValue({ data: { items: [], total: 0 } });
    await open();

    expect(await screen.findByText('Нет действующих контрагентов')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'заведите контрагента' }))
      .toHaveAttribute('href', '/bpp/counterparties/new');
    expect(screen.queryByText(/Ничего не найдено/)).toBeNull();
  });

  it('с поиском — «Ничего не найдено по запросу», без ссылки на заведение', async () => {
    get.mockImplementation((_url: string, config?: { params?: Record<string, unknown> }) => {
      const items = config?.params?.q ? [] : [ALPHA];
      return Promise.resolve({ data: { items, total: items.length } });
    });
    await open();
    await screen.findByRole('option', { name: /Альфа/ });

    await user.type(screen.getByPlaceholderText('Наименование или БИН/ИИН'), 'Гамма');

    expect(await screen.findByText('Ничего не найдено по запросу «Гамма»')).toBeInTheDocument();
    expect(screen.queryByText('Нет действующих контрагентов')).toBeNull();
    expect(screen.queryByRole('link', { name: 'заведите контрагента' })).toBeNull();
  });

  it('отказ сервера — его текст сообщением, в списке «не удалось загрузить»', async () => {
    get.mockRejectedValue({
      response: { status: 503, data: { detail: 'Модуль «Бюджет, закупки и оплаты» выключен' } },
    });
    await open();

    expect(await screen.findByText('Не удалось загрузить контрагентов')).toBeInTheDocument();
    await waitFor(() => expect(toastError).toHaveBeenCalledWith(
      'Модуль «Бюджет, закупки и оплаты» выключен', undefined));
    expect(toastError).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/Ничего не найдено/)).toBeNull();
    expect(screen.queryByText('Нет действующих контрагентов')).toBeNull();
    expect(screen.queryByRole('link', { name: 'заведите контрагента' })).toBeNull();
  });
});
