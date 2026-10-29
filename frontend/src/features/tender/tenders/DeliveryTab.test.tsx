/**
 * Вкладка «Поставка» (TND-040…TND-042): стадии, документы БЗО ссылками
 * (и замена альтернативой), «Отметить получение» — со стадии «В поставке»
 * и только у автора, «Оригиналы переданы», отмена приёмки с причиной,
 * сканы — панель файлов владельца `tender.receipt`.
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { createTestQueryClient } from '@/test/renderWithProviders';

import type { DeliverySupplier, Receipt } from './delivery';
import { DeliveryTab } from './DeliveryTab';
import { TENDER_ID, deliverySupplier, receipt } from './testData';

const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
const patch = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get, post, patch, put: vi.fn(), delete: vi.fn() } }));
const toast = vi.hoisted(() => ({ error: vi.fn(), success: vi.fn(), info: vi.fn() }));
vi.mock('sonner', () => ({ toast }));
vi.mock('@/components/files/FilesPanel', () => ({
  FilesPanel: ({ ownerType, ownerId, readOnly }: { ownerType: string; ownerId: string; readOnly?: boolean }) => (
    <div data-testid="files-panel">{`${ownerType}:${ownerId}:${readOnly ? 'ro' : 'rw'}`}</div>
  ),
}));

const onChanged = vi.fn();

function serve(suppliers: DeliverySupplier[], receipts: Receipt[] = []) {
  get.mockImplementation((url: string) => {
    if (url.endsWith(`tenders/${TENDER_ID}/delivery`)) {
      return Promise.resolve({ data: { tender_id: TENDER_ID, status: 'delivery', suppliers } });
    }
    if (url.endsWith(`tenders/${TENDER_ID}/receipts`)) return Promise.resolve({ data: receipts });
    return Promise.reject(new Error(`unexpected ${url}`));
  });
}

function renderTab(canReceive = true) {
  return render(
    <QueryClientProvider client={createTestQueryClient()}>
      <MemoryRouter>
        <DeliveryTab tenderId={TENDER_ID} canReceive={canReceive} onChanged={onChanged} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  get.mockReset();
  post.mockReset();
  patch.mockReset();
  onChanged.mockReset();
});

describe('DeliveryTab', () => {
  it('стадия, документы БЗО ссылками, замена альтернативой', async () => {
    serve([deliverySupplier({
      stage: 'awaiting_final_payment',
      documents: [
        { doc_type: 'agreement', doc_id: 'ag-1', number: 'ДГ-2026-000003', status: 'active', amount: '900',
          paid_amount: '0', received_at: null, replaced_by: null },
        { doc_type: 'invoice', doc_id: 'doc-1', number: 'СЧ-2026-000010', status: 'replaced', amount: '360',
          paid_amount: '0', received_at: null,
          replaced_by: { doc_type: 'invoice', doc_id: 'doc-2', number: 'СЧ-2026-000011', offer_number: 'АП-2026-000001' } },
      ],
    })]);
    renderTab();
    const card = await screen.findByTestId('delivery-inv-a');
    expect(within(card).getByText('Ждёт оплаты остатка')).toBeInTheDocument();
    expect(within(card).getByRole('link', { name: 'ДГ-2026-000003' })).toHaveAttribute('href', '/bpp/agreements/ag-1');
    expect(within(card).getByRole('link', { name: 'СЧ-2026-000010' })).toHaveAttribute('href', '/bpp/invoices/doc-1');
    expect(within(card).getByText(/заменён по АП-2026-000001/)).toBeInTheDocument();
    expect(within(card).getByRole('link', { name: 'СЧ-2026-000011' })).toHaveAttribute('href', '/bpp/invoices/doc-2');
    expect(within(card).getByText('Арматура А500: принято 4 из 10')).toBeInTheDocument();
    expect(within(card).getByText('Доставка: принимается вместе с товаром')).toBeInTheDocument();
  });

  it('«Отметить получение» — со стадии «В поставке», не раньше и не без права', async () => {
    serve([
      deliverySupplier(),
      deliverySupplier({ invitation_id: 'inv-b', supplier: 'ТОО «Бета»', stage: 'awaiting_shipment_payment' }),
    ]);
    const { unmount } = renderTab();
    const ready = await screen.findByTestId('delivery-inv-a');
    expect(within(ready).getByRole('button', { name: 'Отметить получение' })).toBeInTheDocument();
    expect(within(screen.getByTestId('delivery-inv-b')).queryByRole('button', { name: 'Отметить получение' })).toBeNull();
    unmount();

    renderTab(false);
    const viewer = await screen.findByTestId('delivery-inv-a');
    expect(within(viewer).queryByRole('button', { name: 'Отметить получение' })).toBeNull();
  });

  it('приёмка: оригиналы переданы — PATCH, сканы — панель файлов приёмки', async () => {
    serve([deliverySupplier()], [receipt()]);
    patch.mockResolvedValue({ data: receipt({ originals_at: '2026-10-20', originals_to: 'Бухгалтерия' }) });
    const user = userEvent.setup();
    renderTab();
    const row = await screen.findByTestId('receipt-rc-1');
    expect(within(row).getByText('Товар получен 19.10.2026')).toBeInTheDocument();
    expect(within(row).getByText('Арматура А500: 4')).toBeInTheDocument();
    expect(within(row).getByTestId('files-panel')).toHaveTextContent('tender.receipt:rc-1:rw');

    await user.click(within(row).getByRole('button', { name: 'Оригиналы переданы' }));
    await user.type(within(row).getByLabelText('Кому'), 'Бухгалтерия');
    await user.click(within(row).getByRole('button', { name: 'Сохранить' }));
    await waitFor(() => expect(patch).toHaveBeenCalled());
    expect(patch.mock.calls[0][0]).toContain(`tenders/${TENDER_ID}/receipts/rc-1`);
    expect(patch.mock.calls[0][1]).toEqual({ originals_at: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/), originals_to: 'Бухгалтерия' });
  });

  it('отмена приёмки — с причиной от 10 символов', async () => {
    serve([deliverySupplier()], [receipt()]);
    post.mockResolvedValue({ data: receipt({ cancelled_at: '2026-10-20T10:00:00Z' }) });
    const user = userEvent.setup();
    renderTab();
    const row = await screen.findByTestId('receipt-rc-1');
    await user.click(within(row).getByRole('button', { name: 'Отменить приёмку' }));
    const dialog = await screen.findByRole('dialog');
    await user.type(within(dialog).getByRole('textbox'), 'Ошиблись поставщиком при отметке');
    await user.click(within(dialog).getByRole('button', { name: 'Отменить приёмку' }));
    await waitFor(() => expect(post).toHaveBeenCalled());
    expect(post.mock.calls[0][0]).toContain(`tenders/${TENDER_ID}/receipts/rc-1/cancel`);
    expect(post.mock.calls[0][1]).toEqual({ comment: 'Ошиблись поставщиком при отметке' });
  });

  it('отменённая приёмка — приглушена, без действий и без файлов', async () => {
    serve([deliverySupplier()], [receipt({ cancelled_at: '2026-10-20T10:00:00Z' })]);
    renderTab();
    const row = await screen.findByTestId('receipt-rc-1');
    expect(row.className).toContain('opacity-60');
    expect(within(row).getByText(/отменена/)).toBeInTheDocument();
    expect(within(row).queryByRole('button')).toBeNull();
    expect(within(row).queryByTestId('files-panel')).toBeNull();
  });
});
