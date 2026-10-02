/**
 * Форма контрагента (ТЗ §18; задача 9 плана этапа 2 A):
 * - неверный контрольный разряд БИН ловится до запроса тем же правилом, что
 *   на сервере;
 * - дубль E-CTR-02 — текст сервера и ссылка на существующую карточку из
 *   `fields[0].existing_id`;
 * - создание идёт с `Idempotency-Key`.
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

// Под общей нагрузкой прогона форма не укладывается в 5 с (сверка B §20).
vi.setConfig({ testTimeout: 15000 });

import { createTestQueryClient } from '@/test/renderWithProviders';

import { CounterpartyForm } from './CounterpartyForm';

const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
const patch = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get, post, patch } }));

const toastError = vi.hoisted(() => vi.fn());
vi.mock('sonner', () => ({ toast: { error: toastError, success: vi.fn(), info: vi.fn() } }));

const EXISTING = '3fa85f64-5717-4562-b3fc-2c963f66afa6';
const VALID_BIN = '100000000001';

function renderForm(onSaved = vi.fn()) {
  render(
    <QueryClientProvider client={createTestQueryClient()}>
      <MemoryRouter>
        <CounterpartyForm onSaved={onSaved} onCancel={vi.fn()} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return onSaved;
}

describe('CounterpartyForm — создание', () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    patch.mockReset();
    toastError.mockReset();
    get.mockResolvedValue({ data: [{ code: 'KZ', name: 'Казахстан' }] });
  });

  it('неверный контрольный разряд БИН — отказ у поля, запроса нет', async () => {
    const user = userEvent.setup();
    renderForm();
    await user.type(screen.getByLabelText('Наименование'), 'ТОО «Альфа»');
    await user.type(screen.getByLabelText('БИН/ИИН'), '100000000002');
    await user.click(screen.getByRole('button', { name: 'Создать контрагента' }));

    expect(await screen.findByText(/не прошёл проверку контрольного разряда/)).toBeInTheDocument();
    expect(post).not.toHaveBeenCalled();
  });

  it('дубль E-CTR-02 — текст сервера и ссылка на существующего', async () => {
    const user = userEvent.setup();
    const detail = `Контрагент с номером ${VALID_BIN} (KZ) уже есть в справочнике: ТОО «Альфа». Откройте существующую карточку.`;
    post.mockRejectedValue({
      response: {
        status: 422,
        data: {
          detail,
          code: 'E-CTR-02',
          fields: [{ field: 'reg_number', message: 'Номер уже занят', existing_id: EXISTING }],
        },
      },
    });
    const onSaved = renderForm();

    await user.type(screen.getByLabelText('Наименование'), 'ТОО «Альфа-2»');
    await user.type(screen.getByLabelText('БИН/ИИН'), VALID_BIN);
    await user.click(screen.getByRole('button', { name: 'Создать контрагента' }));

    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    const [url, body, config] = post.mock.calls[0];
    expect(url).toBe('bpp/v1/counterparties');
    expect(body).toMatchObject({ name: 'ТОО «Альфа-2»', reg_number: VALID_BIN, kind: 'legal', country_code: 'KZ' });
    expect(config.headers['Idempotency-Key']).toEqual(expect.any(String));

    expect(await screen.findByText(detail)).toBeInTheDocument();
    expect(screen.getByText('Номер уже занят')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Открыть карточку существующего контрагента' }))
      .toHaveAttribute('href', `/bpp/counterparties/${EXISTING}`);
    expect(onSaved).not.toHaveBeenCalled();
  });

  it('успех — карточка уходит вызывающему', async () => {
    const user = userEvent.setup();
    const card = { id: EXISTING, name: 'ТОО «Альфа»', allowed_actions: [], bank_accounts: [] };
    post.mockResolvedValue({ data: card });
    const onSaved = renderForm();

    await user.type(screen.getByLabelText('Наименование'), 'ТОО «Альфа»');
    await user.type(screen.getByLabelText('БИН/ИИН'), `${VALID_BIN.slice(0, 6)} ${VALID_BIN.slice(6)}`);
    await user.click(screen.getByRole('button', { name: 'Создать контрагента' }));

    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(card));
  });
});
