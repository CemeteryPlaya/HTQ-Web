/**
 * Заявка на закупку в карточке согласования: позиции, сумма и блок «Бюджет»
 * в формате модуля (`1 250 000,00 KZT`).
 */
import { screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { formatDate, formatMoney } from '@/features/bpp/format';
import RequestSignoffView from '@/features/bpp/requests/RequestSignoffView';
import type { PurchaseRequestCard } from '@/features/bpp/requests/api';
import { renderWithProviders } from '@/test/renderWithProviders';

const card: PurchaseRequestCard = {
  id: '3fa85f64-5717-4562-b3fc-2c963f66afa6',
  number: 'ЗЗ-2026-000045',
  status: 'in_approval',
  author_name: 'Иванов А.',
  created_at: '2026-09-27T10:00:00Z',
  initiator_role: 'sn',
  project: { id: 'p', code: 'П-015', name: 'Объект 15' },
  article: { id: 'a', code: 'MET', name: 'Металлопрокат', archived: false },
  purchase_type: 'goods',
  need_date: '2026-10-15',
  justification: 'Нужно для монтажа каркаса',
  currency_code: 'KZT',
  total_amount: '2400000.00',
  rework_comment: '',
  budget: {
    limit: '5000000.00', committed: '3400000.00', available: '1600000.00',
    after_request: '1600000.00', reserved: true,
  },
  items: [{
    id: 'i1', line_no: 1, sys_number: 'ЗЗ-2026-000045-01', name: 'Швеллер 12П', specs: '',
    uom: 'т', qty: '10.000', price: '240000.00', amount: '2400000.00',
    need_date: '2026-10-15', status: 'open',
  }],
  files: [],
};

vi.mock('@/features/bpp/requests/api', () => ({
  bppRequestsApi: { get: vi.fn(() => Promise.resolve(card)) },
}));

describe('RequestSignoffView', () => {
  it('пишет суммы и даты по правилам модуля', () => {
    expect(formatMoney('1250000', 'KZT')).toBe('1 250 000,00 KZT');
    expect(formatMoney('0.5')).toBe('0,50');
    expect(formatDate('2026-10-15')).toBe('15.10.2026');
    expect(formatDate(null)).toBe('—');
  });

  it('показывает позиции, итог и бюджет статьи', async () => {
    renderWithProviders(<RequestSignoffView id={card.id} embedded />);
    expect(await screen.findByText('ЗЗ-2026-000045-01')).toBeInTheDocument();
    expect(screen.getByText('Швеллер 12П')).toBeInTheDocument();
    expect(screen.getAllByText('2 400 000,00 KZT').length).toBeGreaterThan(0);
    // Заявка уже в резерве — остаток после неё и есть «Доступно».
    expect(screen.getByText('Остаток после заявки (уже в резерве)')).toBeInTheDocument();
    expect(screen.getAllByText('1 600 000,00 KZT')).toHaveLength(2);
  });
});
