/**
 * «Статьи»: родительская статья — только из группы новой статьи (сервер
 * отвечает на чужую 422 `E-REF-05`), список родителей строится по выбранной
 * группе и сбрасывается при её смене.
 */
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';

import ArticlesTab from './ArticlesTab';

const get = vi.hoisted(() => vi.fn());
const patch = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get, patch, post } }));

vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() } }));

const groups = [
  { id: 'g-sup', code: 'supply', name: 'Снабжение', node_key: 'bpp.articles.supply', is_active: true, can_edit: true },
  { id: 'g-pm', code: 'pm', name: 'Проектное управление', node_key: 'bpp.articles.pm', is_active: true, can_edit: true },
];
const article = (id: string, code: string, name: string, group_id: string) => ({
  id, code, name, group_id, parent_id: null, ext_1c_ref: '', is_active: true, can_edit: true,
});
const articles = [
  article('a-mat', '100', 'Материалы', 'g-sup'),
  article('a-srv', '200', 'Услуги консультантов', 'g-pm'),
];

// Radix оставляет `pointer-events: none` на body после закрытого в прошлом
// тесте диалога — проверка user-event здесь ничего не ловит.
let user: ReturnType<typeof userEvent.setup>;

beforeEach(() => {
  user = userEvent.setup({ pointerEventsCheck: 0 });
  get.mockReset();
  post.mockReset();
  get.mockImplementation((url: string) => Promise.resolve({
    data: url.includes('article-groups') ? groups : articles,
  }));
  post.mockResolvedValue({ data: {} });
});

async function openCreateArticle() {
  await screen.findByText('Материалы');
  const section = screen.getByRole('heading', { name: 'Статьи' }).closest('section')!;
  await user.click(within(section).getByRole('button', { name: 'Добавить' }));
  return screen.findByRole('dialog');
}

const optionNames = () => screen.getAllByRole('option').map((o) => o.textContent);

describe('ArticlesTab — родительская статья', () => {
  it('предлагает родителей только из выбранной группы', async () => {
    renderWithProviders(<ArticlesTab />);
    const dialog = await openCreateArticle();

    await user.click(within(dialog).getByRole('combobox', { name: 'Группа' }));
    await user.click(await screen.findByRole('option', { name: 'Снабжение' }));
    await user.click(within(dialog).getByRole('combobox', { name: 'Родительская статья' }));

    await waitFor(() => expect(optionNames()).toContain('100 Материалы'));
    expect(optionNames()).not.toContain('200 Услуги консультантов');
  });

  it('без группы выбрать родителя не из чего', async () => {
    renderWithProviders(<ArticlesTab />);
    const dialog = await openCreateArticle();

    await user.click(within(dialog).getByRole('combobox', { name: 'Родительская статья' }));

    await waitFor(() => expect(optionNames()).toEqual(['— нет —']));
  });

  it('смена группы сбрасывает выбранного родителя', async () => {
    renderWithProviders(<ArticlesTab />);
    const dialog = await openCreateArticle();
    const group = within(dialog).getByRole('combobox', { name: 'Группа' });
    const parent = within(dialog).getByRole('combobox', { name: 'Родительская статья' });

    await user.click(group);
    await user.click(await screen.findByRole('option', { name: 'Снабжение' }));
    await user.click(parent);
    await user.click(await screen.findByRole('option', { name: '100 Материалы' }));
    expect(parent).toHaveTextContent('100 Материалы');

    await user.click(group);
    await user.click(await screen.findByRole('option', { name: 'Проектное управление' }));

    expect(parent).toHaveTextContent('— нет —');
  });
});
