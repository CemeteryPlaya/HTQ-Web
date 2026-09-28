/**
 * Реестр модуля (ТЗ §19; задача 8): серверные страницы и сортировка,
 * скрытые колонки переживают перемонтирование, массовое действие возвращает
 * результат по строкам, «Экспорт» — синхронный файл и фоновая очередь.
 */
import type { ComponentProps } from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { createTestQueryClient } from '@/test/renderWithProviders';

import { BppRegistry } from './BppRegistry';
import type { RegistryColumn } from './registryTypes';

interface Row { id: string; number: string; status: string }

const get = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get } }));

const exportRegistry = vi.hoisted(() => vi.fn());
vi.mock('./registryExport', () => ({ exportRegistry }));

const toastInfo = vi.hoisted(() => vi.fn());
const toastError = vi.hoisted(() => vi.fn());
vi.mock('sonner', () => ({ toast: { info: toastInfo, error: toastError, success: vi.fn() } }));

const COLUMNS: RegistryColumn<Row>[] = [
  { key: 'number', title: 'Номер', required: true, sortable: true },
  { key: 'status', title: 'Статус', sortable: 'status' },
];

const page = (rows: Row[], total: number) => ({ items: rows, total, page: 1, page_size: 50 });

const row = (id: string, number: string, status = 'draft'): Row => ({ id, number, status });

function setup(props: Partial<ComponentProps<typeof BppRegistry<Row>>> = {}) {
  const queryClient = createTestQueryClient();
  const utils = render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <BppRegistry<Row>
          registryKey="test-registry"
          endpoint="/bpp/v1/requests"
          columns={COLUMNS}
          {...props}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { queryClient, ...utils };
}

describe('BppRegistry', () => {
  beforeEach(() => {
    window.localStorage.clear();
    get.mockReset();
    exportRegistry.mockReset();
    toastInfo.mockReset();
    toastError.mockReset();
  });
  afterEach(() => window.localStorage.clear());

  it('смена страницы и сортировки уходит в запрос', async () => {
    const user = userEvent.setup();
    get.mockResolvedValue({ data: page([row('1', 'ЗЗ-01'), row('2', 'ЗЗ-02')], 60) });

    setup();

    await waitFor(() => expect(get).toHaveBeenCalled());
    expect(get.mock.calls[0][1].params).toMatchObject({ page: 1, page_size: 50 });

    await user.click(screen.getByRole('button', { name: 'Следующая страница' }));
    await waitFor(() =>
      expect(get.mock.calls.at(-1)?.[1].params).toMatchObject({ page: 2, page_size: 50 }));

    await user.click(screen.getByRole('button', { name: 'Номер' }));
    await waitFor(() => {
      const last = get.mock.calls.at(-1)?.[1].params;
      expect(last.sort).toBe('number');
      expect(last.page).toBe(1); // смена сортировки вернула на первую страницу
    });

    await user.click(screen.getByRole('button', { name: 'Номер' }));
    await waitFor(() => expect(get.mock.calls.at(-1)?.[1].params.sort).toBe('-number'));
  });

  it('скрытая колонка остаётся скрытой после перемонтирования', async () => {
    const user = userEvent.setup();
    get.mockResolvedValue({ data: page([row('1', 'ЗЗ-01')], 1) });

    const first = setup();
    await screen.findByRole('columnheader', { name: 'Статус' });

    await user.click(screen.getByRole('button', { name: 'Колонки' }));
    await user.click(await screen.findByRole('menuitemcheckbox', { name: 'Статус' }));
    expect(screen.queryByRole('columnheader', { name: 'Статус' })).not.toBeInTheDocument();
    first.unmount();

    setup();
    await screen.findByRole('columnheader', { name: 'Номер' });
    expect(screen.queryByRole('columnheader', { name: 'Статус' })).not.toBeInTheDocument();
  });

  it('массовое действие — результат по строкам: успехи и отказы', async () => {
    const user = userEvent.setup();
    get.mockResolvedValue({ data: page([row('1', 'ЗЗ-01'), row('2', 'ЗЗ-02')], 2) });
    const run = vi.fn().mockResolvedValue({
      ok: ['1'], failed: [{ id: '2', reason: 'Нет прав' }],
    });

    setup({
      bulkActions: [{ key: 'approve', label: 'Утвердить', run }],
      rowLabel: (r) => r.number,
    });

    await screen.findByRole('columnheader', { name: 'Номер' });
    await user.click(screen.getByRole('checkbox', { name: 'Отметить все на странице' }));
    await user.click(screen.getByRole('button', { name: 'Утвердить' }));

    await waitFor(() => expect(run).toHaveBeenCalledWith(['1', '2']));
    const outcome = (await screen.findByText(/выполнено — 1, отклонено — 1/)).closest('div')!;
    expect(within(outcome).getByText('ЗЗ-02')).toBeInTheDocument();
    expect(within(outcome).getByText(/Нет прав/)).toBeInTheDocument();
  });

  it('экспорт — синхронный файл: без сообщения о фоне', async () => {
    const user = userEvent.setup();
    get.mockResolvedValue({ data: page([row('1', 'ЗЗ-01')], 1) });
    exportRegistry.mockResolvedValue({ kind: 'file', filename: 'export.xlsx' });

    setup({ exportName: 'requests' });
    await screen.findByRole('columnheader', { name: 'Номер' });

    await user.click(screen.getByRole('button', { name: 'Экспорт' }));
    await waitFor(() => expect(exportRegistry).toHaveBeenCalledTimes(1));
    expect(exportRegistry.mock.calls[0][0]).toBe('/bpp/v1/requests');
    expect(exportRegistry.mock.calls[0][2]).toBe('requests');
    expect(toastInfo).not.toHaveBeenCalled();
  });

  it('экспорт — фоновая очередь: сообщение о том, что ссылка придёт уведомлением', async () => {
    const user = userEvent.setup();
    get.mockResolvedValue({ data: page([row('1', 'ЗЗ-01')], 1) });
    exportRegistry.mockResolvedValue({ kind: 'queued', id: 'job-1', detail: 'в фоне' });

    setup({ exportName: 'requests' });
    await screen.findByRole('columnheader', { name: 'Номер' });

    await user.click(screen.getByRole('button', { name: 'Экспорт' }));
    await waitFor(() =>
      expect(toastInfo).toHaveBeenCalledWith('Выгрузка готовится, ссылка придёт уведомлением'));
  });

  it('ошибка экспорта — тост с объяснением', async () => {
    const user = userEvent.setup();
    get.mockResolvedValue({ data: page([row('1', 'ЗЗ-01')], 1) });
    exportRegistry.mockRejectedValue(new Error('boom'));

    setup({ exportName: 'requests' });
    await screen.findByRole('columnheader', { name: 'Номер' });
    await user.click(screen.getByRole('button', { name: 'Экспорт' }));

    await waitFor(() => expect(toastError).toHaveBeenCalled());
  });

  it('реестр без выгрузки — тост своим текстом, а не запасной фразой', async () => {
    const user = userEvent.setup();
    get.mockResolvedValue({ data: page([row('1', 'ЗЗ-01')], 1) });
    exportRegistry.mockRejectedValue(Object.assign(
      new Error('Реестр не поддерживает выгрузку в xlsx. Сообщите администратору.'),
      { name: 'ExportNotSupportedError' },
    ));

    setup({ exportName: 'requests' });
    await screen.findByRole('columnheader', { name: 'Номер' });
    await user.click(screen.getByRole('button', { name: 'Экспорт' }));

    await waitFor(() => expect(toastError).toHaveBeenCalledWith(
      'Реестр не поддерживает выгрузку в xlsx. Сообщите администратору.'));
  });

  it('первая колонка — настоящая ссылка на документ (клавиатура, новая вкладка)', async () => {
    get.mockResolvedValue({ data: page([row('1', 'ЗЗ-01')], 1) });
    setup({ rowHref: (r) => `/bpp/requests/${r.id}` });

    const link = await screen.findByRole('link', { name: 'ЗЗ-01' });
    expect(link).toHaveAttribute('href', '/bpp/requests/1');
    // Остальные ячейки — не ссылки: одна ссылка на строку.
    expect(screen.getAllByRole('link')).toHaveLength(1);
  });

  it('выборка сократилась — страница прижимается к последней', async () => {
    const user = userEvent.setup();
    get.mockResolvedValueOnce({ data: page([row('1', 'ЗЗ-01')], 120) });
    get.mockResolvedValueOnce({ data: page([row('2', 'ЗЗ-51')], 120) });
    const { queryClient } = setup();
    // Как в приложении: вернувшись на первую страницу, реестр перечитывает её.
    queryClient.setDefaultOptions({ queries: { retry: false, staleTime: 0 } });

    await screen.findByText('ЗЗ-01');
    await user.click(screen.getByRole('button', { name: 'Следующая страница' }));
    await screen.findByText('ЗЗ-51');
    // Пока смотрели вторую страницу, строки ушли: выборка — одна страница.
    get.mockResolvedValue({ data: page([], 30) });
    await user.click(screen.getByRole('button', { name: 'Следующая страница' }));

    await waitFor(() => expect(get.mock.calls.at(-1)?.[1].params.page).toBe(1));
    expect(await screen.findByText('Страница 1 из 1')).toBeInTheDocument();
  });

  it('смена страницы снимает отметки строк', async () => {
    const user = userEvent.setup();
    get.mockResolvedValue({ data: page([row('1', 'ЗЗ-01'), row('2', 'ЗЗ-02')], 120) });
    setup({
      bulkActions: [{ key: 'approve', label: 'Утвердить', run: vi.fn() }],
      rowLabel: (r) => r.number,
    });

    await screen.findByText('ЗЗ-01');
    await user.click(screen.getByRole('checkbox', { name: 'Отметить ЗЗ-01' }));
    expect(screen.getByText('Отмечено: 1')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Следующая страница' }));
    await waitFor(() => expect(screen.queryByText(/Отмечено:/)).not.toBeInTheDocument());
  });

  it('текстовый фильтр уходит в запрос после паузы, а не на каждую букву', async () => {
    const user = userEvent.setup();
    get.mockResolvedValue({ data: page([row('1', 'ЗЗ-01')], 1) });
    setup({ filters: [{ key: 'name', label: 'Наименование', kind: 'text' }] });

    await screen.findByText('ЗЗ-01');
    const calls = get.mock.calls.length;
    await user.type(screen.getByLabelText('Наименование'), 'бетон');
    await waitFor(() => expect(get.mock.calls.at(-1)?.[1].params.name).toBe('бетон'));
    // Один новый запрос на всё слово, а не пять.
    expect(get.mock.calls.length - calls).toBe(1);
  });
});
