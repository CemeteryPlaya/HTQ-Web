/**
 * «Правила маршрута» (мастер-план БЗО, D-21): форма шлёт флаги целиком,
 * а неверную длину комментария не отправляет на сервер. Должности
 * вышестоящей компании (B8.1) уходят своими полями, а переключатель решения
 * из холдинга есть только у типов, которые это допускают.
 */
import { fireEvent, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { RouteFlagsCard } from '@/components/signoff/RouteFlagsCard';
import { renderWithProviders } from '@/test/renderWithProviders';
import type { ApprovalRoute } from '@/types/signoff';

const signoff = vi.hoisted(() => ({
  updateRoute: vi.fn(),
  positionCompanies: vi.fn(),
  positions: vi.fn(),
}));
vi.mock('@/api/signoff', () => ({ signoffApi: signoff }));
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock('sonner', () => ({ toast }));

function route(over: Partial<ApprovalRoute> = {}): ApprovalRoute {
  return {
    id: 5, subject_type: 'bpp.invoice', scope: '', scope_label: null, name: 'Счёт',
    is_active: true, stages: [], created_at: '', updated_at: '',
    forbid_self_approval: false, reject_comment_min: 0, lazy_resolution: false,
    no_executor_notify_position_ids: [], escalation_position_id: null,
    self_skip_notify_position_ids: [], no_executor_notify_positions: [],
    escalation_position: null, self_skip_notify_positions: [],
    ...over,
  };
}

const BASE_PAYLOAD = {
  forbid_self_approval: false,
  reject_comment_min: 0,
  lazy_resolution: false,
  skip_unmatched_groups: false,
  no_executor_notify_position_ids: [],
  no_executor_notify_foreign: [],
  escalation_position_id: null,
  escalation_position_company: '',
  self_skip_notify_position_ids: [],
  self_skip_notify_foreign: [],
};

describe('RouteFlagsCard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    signoff.updateRoute.mockResolvedValue({ data: route() });
    signoff.positionCompanies.mockResolvedValue({ data: [{ slug: 'beta', name: 'Бета', own: true }] });
    signoff.positions.mockResolvedValue({ data: [] });
  });

  it('сохраняет флаги целиком', async () => {
    renderWithProviders(<RouteFlagsCard route={route()} />);

    fireEvent.click(screen.getByLabelText('Запрет самосогласования'));
    fireEvent.change(screen.getByLabelText(/Комментарий при отказе/), { target: { value: '10' } });
    fireEvent.click(screen.getByRole('button', { name: /Сохранить правила/ }));

    await waitFor(() => expect(signoff.updateRoute).toHaveBeenCalledWith(5, {
      ...BASE_PAYLOAD, forbid_self_approval: true, reject_comment_min: 10,
    }));
  });

  it('должности холдинга уходят своими полями, свои — номерами', async () => {
    renderWithProviders(<RouteFlagsCard route={route({
      forbid_self_approval: true, lazy_resolution: true,
      escalation_position_id: 12, escalation_position_company: 'alpha',
      no_executor_notify_position_ids: [3],
      no_executor_notify_foreign: [{ company: 'alpha', position_id: 12 }],
      self_skip_notify_foreign: [{ company: 'alpha', position_id: 7 }],
      escalation_position: { id: 12, title: 'ГД · Альфа', company: 'alpha' },
    })} />);

    // ГД холдинга — и эскалация, и получатель «Нет исполнителя».
    expect(screen.getAllByText('ГД · Альфа')).toHaveLength(2);
    fireEvent.click(screen.getByRole('button', { name: /Сохранить правила/ }));

    await waitFor(() => expect(signoff.updateRoute).toHaveBeenCalledWith(5, {
      ...BASE_PAYLOAD,
      forbid_self_approval: true,
      lazy_resolution: true,
      no_executor_notify_position_ids: [3],
      no_executor_notify_foreign: [{ company: 'alpha', position_id: 12 }],
      escalation_position_id: 12,
      escalation_position_company: 'alpha',
      self_skip_notify_foreign: [{ company: 'alpha', position_id: 7 }],
    }));
  });

  it('переключатель решения из холдинга — только у типов, которые это допускают', async () => {
    const { unmount } = renderWithProviders(<RouteFlagsCard route={route()} />);
    expect(screen.queryByLabelText('Решение из вышестоящей компании')).not.toBeInTheDocument();
    unmount();

    renderWithProviders(<RouteFlagsCard route={route({ cross_company_decisions: true })} />);
    fireEvent.click(screen.getByLabelText('Решение из вышестоящей компании'));
    fireEvent.click(screen.getByRole('button', { name: /Сохранить правила/ }));

    await waitFor(() => expect(signoff.updateRoute).toHaveBeenCalledWith(5, {
      ...BASE_PAYLOAD, allow_direct_decisions: true,
    }));
  });

  it('показывает должности эскалации только при запрете самосогласования', () => {
    renderWithProviders(<RouteFlagsCard route={route()} />);
    expect(screen.queryByText('Должность эскалации')).not.toBeInTheDocument();

    fireEvent.click(screen.getByLabelText('Запрет самосогласования'));

    expect(screen.getByText('Должность эскалации')).toBeInTheDocument();
  });

  it('не отправляет неверную длину комментария', () => {
    renderWithProviders(<RouteFlagsCard route={route()} />);

    fireEvent.change(screen.getByLabelText(/Комментарий при отказе/), { target: { value: '501' } });
    fireEvent.click(screen.getByRole('button', { name: /Сохранить правила/ }));

    expect(screen.getByText(/целое число от 0 до 500/)).toBeInTheDocument();
    expect(signoff.updateRoute).not.toHaveBeenCalled();
  });
});
