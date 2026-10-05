/**
 * Окно подтверждения контрагента для договора и счёта (D-20; задача 9
 * плана этапа 2 A):
 * - проверенный и действующий — окна нет;
 * - непроверенный — продолжить можно только после явной отметки;
 * - заблокированный или архивный — продолжить нельзя, только закрыть;
 * - хук `useCounterpartyConfirmation` отвечает `true`/`false`.
 */
import { useState } from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { ConfirmCounterpartyDialog } from './ConfirmCounterpartyDialog';
import { counterpartyGate, type CounterpartyForConfirm } from './counterpartyGate';
import { useCounterpartyConfirmation } from './useCounterpartyConfirmation';

const base: CounterpartyForConfirm = {
  id: 'cp-1',
  name: 'Товарищество «Альфа»',
  short_name: 'ТОО «Альфа»',
  status: 'active',
  is_verified: false,
  successful_documents: 1,
  verified_threshold: 3,
};

function renderDialog(counterparty: CounterpartyForConfirm) {
  const onConfirm = vi.fn();
  const onCancel = vi.fn();
  render(
    <ConfirmCounterpartyDialog counterparty={counterparty} open onConfirm={onConfirm} onCancel={onCancel} />,
  );
  return { onConfirm, onCancel };
}

describe('counterpartyGate', () => {
  it('ok / confirm / unusable', () => {
    expect(counterpartyGate({ ...base, is_verified: true })).toBe('ok');
    expect(counterpartyGate(base)).toBe('confirm');
    expect(counterpartyGate({ ...base, status: 'blocked', is_verified: true })).toBe('unusable');
    expect(counterpartyGate({ ...base, status: 'archived', is_verified: true })).toBe('unusable');
  });
});

describe('ConfirmCounterpartyDialog', () => {
  it('проверенный — окна нет даже при open', () => {
    renderDialog({ ...base, is_verified: true });
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
  });

  it('непроверенный — «Подтвердить» неактивна до отметки, потом зовёт onConfirm', async () => {
    const user = userEvent.setup();
    const { onConfirm, onCancel } = renderDialog(base);

    const dialog = await screen.findByRole('alertdialog');
    expect(dialog).toHaveTextContent('Контрагент не проверен');
    expect(dialog).toHaveTextContent('ТОО «Альфа»');
    expect(dialog).toHaveTextContent('1 из 3');

    const submit = screen.getByRole('button', { name: 'Подтвердить и продолжить' });
    expect(submit).toBeDisabled();
    await user.click(screen.getByRole('checkbox'));
    expect(submit).toBeEnabled();
    await user.click(submit);

    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onCancel).not.toHaveBeenCalled();
  });

  it('непроверенный — «Отмена» зовёт onCancel', async () => {
    const user = userEvent.setup();
    const { onConfirm, onCancel } = renderDialog(base);
    await user.click(await screen.findByRole('button', { name: 'Отмена' }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it('заблокированный — причина и дата, продолжить нельзя', async () => {
    const user = userEvent.setup();
    const { onConfirm, onCancel } = renderDialog({
      ...base,
      status: 'blocked',
      is_verified: true,
      block_reason: 'Срыв сроков поставки',
      blocked_at: '2026-09-27T20:30:00Z',
    });

    const dialog = await screen.findByRole('alertdialog');
    expect(dialog).toHaveTextContent('Контрагент заблокирован');
    // Дата — по Алматы: 20:30 UTC 27.09 — это уже 28.09.
    expect(dialog).toHaveTextContent(
      'Контрагент ТОО «Альфа» заблокирован 28.09.2026: „Срыв сроков поставки“.',
    );
    expect(screen.queryByRole('button', { name: 'Подтвердить и продолжить' })).not.toBeInTheDocument();
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Закрыть' }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it('архивный — свой текст, продолжить нельзя', async () => {
    renderDialog({ ...base, status: 'archived' });
    const dialog = await screen.findByRole('alertdialog');
    expect(dialog).toHaveTextContent('переведён в архив');
    expect(screen.queryByRole('button', { name: 'Подтвердить и продолжить' })).not.toBeInTheDocument();
  });
});

describe('useCounterpartyConfirmation', () => {
  function Harness({ counterparty }: { counterparty: CounterpartyForConfirm }) {
    const { confirm, dialog } = useCounterpartyConfirmation();
    const [answer, setAnswer] = useState<string>('—');
    return (
      <>
        <button type="button" onClick={() => { void confirm(counterparty).then((ok) => setAnswer(String(ok))); }}>
          Отправить
        </button>
        <output>{answer}</output>
        {dialog}
      </>
    );
  }

  it('проверенный — true без окна', async () => {
    const user = userEvent.setup();
    render(<Harness counterparty={{ ...base, is_verified: true }} />);
    await user.click(screen.getByRole('button', { name: 'Отправить' }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('true'));
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
  });

  it('непроверенный — true после подтверждения', async () => {
    const user = userEvent.setup();
    render(<Harness counterparty={base} />);
    await user.click(screen.getByRole('button', { name: 'Отправить' }));
    await user.click(await screen.findByRole('checkbox'));
    await user.click(screen.getByRole('button', { name: 'Подтвердить и продолжить' }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('true'));
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
  });

  it('заблокированный — false по закрытию', async () => {
    const user = userEvent.setup();
    render(<Harness counterparty={{ ...base, status: 'blocked', block_reason: 'Причина блокировки' }} />);
    await user.click(screen.getByRole('button', { name: 'Отправить' }));
    await user.click(await screen.findByRole('button', { name: 'Закрыть' }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('false'));
  });
});
