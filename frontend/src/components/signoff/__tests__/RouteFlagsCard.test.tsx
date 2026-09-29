/**
 * «Правила маршрута» (мастер-план БЗО, D-21): форма шлёт флаги целиком,
 * а неверную длину комментария не отправляет на сервер.
 */
import { fireEvent, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { RouteFlagsCard } from '@/components/signoff/RouteFlagsCard';
import { renderWithProviders } from '@/test/renderWithProviders';
import type { ApprovalRoute } from '@/types/signoff';

const signoff = vi.hoisted(() => ({ updateRoute: vi.fn() }));
vi.mock('@/api/signoff', () => ({ signoffApi: signoff }));
vi.mock('@/api/hr', () => ({ fetchPositions: vi.fn().mockResolvedValue([]) }));
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

describe('RouteFlagsCard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    signoff.updateRoute.mockResolvedValue({ data: route() });
  });

  it('сохраняет флаги целиком', async () => {
    renderWithProviders(<RouteFlagsCard route={route()} />);

    fireEvent.click(screen.getByLabelText('Запрет самосогласования'));
    fireEvent.change(screen.getByLabelText(/Комментарий при отказе/), { target: { value: '10' } });
    fireEvent.click(screen.getByRole('button', { name: /Сохранить правила/ }));

    await waitFor(() => expect(signoff.updateRoute).toHaveBeenCalledWith(5, {
      forbid_self_approval: true,
      reject_comment_min: 10,
      lazy_resolution: false,
      skip_unmatched_groups: false,
      no_executor_notify_position_ids: [],
      escalation_position_id: null,
      self_skip_notify_position_ids: [],
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
