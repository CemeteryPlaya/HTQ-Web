/**
 * Выбор варианта в диалоге «Согласовать» (альтернативы снабженца, ТЗ §12.4).
 *
 * Когда вариантов два и больше, согласие без выбора не уходит на сервер —
 * тот всё равно ответил бы 422 «выберите вариант», но человек узнал бы об
 * этом после нажатия. Отказ и доработка варианта не спрашивают: они решают
 * судьбу документа целиком.
 */
import { fireEvent, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { DecisionDialog, type DecisionTarget } from '@/components/signoff/DecisionDialog';
import { renderWithProviders } from '@/test/renderWithProviders';

const signoff = vi.hoisted(() => ({ decide: vi.fn(), attachDocument: vi.fn() }));
vi.mock('@/api/signoff', () => ({ signoffApi: signoff }));
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock('sonner', () => ({ toast }));

const OPTIONS = [
  { key: 'original', label: 'Исходный договор № Д-17 — ТОО «Альфа», 400 000,00 KZT' },
  { key: 'offer:3', label: 'Альтернатива АП-2026-000003 — ТОО «Бета», 350 000,00 KZT' },
];

function target(over: Partial<DecisionTarget> = {}): DecisionTarget {
  return { taskId: 41, kind: 'approve', subjectLabel: 'Договор № Д-17', options: OPTIONS, ...over };
}

function renderDialog(t: DecisionTarget) {
  const onDecided = vi.fn();
  renderWithProviders(<DecisionDialog target={t} onOpenChange={vi.fn()} onDecided={onDecided} />);
  return { onDecided };
}

const confirm = () => screen.getAllByRole('button', { name: /Согласовать/ }).at(-1)!;

describe('DecisionDialog — выбор варианта', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    signoff.decide.mockResolvedValue({ data: { id: 9 } });
  });

  it('не отправляет согласие без выбора и отправляет выбранный вариант', async () => {
    const { onDecided } = renderDialog(target());

    expect(screen.getByText('Какой вариант вы согласуете')).toBeInTheDocument();
    fireEvent.click(confirm());
    expect(await screen.findByText(/Выберите, какой вариант вы согласуете/)).toBeInTheDocument();
    expect(signoff.decide).not.toHaveBeenCalled();

    fireEvent.click(screen.getByLabelText(/Альтернатива АП-2026-000003/));
    fireEvent.click(confirm());

    await waitFor(() => expect(signoff.decide).toHaveBeenCalledWith(41, {
      decision: 'approve', comment: '', option_key: 'offer:3',
    }));
    await waitFor(() => expect(onDecided).toHaveBeenCalled());
  });

  it('с одним вариантом выбора нет — и option_key не отправляется', async () => {
    renderDialog(target({ options: [OPTIONS[0]] }));

    expect(screen.queryByText('Какой вариант вы согласуете')).not.toBeInTheDocument();
    fireEvent.click(confirm());

    await waitFor(() => expect(signoff.decide).toHaveBeenCalledWith(41, {
      decision: 'approve', comment: '',
    }));
  });

  it('отказ варианта не спрашивает', () => {
    renderDialog(target({ kind: 'reject' }));

    expect(screen.queryByText('Какой вариант вы согласуете')).not.toBeInTheDocument();
  });
});
