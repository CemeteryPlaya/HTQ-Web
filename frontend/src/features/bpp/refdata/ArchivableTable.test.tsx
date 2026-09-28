/**
 * Экран архивируемого справочника (задача 9, A2.4) на примере «Стран»:
 * кнопки правки включает `can_edit` из ответа сервера, архивная запись
 * остаётся в списке с меткой «Архив», экран читает полный список (без
 * `?active=1`).
 */
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';

import CountriesTab from './CountriesTab';

const get = vi.hoisted(() => vi.fn());
const patch = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get, patch, post } }));

const toastError = vi.hoisted(() => vi.fn());
vi.mock('sonner', () => ({ toast: { error: toastError, success: vi.fn(), info: vi.fn() } }));

const country = (over: Record<string, unknown>) => ({
  id: 'c-kz', code: 'KZ', name: 'Казахстан', is_active: true, can_edit: true, ...over,
});

const rowOf = (text: string) => screen.getByText(text).closest('tr')!;

beforeEach(() => {
  get.mockReset();
  patch.mockReset();
  post.mockReset();
  toastError.mockReset();
});

describe('ArchivableTable (Страны)', () => {
  it('вне управляющей компании (can_edit=false) кнопки выключены и есть объяснение', async () => {
    get.mockResolvedValue({
      data: [
        country({ can_edit: false }),
        country({ id: 'c-ru', code: 'RU', name: 'Россия', can_edit: false }),
      ],
    });
    renderWithProviders(<CountriesTab />);

    await screen.findByText('Казахстан');
    expect(screen.getByRole('button', { name: 'Добавить' })).toBeDisabled();
    for (const button of screen.getAllByRole('button', { name: 'Изменить' })) {
      expect(button).toBeDisabled();
    }
    for (const button of screen.getAllByRole('button', { name: 'В архив' })) {
      expect(button).toBeDisabled();
    }
    expect(screen.getByRole('note')).toHaveTextContent('управляющая компания');
  });

  it('в управляющей компании (can_edit=true) кнопки включены, объяснения нет', async () => {
    get.mockResolvedValue({ data: [country({})] });
    renderWithProviders(<CountriesTab />);

    await screen.findByText('Казахстан');
    expect(screen.getByRole('button', { name: 'Добавить' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Изменить' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'В архив' })).toBeEnabled();
    expect(screen.queryByRole('note')).not.toBeInTheDocument();
  });

  it('экран читает полный список — без ?active=1', async () => {
    get.mockResolvedValue({ data: [country({})] });
    renderWithProviders(<CountriesTab />);

    await screen.findByText('Казахстан');
    expect(get).toHaveBeenCalledWith('refdata/v1/countries', { params: undefined });
  });

  it('архивная запись видна в списке с меткой «Архив» и кнопкой «Восстановить»', async () => {
    get.mockResolvedValue({
      data: [
        country({}),
        country({ id: 'c-su', code: 'SU', name: 'СССР', is_active: false }),
      ],
    });
    renderWithProviders(<CountriesTab />);

    await screen.findByText('СССР');
    const archived = rowOf('СССР');
    expect(within(archived).getByText('Архив')).toBeInTheDocument();
    expect(within(archived).getByRole('button', { name: 'Восстановить' })).toBeEnabled();
    const active = rowOf('Казахстан');
    expect(within(active).getByText('Действует')).toBeInTheDocument();
    expect(within(active).queryByText('Архив')).not.toBeInTheDocument();
  });

  it('«В архив» — PATCH is_active=false, затем список перечитывается', async () => {
    get.mockResolvedValue({ data: [country({})] });
    patch.mockResolvedValue({ data: country({ is_active: false }) });
    renderWithProviders(<CountriesTab />);

    await screen.findByText('Казахстан');
    fireEvent.click(screen.getByRole('button', { name: 'В архив' }));

    await waitFor(() => {
      expect(patch).toHaveBeenCalledWith('refdata/v1/countries/c-kz', { is_active: false });
    });
    await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
  });

  it('«Восстановить» — PATCH is_active=true', async () => {
    get.mockResolvedValue({ data: [country({ is_active: false })] });
    patch.mockResolvedValue({ data: country({}) });
    renderWithProviders(<CountriesTab />);

    fireEvent.click(await screen.findByRole('button', { name: 'Восстановить' }));
    await waitFor(() => {
      expect(patch).toHaveBeenCalledWith('refdata/v1/countries/c-kz', { is_active: true });
    });
  });

  it('добавление: код приводится к верхнему регистру; двойной клик — один запрос', async () => {
    get.mockResolvedValue({ data: [country({})] });
    let resolve: (value: unknown) => void = () => {};
    post.mockReturnValue(new Promise((r) => { resolve = r; }));
    renderWithProviders(<CountriesTab />);

    await screen.findByText('Казахстан'); // до ответа кнопка выключена
    fireEvent.click(screen.getByRole('button', { name: 'Добавить' }));
    const dialog = await screen.findByRole('dialog');
    const save = within(dialog).getByRole('button', { name: 'Сохранить' });
    expect(save).toBeDisabled(); // обязательные поля пусты
    fireEvent.change(within(dialog).getByLabelText('Код'), { target: { value: 'de' } });
    fireEvent.change(within(dialog).getByLabelText('Наименование'), {
      target: { value: ' Германия ' },
    });
    fireEvent.click(save);
    fireEvent.click(save);

    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(post).toHaveBeenCalledWith('refdata/v1/countries', { code: 'DE', name: 'Германия' });
    resolve({ data: country({ id: 'c-de', code: 'DE', name: 'Германия' }) });
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('отказ сервера (E-REF-01) показывается его текстом', async () => {
    get.mockResolvedValue({ data: [country({})] });
    patch.mockRejectedValue({
      isAxiosError: true,
      response: {
        status: 403,
        data: {
          detail: 'Справочники ведёт управляющая компания. Откройте раздел на её поддомене или обратитесь к финансовому директору.',
          code: 'E-REF-01',
        },
      },
    });
    renderWithProviders(<CountriesTab />);

    fireEvent.click(await screen.findByRole('button', { name: 'В архив' }));
    await waitFor(() => expect(toastError).toHaveBeenCalled());
    expect(toastError.mock.calls[0][0]).toMatch(/^Справочники ведёт управляющая компания\./);
  });
});
