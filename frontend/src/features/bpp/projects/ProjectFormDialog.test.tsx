/**
 * Диалог проекта — поле «Заказчик — контрагент» (`customer_counterparty_id`):
 * поиск по реестру контрагентов (только действующие), выбор уходит на
 * сервер, при правке выбранный показывается по карточке и снимается
 * крестиком (сервер понимает пустую строку как «не выбран»).
 */
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

// Под общей нагрузкой прогона форма не укладывается в 5 с (сверка B §20).
vi.setConfig({ testTimeout: 15000 });

import { renderWithProviders } from '@/test/renderWithProviders';

import type { Project } from './api';
import { ProjectFormDialog } from './ProjectFormDialog';

const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
const patch = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get, post, patch } }));
vi.mock('@/api/hr', () => ({
  fetchEmployees: vi.fn(() => Promise.resolve([])),
  fetchDepartments: vi.fn(() => Promise.resolve([])),
}));
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() } }));

const ALPHA = { id: 'cp-alpha', name: 'ТОО «Альфа»', reg_number: '123456789012', status: 'active' };
const BETA = { id: 'cp-beta', name: 'ТОО «Бета»', reg_number: '210987654321', status: 'active' };

const PROJECT: Project = {
  id: 'p-1', code: 'PRJ-001', name: 'ЖК «Орда»', kind: 'project', status: 'active',
  country_code: 'KZ', manager_user_id: null, customer_name: '',
  customer_counterparty_id: 'cp-alpha',
};

let user: ReturnType<typeof userEvent.setup>;

beforeEach(() => {
  user = userEvent.setup({ pointerEventsCheck: 0 });
  get.mockReset();
  post.mockReset();
  patch.mockReset();
  get.mockImplementation((url: string, config?: { params?: Record<string, unknown> }) => {
    if (url.includes('refdata')) return Promise.resolve({ data: [{ code: 'KZ', name: 'Казахстан' }] });
    if (url.endsWith('counterparties/cp-alpha')) return Promise.resolve({ data: ALPHA });
    // Карточка Беты отвечает не сразу: подпись берётся из выбранной строки.
    if (url.endsWith('counterparties/cp-beta')) return new Promise(() => {});
    if (url.endsWith('counterparties')) {
      const q = String(config?.params?.q ?? '');
      const items = [ALPHA, BETA].filter((row) => !q || row.name.includes(q));
      return Promise.resolve({ data: { items, total: items.length } });
    }
    return Promise.resolve({ data: [] });
  });
  post.mockImplementation((_url: string, body: object) =>
    Promise.resolve({ data: { ...PROJECT, ...body, id: 'p-new' } }));
  patch.mockImplementation((_url: string, body: object) =>
    Promise.resolve({ data: { ...PROJECT, ...body } }));
});

const picker = () => screen.getByRole('combobox', { name: 'Заказчик — контрагент' });

describe('ProjectFormDialog — заказчик-контрагент', () => {
  it('ищет по реестру только действующих и отправляет выбранного', async () => {
    const onSaved = vi.fn();
    renderWithProviders(<ProjectFormDialog open onOpenChange={() => {}} onSaved={onSaved} />);

    await user.type(screen.getByLabelText('Код'), 'PRJ-002');
    await user.type(screen.getByLabelText('Наименование'), 'Школа');
    await user.click(picker());
    await user.type(screen.getByPlaceholderText('Наименование или БИН/ИИН'), 'Бета');
    // Поиск уходит на сервер после паузы — до неё список ещё не сужен.
    await waitFor(() => expect(screen.queryByRole('option', { name: /Альфа/ })).toBeNull());
    await user.click(await screen.findByRole('option', { name: /ТОО «Бета»/ }));

    await waitFor(() => expect(picker()).toHaveTextContent('ТОО «Бета»'));
    const searches = get.mock.calls.filter(([url]) => String(url).endsWith('counterparties'));
    expect(searches.at(-1)?.[1]).toEqual({
      params: { q: 'Бета', status: 'active', page_size: 25 },
    });

    await user.click(screen.getByRole('button', { name: 'Создать проект' }));
    await waitFor(() => expect(post).toHaveBeenCalled());
    expect(post.mock.calls[0][1]).toMatchObject({
      code: 'PRJ-002', customer_counterparty_id: 'cp-beta',
    });
  });

  it('при правке показывает выбранного по карточке и снимает выбор крестиком', async () => {
    renderWithProviders(
      <ProjectFormDialog open onOpenChange={() => {}} project={PROJECT} onSaved={() => {}} />,
    );

    await waitFor(() => expect(picker()).toHaveTextContent('ТОО «Альфа»'));
    await user.click(screen.getByRole('button', { name: 'Убрать контрагента' }));
    expect(picker()).toHaveTextContent('Выберите контрагента');

    await user.click(screen.getByRole('button', { name: 'Сохранить' }));
    await waitFor(() => expect(patch).toHaveBeenCalled());
    expect(patch.mock.calls[0][1]).toMatchObject({ customer_counterparty_id: '' });
  });

  it('нет действующих контрагентов — ссылка на заведение контрагента', async () => {
    get.mockImplementation((url: string) => Promise.resolve({
      data: url.endsWith('counterparties') ? { items: [], total: 0 } : [],
    }));
    renderWithProviders(<ProjectFormDialog open onOpenChange={() => {}} onSaved={() => {}} />);

    await user.click(picker());

    const link = await screen.findByRole('link', { name: 'заведите контрагента' });
    expect(link).toHaveAttribute('href', '/bpp/counterparties/new');
    expect(within(screen.getByRole('dialog', { name: 'Новый проект' })).getByText(/Действующих контрагентов нет/))
      .toBeInTheDocument();
  });
});
