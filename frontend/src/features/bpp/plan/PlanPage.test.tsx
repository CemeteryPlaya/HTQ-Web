/**
 * План закупок L-04 и мастер F-03 (ТЗ §08):
 * - позиции разных статей — «Оформить договор» недоступна, подсказка §8.3 п.1;
 * - позиция с остатком 0 — флажок недоступен (§8.3 п.2);
 * - мастер не принимает количество больше остатка (§8.4 шаг 2);
 * - у ФД (`read_only`) флажков и кнопок нет, есть колонка «Исполнитель».
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { createTestQueryClient } from '@/test/renderWithProviders';

import type { PlanItem } from './api';
import { PlanPage } from './PlanPage';
import { qtyProblem, selectionProblem, shownQty } from './planSelection';

const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get, post } }));
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() } }));

const item = (over: Partial<PlanItem>): PlanItem => ({
  id: 'i1', sys_number: 'ЗЗ-2026-000045-01', request_id: 'r1', request_number: 'ЗЗ-2026-000045',
  project_id: 'p1', project_code: 'П-015', article_id: 'a1', article_name: 'Металлопрокат',
  name: 'Швеллер 12П', uom: 'т', qty: '10.000', qty_in_agreements: '0', qty_in_invoices: '0',
  qty_left: '10.000', amount: '2400000.00', amount_in_invoices: '0.00',
  amount_left: '2400000.00', need_date: '2099-10-15', overdue: false, purchase_type: 'goods',
  in_agreement_on_review: false, executor_id: 904, executor_name: 'Иванов А.', selectable: true,
  ...over,
});

function serve(items: PlanItem[], readOnly = false) {
  get.mockImplementation((url: string) => {
    if (url.endsWith('bpp/v1/me')) {
      return Promise.resolve({ data: { article_groups: ['supply'], initiator_roles: readOnly ? [] : ['sn'] } });
    }
    if (url.endsWith('bpp/v1/plan')) {
      return Promise.resolve({
        data: { items, total: items.length, page: 1, page_size: 50, read_only: readOnly },
      });
    }
    return Promise.resolve({ data: [] });
  });
}

function renderPlan() {
  return render(
    <QueryClientProvider client={createTestQueryClient()}>
      <MemoryRouter><PlanPage /></MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('правила выбора', () => {
  it('один проект и одна статья', () => {
    expect(selectionProblem([])).toBe('Отметьте позиции для документа');
    expect(selectionProblem([item({}), item({ id: 'i2', article_id: 'a2' })]))
      .toBe('Для одного документа выберите позиции одного проекта и одной статьи');
    expect(selectionProblem([item({}), item({ id: 'i2' })])).toBeNull();
  });

  it('количество мастера — больше нуля и не больше остатка', () => {
    expect(qtyProblem('2,5', '2.500')).toBeNull();
    expect(qtyProblem('3', '2.500')).toBe('Не больше остатка 2,5');
    expect(qtyProblem('0', '2.500')).toBe('Количество — больше нуля');
    expect(shownQty('10.000')).toBe('10');
    expect(shownQty('100')).toBe('100');
  });
});

describe('PlanPage', () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.clearAllMocks();
  });

  it('разные статьи — кнопки документа недоступны, остаток 0 — флажок недоступен', { timeout: 15000 }, async () => {
    serve([
      item({}),
      item({ id: 'i2', sys_number: 'ЗЗ-2026-000046-01', article_id: 'a2', article_name: 'Трубы' }),
      item({ id: 'i3', sys_number: 'ЗЗ-2026-000047-01', qty_left: '0.000', selectable: false }),
    ]);
    renderPlan();

    await userEvent.click(await screen.findByRole(
      'checkbox', { name: 'Отметить ЗЗ-2026-000045-01' }, { timeout: 4000 },
    ));
    await userEvent.click(screen.getByRole('checkbox', { name: 'Отметить ЗЗ-2026-000046-01' }));

    expect(screen.getByRole('button', { name: 'Оформить договор' })).toBeDisabled();
    expect(screen.getByRole('status')).toHaveTextContent(
      'Для одного документа выберите позиции одного проекта и одной статьи',
    );
    expect(screen.getByRole('checkbox', { name: 'Отметить ЗЗ-2026-000047-01' })).toBeDisabled();
  });

  it('мастер: проверка сервером и количество не больше остатка', { timeout: 15000 }, async () => {
    serve([item({})]);
    post.mockResolvedValue({
      data: {
        ok: true, target: 'contract', project_id: 'p1', article_id: 'a1', purchase_type: 'goods',
        items: [{ id: 'i1', sys_number: 'ЗЗ-2026-000045-01', name: 'Швеллер 12П', qty_left: '10.000', amount_left: '2400000.00' }],
      },
    });
    renderPlan();

    await userEvent.click(await screen.findByRole(
      'checkbox', { name: 'Отметить ЗЗ-2026-000045-01' }, { timeout: 4000 },
    ));
    await userEvent.click(screen.getByRole('button', { name: 'Оформить договор' }));

    await waitFor(() => expect(post).toHaveBeenCalled());
    expect(post.mock.calls[0][1]).toEqual({ item_ids: ['i1'], target: 'contract', role: 'sn' });
    const dialog = await screen.findByRole('dialog');
    const qty = within(dialog).getByRole('textbox', { name: 'Количество ЗЗ-2026-000045-01' });
    expect(qty).toHaveValue('10');
    await userEvent.clear(qty);
    await userEvent.type(qty, '12');
    expect(within(dialog).getByText('Не больше остатка 10')).toBeInTheDocument();
  });

  it('ФД — все позиции без флажков и кнопок, с исполнителем', { timeout: 15000 }, async () => {
    serve([item({ selectable: false })], true);
    renderPlan();

    expect(await screen.findByText('Иванов А.', {}, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.queryByRole('checkbox', { name: /Отметить/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Оформить договор' })).not.toBeInTheDocument();
    expect(screen.getByText('Все позиции — только просмотр')).toBeInTheDocument();
  });
});
