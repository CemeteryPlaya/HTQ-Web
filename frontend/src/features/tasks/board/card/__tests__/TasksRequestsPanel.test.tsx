/**
 * Панель «Запросы» (решение K-32): решающий одобряет «владение» с заменой
 * прямо из списка, запросивший видит статус и отзывает ждущий запрос,
 * пустые вкладки объясняют пустоту.
 */
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';

vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() } }));
const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() }));
vi.mock('@/api/client', () => ({ default: api }));

import { TasksRequestsPanel } from '../TasksRequestsPanel';

const ROW = {
  id: 21, task: { id: 5, key: 'T-5', summary: 'Подготовить смету' },
  requester: { id: 8, name: 'Анна Ким' }, kind: 'own', comment: 'Возьму проект', status: 'pending',
  approve_mode: null, replaced: null, decided_by: null, decided_at: null, decision_comment: '',
  created_at: '2026-10-21T10:00:00Z',
};

beforeEach(() => {
  vi.clearAllMocks();
  api.post.mockResolvedValue({ data: { ...ROW, status: 'approved' } });
  api.delete.mockResolvedValue({ data: null });
});

function serve(inbox: object) {
  api.get.mockImplementation((url: string) => (url.endsWith('access-requests/inbox')
    ? Promise.resolve({ data: inbox }) : Promise.resolve({ data: { items: [] } })));
}

describe('TasksRequestsPanel', () => {
  it('решающий передаёт владение прямо из списка, задача открывается по клику', async () => {
    serve({ to_decide: [ROW], mine: [], to_decide_count: 1 });
    const onOpenCard = vi.fn();
    renderWithProviders(<TasksRequestsPanel open onOpenChange={vi.fn()} onOpenCard={onOpenCard}
      departmentId={null} />);
    expect(await screen.findByText('Анна Ким')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Передать владение' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('tasks/v1/access-requests/21/approve',
      { mode: 'replace', comment: undefined }));
    await userEvent.click(screen.getByRole('button', { name: /Подготовить смету/ }));
    expect(onOpenCard).toHaveBeenCalledWith(5);
  });

  it('свой ждущий запрос отзывается, пустая вкладка решений объясняет пустоту', async () => {
    serve({ to_decide: [], mine: [{ ...ROW, requester: { id: 7, name: 'Я' } }], to_decide_count: 0 });
    renderWithProviders(<TasksRequestsPanel open onOpenChange={vi.fn()} onOpenCard={vi.fn()}
      departmentId={null} />);
    expect(await screen.findByText('Нет запросов, которые ждут вашего решения.')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('tab', { name: 'Мои' }));
    const mine = await screen.findByRole('tabpanel');
    expect(within(mine).getByText('ждёт решения')).toBeInTheDocument();
    await userEvent.click(within(mine).getByRole('button', { name: 'Отозвать' }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith('tasks/v1/access-requests/21'));
  });

  it('историю отдела видно, только когда передан отдел', async () => {
    serve({ to_decide: [], mine: [], to_decide_count: 0 });
    renderWithProviders(<TasksRequestsPanel open onOpenChange={vi.fn()} onOpenCard={vi.fn()}
      departmentId={null} />);
    await screen.findByRole('tab', { name: /Ждут решения/ });
    expect(screen.queryByRole('tab', { name: 'История отдела' })).not.toBeInTheDocument();
  });
});
