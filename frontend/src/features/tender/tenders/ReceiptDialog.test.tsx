/**
 * Диалог приёмки (TND-041): количество не больше остатка — ошибка у строки
 * и запрос не уходит; товар и работы — раздельно; тело с ключом
 * идемпотентности; ошибка сервера у строки по индексу тела.
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { ReceiptDialog } from './ReceiptDialog';
import { deliverySupplier } from './testData';

function renderDialog(onSave = vi.fn(() => Promise.resolve()), onError = vi.fn()) {
  const onOpenChange = vi.fn();
  render(<ReceiptDialog supplier={deliverySupplier()} onOpenChange={onOpenChange} onSave={onSave} onError={onError} />);
  return { onSave, onError, onOpenChange };
}

describe('ReceiptDialog', () => {
  it('больше остатка — ошибка у строки, «Сохранить» закрыта', async () => {
    const user = userEvent.setup();
    const { onSave } = renderDialog();
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByText('выбрано 10, принято 4, осталось 6')).toBeInTheDocument();
    await user.type(within(dialog).getByLabelText('Принято: Арматура А500'), '7');
    expect(within(dialog).getByText('Не больше 6 — остальное уже принято')).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Сохранить приёмку' })).toBeDisabled();
    expect(onSave).not.toHaveBeenCalled();
  });

  it('товар: строки только позиций (доставка — с товаром), тело с ключом', async () => {
    const user = userEvent.setup();
    const { onSave, onOpenChange } = renderDialog();
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).queryByLabelText('Принято: Доставка')).toBeNull();
    expect(within(dialog).queryByLabelText('Принято: СМР')).toBeNull();
    await user.type(within(dialog).getByLabelText('Принято: Арматура А500'), '6');
    await user.click(within(dialog).getByRole('button', { name: 'Сохранить приёмку' }));
    await waitFor(() => expect(onSave).toHaveBeenCalled());
    const [key, body] = onSave.mock.calls[0] as unknown as [string, Record<string, unknown>];
    expect(key).toBeTruthy();
    expect(body).toMatchObject({
      invitation_id: 'inv-a', kind: 'goods', lines: [{ award_id: 'aw-1', qty: '6' }],
    });
    expect(body.received_at).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
  });

  it('«Работы приняты» — строки СМР', async () => {
    const user = userEvent.setup();
    const { onSave } = renderDialog();
    const dialog = screen.getByRole('dialog');
    await user.click(within(dialog).getByLabelText('Работы приняты'));
    expect(within(dialog).queryByLabelText('Принято: Арматура А500')).toBeNull();
    await user.type(within(dialog).getByLabelText('Принято: СМР'), '1');
    await user.click(within(dialog).getByRole('button', { name: 'Сохранить приёмку' }));
    await waitFor(() => expect(onSave).toHaveBeenCalled());
    expect((onSave.mock.calls[0] as unknown as [string, { kind: string; lines: unknown[] }])[1])
      .toMatchObject({ kind: 'works', lines: [{ award_id: 'aw-3', qty: '1' }] });
  });

  it('422 E-TND-13 — текст сервера у строки', async () => {
    const user = userEvent.setup();
    const failure = Object.assign(new Error('422'), { response: { status: 422, data: {
      detail: 'Принять можно не больше 2', code: 'E-TND-13', fields: [{ field: 'lines[0].qty', message: 'Не больше 2' }],
    } } });
    const { onError } = renderDialog(vi.fn(() => Promise.reject(failure)));
    const dialog = screen.getByRole('dialog');
    await user.type(within(dialog).getByLabelText('Принято: Арматура А500'), '5');
    await user.click(within(dialog).getByRole('button', { name: 'Сохранить приёмку' }));
    expect(await within(dialog).findByText('Не больше 2')).toBeInTheDocument();
    expect(onError).toHaveBeenCalledWith(failure);
  });
});
