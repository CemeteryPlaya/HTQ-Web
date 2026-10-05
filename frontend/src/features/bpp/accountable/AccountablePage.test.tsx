/**
 * Реестр подотчёта (B4.1): «Создать» — проект, статья бюджета роли с
 * остатком, сумма и цель; сумма сверх остатка статьи закрывает кнопку до
 * запроса, иначе заявка создаётся и открывается её форма.
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { createTestQueryClient } from '@/test/renderWithProviders';

import { AccountablePage } from './AccountablePage';

const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get, post } }));
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() } }));
vi.mock('@/hooks/usePermissions', () => ({
  usePermissions: () => ({ can: () => true, atLeast: () => true }),
}));

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  get.mockImplementation((url: string) => {
    if (url.includes('bpp/v1/me')) return Promise.resolve({ data: { initiator_roles: ['sn'], article_groups: [] } });
    if (url.includes('budgets/lines')) {
      return Promise.resolve({ data: [{ article_id: 'art', article_code: 'T-METAL',
        article_name: 'Металлопрокат', limit: '1000.00', committed: '500.00', available: '500.00' }] });
    }
    if (url.includes('projects')) {
      return Promise.resolve({ data: [{ id: 'p1', code: 'П-015', name: 'Объект', status: 'active' }] });
    }
    return Promise.resolve({ data: { items: [], total: 0, page: 1, page_size: 50, totals: { amount: '0.00' } } });
  });
});

describe('AccountablePage', () => {
  it('«Создать» — статья с остатком, сумма сверх остатка закрыта', { timeout: 20000 }, async () => {
    post.mockResolvedValue({ data: { id: 'new-id' } });
    render(
      <QueryClientProvider client={createTestQueryClient()}>
        <MemoryRouter initialEntries={['/bpp/accountable']}>
          <Routes>
            <Route path="/bpp/accountable" element={<AccountablePage />} />
            <Route path="/bpp/accountable/:id" element={<div>Форма подотчёта</div>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await userEvent.click(await screen.findByRole('button', { name: 'Создать' }, { timeout: 4000 }));
    const dialog = await screen.findByRole('dialog');
    await userEvent.click(within(dialog).getByLabelText('Проект'));
    await userEvent.click(await screen.findByRole('option', { name: 'П-015 — Объект' }));
    await userEvent.click(within(dialog).getByLabelText('Статья бюджета'));
    await userEvent.click(await screen.findByRole('option', { name: 'T-METAL — Металлопрокат' }));
    expect(within(dialog).getByText(/Доступный остаток статьи/)).toHaveTextContent('500,00');

    await userEvent.type(within(dialog).getByLabelText('Сумма'), '600');
    await userEvent.type(within(dialog).getByLabelText('Цель'), 'Командировка на объект');
    expect(within(dialog).getByRole('alert')).toHaveTextContent('Сумма больше доступного остатка статьи');
    const create = within(dialog).getByRole('button', { name: 'Создать' });
    expect(create).toBeDisabled();

    const amount = within(dialog).getByLabelText('Сумма');
    await userEvent.clear(amount);
    await userEvent.type(amount, '450');
    await userEvent.click(create);

    expect(await screen.findByText('Форма подотчёта')).toBeInTheDocument();
    await waitFor(() => expect(post).toHaveBeenCalled());
    expect(post.mock.calls[0][1]).toEqual({
      project_id: 'p1', article_id: 'art', amount: '450.00', goal: 'Командировка на объект',
    });
  });
});
