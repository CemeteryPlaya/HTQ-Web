/**
 * «Мои согласования» (D-34): очередь движка signoff, из которой видны
 * только документы модуля (`bpp.*`); строка ведёт на карточку процесса.
 */
import { screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';
import type { InboxItem } from '@/types/signoff';

import MyApprovalsPage from './MyApprovalsPage';

const item = (over: Partial<InboxItem>): InboxItem => ({
  task_id: 1,
  process_id: 10,
  subject_type: 'bpp.purchase_request',
  subject_id: '3fa85f64-5717-4562-b3fc-2c963f66afa6',
  subject_title: 'Заявка ЗЗ-2026-000045',
  subject_url: '/bpp/requests/3fa85f64-5717-4562-b3fc-2c963f66afa6',
  stage_name: 'Технический директор',
  stage_order: 1,
  stage_count: 3,
  quorum: 'any',
  requires_attachment: false,
  requires_comment: false,
  requirement_label: null,
  file_id: null,
  initiator_id: 5,
  created_at: '2026-09-27T20:30:00Z',
  ...over,
});

const inbox = vi.hoisted(() => vi.fn());
vi.mock('@/api/signoff', () => ({ signoffApi: { inbox } }));

describe('MyApprovalsPage', () => {
  it('показывает только документы модуля bpp.*', async () => {
    inbox.mockResolvedValue({
      data: [
        item({}),
        item({
          task_id: 2, process_id: 20, subject_type: 'contracts.agreement', subject_id: '7',
          subject_title: 'Договор №7', subject_url: '/contracts/agreements/7',
        }),
        item({
          task_id: 3, process_id: 30, subject_type: 'approvals.request', subject_id: '9',
          subject_title: 'Заявка конструктора №9', subject_url: '/requests/9',
        }),
        item({
          task_id: 4, process_id: 40, subject_type: 'bpp.accountable_funds_request',
          subject_id: 'a1', subject_title: 'Подотчёт ПО-2026-000001',
          subject_url: '/bpp/accountable/a1', stage_count: 1,
        }),
      ],
    });
    renderWithProviders(<MyApprovalsPage />);

    expect(await screen.findByText('Заявка ЗЗ-2026-000045')).toBeInTheDocument();
    expect(screen.getByText('Подотчёт ПО-2026-000001')).toBeInTheDocument();
    expect(screen.queryByText('Договор №7')).not.toBeInTheDocument();
    expect(screen.queryByText('Заявка конструктора №9')).not.toBeInTheDocument();
    expect(screen.getAllByRole('row')).toHaveLength(3); // шапка + две строки
  });

  it('строка ведёт на карточку процесса, время — по Алматы', async () => {
    inbox.mockResolvedValue({ data: [item({})] });
    renderWithProviders(<MyApprovalsPage />);

    const row = (await screen.findByText('Заявка ЗЗ-2026-000045')).closest('tr')!;
    expect(within(row).getByRole('link', { name: /Открыть/ }))
      .toHaveAttribute('href', '/signoff/processes/10');
    expect(within(row).getByText('28.09.2026 01:30')).toBeInTheDocument();
    expect(within(row).getByText('Этап 1 из 3')).toBeInTheDocument();
  });

  it('пустая очередь модуля — объяснение, а не пустая таблица', async () => {
    inbox.mockResolvedValue({
      data: [item({ subject_type: 'contracts.invoice', subject_title: 'Счёт' })],
    });
    renderWithProviders(<MyApprovalsPage />);
    expect(await screen.findByText('Нет документов, ожидающих вашего решения')).toBeInTheDocument();
    expect(screen.queryByText('Счёт')).not.toBeInTheDocument();
  });
});
