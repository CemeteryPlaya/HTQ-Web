/**
 * Вкладка «Выбор» (TND-022; S5-05…S5-07): поставщик в строке, доставка
 * «в цене» у победителя — сама, тело `PUT award` с версией, 422 `E-TND-12`
 * — ошибки у строк и общего комментария, «На утверждение» с версией,
 * 422 `E-TND-11` — блок дефицита по статьям, только чтение без `award`.
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { createTestQueryClient } from '@/test/renderWithProviders';

import type { AwardView, Comparison } from './comparison';
import { AwardTab } from './AwardTab';
import { TENDER_ID, awardView, comparisonData, tenderCard } from './testData';

const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
const put = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get, post, put, patch: vi.fn(), delete: vi.fn() } }));
const toast = vi.hoisted(() => ({ error: vi.fn(), success: vi.fn(), info: vi.fn() }));
vi.mock('sonner', () => ({ toast }));

const onChanged = vi.fn();

function serve(view: AwardView, data: Comparison = comparisonData()) {
  get.mockImplementation((url: string) => {
    if (url.endsWith(`tenders/${TENDER_ID}/comparison`)) return Promise.resolve({ data });
    if (url.endsWith(`tenders/${TENDER_ID}/award`)) return Promise.resolve({ data: view });
    return Promise.reject(new Error(`unexpected ${url}`));
  });
}

function renderTab() {
  return render(
    <QueryClientProvider client={createTestQueryClient()}>
      <AwardTab tenderId={TENDER_ID} onChanged={onChanged} onConflict={vi.fn()} />
    </QueryClientProvider>,
  );
}

const failure = (status: number, data: object) => Object.assign(new Error(String(status)), {
  response: { status, data },
});

async function choose(user: ReturnType<typeof userEvent.setup>, label: string, option: RegExp) {
  await user.click(await screen.findByRole('combobox', { name: label }));
  await user.click(await screen.findByRole('option', { name: option }));
}

beforeEach(() => {
  get.mockReset();
  post.mockReset();
  put.mockReset();
  onChanged.mockReset();
  toast.error.mockReset();
});

describe('AwardTab', () => {
  it('выбор в строке и доставка у победителя уходят в PUT с версией', async () => {
    serve(awardView());
    put.mockResolvedValue({ data: awardView({ version: 6 }) });
    const user = userEvent.setup();
    renderTab();
    await choose(user, 'Поставщик позиции 1', /ТОО «Альфа»/);
    await choose(user, 'Поставщик позиции 2', /ТОО «Альфа»/);
    await choose(user, 'Поставщик: Доставка', /ТОО «Альфа»/);
    await user.click(screen.getByRole('button', { name: 'Сохранить выбор' }));
    await waitFor(() => expect(put).toHaveBeenCalled());
    expect(put.mock.calls[0][0]).toContain(`tenders/${TENDER_ID}/award`);
    expect(put.mock.calls[0][1]).toEqual({
      version: 5, comment: '',
      lines: [{ line_id: 'ln-a1' }, { line_id: 'ln-a2' }],
      extras: [{ extra_id: 'ex-a' }],
    });
    expect(onChanged).toHaveBeenCalled();
  });

  it('доставка «в цене» у победителя — подписью, без выбора', async () => {
    serve(awardView());
    const user = userEvent.setup();
    renderTab();
    await choose(user, 'Поставщик позиции 1', /ТОО «Бета»/);
    const extra = screen.getByTestId('award-extra-delivery');
    expect(within(extra).getByText('в цене у ТОО «Бета»')).toBeInTheDocument();
    expect(within(extra).queryByRole('combobox')).toBeNull();
  });

  it('доставку не у победителя не выбрать — подсказка', async () => {
    serve(awardView());
    renderTab();
    const extra = await screen.findByTestId('award-extra-delivery');
    expect(within(extra).getByText(/выигравшего хотя бы одну позицию/)).toBeInTheDocument();
  });

  it('422 E-TND-12 — ошибка у строки и у общего комментария', async () => {
    serve(awardView());
    put.mockRejectedValue(failure(422, {
      detail: 'Выбран не самый дешёвый вариант.', code: 'E-TND-12',
      fields: [
        { field: 'comment', message: 'объясните выбор — не короче 10 символов' },
        { field: 'lines[0].comment', message: 'не самый дешёвый вариант — объясните выбор строки' },
      ],
      details: { rows: [{ line_id: 'ln-b1', item_id: 'it-1' }] },
    }));
    const user = userEvent.setup();
    renderTab();
    await choose(user, 'Поставщик позиции 1', /ТОО «Бета»/);
    const comment = screen.getByRole('textbox', { name: 'Комментарий к позиции 1' });
    expect(comment).toHaveAttribute('placeholder', expect.stringContaining('Почему не самый дешёвый'));
    await user.click(screen.getByRole('button', { name: 'Сохранить выбор' }));
    const row = screen.getByTestId('award-item-1');
    expect(await within(row).findByText('не самый дешёвый вариант — объясните выбор строки')).toBeInTheDocument();
    expect(screen.getByText('объясните выбор — не короче 10 символов')).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Комментарий к позиции 1' })).toHaveAttribute('aria-invalid', 'true');
  });

  it('«На утверждение» — с версией; E-TND-11 — блок дефицита по статьям', async () => {
    const saved = awardView({
      allowed_actions: ['cancel', 'award', 'award_submit'],
      lines: [{
        award_id: 'aw-1', invitation_id: 'inv-a', supplier: 'ТОО «Альфа»', part_id: 'p1', qty: '10',
        amount: '1008.00', currency_code: 'KZT', amount_kzt: '1008.00', plan_amount_kzt: '1000',
        is_cheapest: true, comment: '', line_id: 'ln-a1', item_id: 'it-1', line_no: 1,
        name: 'Арматура А500', price: '90', is_analog: false,
      }],
    });
    serve(saved);
    post.mockRejectedValueOnce(failure(422, {
      detail: 'Выбор дороже плана сверх свободного остатка бюджета статьи.', code: 'E-TND-11',
      details: { deficits: [{ article_id: 'a1', article_code: '1.2.3', over: '500.00', available: '120.00' }] },
    }));
    const user = userEvent.setup();
    renderTab();
    await user.click(await screen.findByRole('button', { name: 'На утверждение' }));
    await waitFor(() => expect(post).toHaveBeenCalled());
    expect(post.mock.calls[0][0]).toContain(`tenders/${TENDER_ID}/award/submit`);
    expect(post.mock.calls[0][1]).toEqual({ version: 5 });
    expect(post.mock.calls[0][2].headers['Idempotency-Key']).toBeTruthy();
    const deficits = await screen.findByTestId('award-deficits');
    expect(within(deficits).getByText('1.2.3: сверх плана 500,00 KZT, свободно 120,00 KZT')).toBeInTheDocument();

    post.mockResolvedValueOnce({ data: tenderCard({ status: 'on_approval' }) });
    await user.click(screen.getByRole('button', { name: 'На утверждение' }));
    await waitFor(() => expect(onChanged).toHaveBeenCalledWith(expect.objectContaining({ status: 'on_approval' })));
  });

  it('несохранённый выбор не отправляется', async () => {
    serve(awardView({ allowed_actions: ['award', 'award_submit'] }));
    const user = userEvent.setup();
    renderTab();
    await choose(user, 'Поставщик позиции 1', /ТОО «Альфа»/);
    expect(screen.getByRole('button', { name: 'На утверждение' })).toBeDisabled();
    expect(screen.getByText('Сохраните выбор перед отправкой')).toBeInTheDocument();
  });

  it('без действия award — только чтение', async () => {
    serve(awardView({
      status: 'on_approval', allowed_actions: [], comment: 'Альфа надёжнее',
      lines: [{
        award_id: 'aw-1', invitation_id: 'inv-a', supplier: 'ТОО «Альфа»', part_id: 'p1', qty: '10',
        amount: '1008.00', currency_code: 'KZT', amount_kzt: '1008.00', plan_amount_kzt: '1000',
        is_cheapest: true, comment: '', line_id: 'ln-a1', item_id: 'it-1', line_no: 1,
        name: 'Арматура А500', price: '90', is_analog: false,
      }],
    }));
    renderTab();
    const row = await screen.findByTestId('award-item-1');
    expect(within(row).getByText('ТОО «Альфа»')).toBeInTheDocument();
    expect(screen.queryByRole('combobox')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Сохранить выбор' })).toBeNull();
    expect(screen.getByText('Альфа надёжнее')).toBeInTheDocument();
  });

  it('ошибка количества — у поля количества, а не у комментария', async () => {
    serve(awardView());
    put.mockRejectedValue(failure(422, {
      detail: 'Неверные данные', code: 'E-VAL-01',
      fields: [{ field: 'lines[0].qty', message: 'количество — больше нуля и не больше предложенного (10)' }],
    }));
    const user = userEvent.setup();
    renderTab();
    await choose(user, 'Поставщик позиции 1', /ТОО «Альфа»/);
    await user.type(screen.getByRole('textbox', { name: 'Количество позиции 1' }), '11');
    await user.click(screen.getByRole('button', { name: 'Сохранить выбор' }));
    const qty = screen.getByRole('textbox', { name: 'Количество позиции 1' });
    await waitFor(() => expect(qty).toHaveAttribute('aria-invalid', 'true'));
    expect(screen.getByRole('textbox', { name: 'Комментарий к позиции 1' })).not.toHaveAttribute('aria-invalid');
    expect(screen.getByText(/не больше предложенного \(10\)/)).toBeInTheDocument();
  });
});
