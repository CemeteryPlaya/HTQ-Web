/**
 * Справочник потенциальных поставщиков (T2.3; план §4.1, §4.3): список,
 * поиск, создание и правка с `version` (409 E-CON-01 — сообщение),
 * проверка e-mail; кнопки — по узлу `tender.prospects`.
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { createTestQueryClient } from '@/test/renderWithProviders';

import { ProspectsPage } from './ProspectsPage';

const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
const patch = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get, post, patch, delete: vi.fn() } }));
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() } }));

const flags = vi.hoisted(() => ({ value: ['view', 'create', 'edit'] as string[] }));
vi.mock('@/hooks/usePermissions', () => ({
  usePermissions: () => ({
    atLeast: () => true,
    can: (node: string, flag: string) => node === 'tender.prospects' && flags.value.includes(flag),
    isLoading: false,
  }),
}));

const PROSPECT = {
  id: 'pr-1', name: 'ИП Новый поставщик', email: 'new@supplier.kz', reg_number: '870101300123',
  country_code: 'KZ', counterparty_id: null, version: 3,
};

function renderPage() {
  return render(
    <QueryClientProvider client={createTestQueryClient()}>
      <MemoryRouter initialEntries={['/tender/prospects']}>
        <ProspectsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('ProspectsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    flags.value = ['view', 'create', 'edit'];
    get.mockResolvedValue({ data: [PROSPECT] });
  });

  it('список: имя, e-mail, рег. номер, страна', async () => {
    renderPage();
    const row = (await screen.findByText('ИП Новый поставщик')).closest('tr') as HTMLElement;
    expect(within(row).getByText('new@supplier.kz')).toBeInTheDocument();
    expect(within(row).getByText('870101300123')).toBeInTheDocument();
    expect(within(row).getByText('KZ')).toBeInTheDocument();
  });

  it('создание: POST с полями формы, страна по умолчанию KZ', async () => {
    post.mockResolvedValue({ data: { ...PROSPECT, id: 'pr-2', name: 'ТОО «Бетон»' } });
    renderPage();

    await userEvent.click(await screen.findByRole('button', { name: 'Добавить поставщика' }));
    const dialog = await screen.findByRole('dialog');
    await userEvent.type(within(dialog).getByLabelText('Наименование'), 'ТОО «Бетон»');
    await userEvent.type(within(dialog).getByLabelText('E-mail'), 'beton@mail.kz');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Сохранить' }));

    await waitFor(() => expect(post).toHaveBeenCalled());
    expect(post.mock.calls[0][0]).toContain('tender/v1/prospects');
    expect(post.mock.calls[0][1]).toEqual({
      name: 'ТОО «Бетон»', email: 'beton@mail.kz', reg_number: '', country_code: 'KZ',
    });
  });

  it('неверный e-mail — не уходит', async () => {
    renderPage();
    await userEvent.click(await screen.findByRole('button', { name: 'Добавить поставщика' }));
    const dialog = await screen.findByRole('dialog');
    await userEvent.type(within(dialog).getByLabelText('Наименование'), 'ТОО «Бетон»');
    await userEvent.type(within(dialog).getByLabelText('E-mail'), 'beton.mail.kz');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Сохранить' }));
    expect(await within(dialog).findByText('Укажите e-mail вида name@example.kz')).toBeInTheDocument();
    expect(post).not.toHaveBeenCalled();
  });

  it('правка: PATCH с version; 409 E-CON-01 — сообщение', async () => {
    patch.mockRejectedValueOnce(Object.assign(new Error('409'), {
      response: { status: 409, data: { detail: 'Изменён', code: 'E-CON-01', fields: [] } },
    }));
    renderPage();

    await userEvent.click(await screen.findByRole('button', { name: 'Изменить ИП Новый поставщик' }));
    const dialog = await screen.findByRole('dialog');
    const email = within(dialog).getByLabelText('E-mail');
    await userEvent.clear(email);
    await userEvent.type(email, 'sales@supplier.kz');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Сохранить' }));

    await waitFor(() => expect(patch).toHaveBeenCalled());
    expect(patch.mock.calls[0][0]).toContain('tender/v1/prospects/pr-1');
    expect(patch.mock.calls[0][1]).toMatchObject({ email: 'sales@supplier.kz', version: 3 });
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Карточку поставщика уже изменили');
  });

  it('отказ сервиса по полю email — текст у поля', async () => {
    post.mockRejectedValue(Object.assign(new Error('422'), {
      response: {
        status: 422,
        data: { detail: 'Не удалось сохранить.', code: 'E-VAL-01', fields: [{ field: 'email', message: 'e-mail уже в справочнике' }] },
      },
    }));
    renderPage();
    await userEvent.click(await screen.findByRole('button', { name: 'Добавить поставщика' }));
    const dialog = await screen.findByRole('dialog');
    await userEvent.type(within(dialog).getByLabelText('Наименование'), 'ТОО «Бетон»');
    await userEvent.type(within(dialog).getByLabelText('E-mail'), 'beton@mail.kz');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Сохранить' }));
    expect(await within(dialog).findByText('e-mail уже в справочнике')).toBeInTheDocument();
  });

  it('без права create/edit — кнопок нет', async () => {
    flags.value = ['view'];
    renderPage();
    await screen.findByText('ИП Новый поставщик');
    expect(screen.queryByRole('button', { name: 'Добавить поставщика' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Изменить/ })).not.toBeInTheDocument();
  });

  it('поиск уходит параметром q', async () => {
    renderPage();
    await screen.findByText('ИП Новый поставщик');
    await userEvent.type(screen.getByRole('searchbox'), 'Бетон');
    await waitFor(() => expect(get).toHaveBeenCalledWith(
      expect.stringContaining('tender/v1/prospects'),
      { params: expect.objectContaining({ q: 'Бетон' }) },
    ));
  });
});
