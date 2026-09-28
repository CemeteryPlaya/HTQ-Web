/**
 * Вкладка «История изменений» (ТЗ §25.2, §05; задача 8): журнал
 * `GET /api/bpp/v1/history/<тип>/<id>` — дата по Алматы, кто, действие,
 * было/стало, комментарий; 404 — «История недоступна», а не общая ошибка.
 */
import { screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';

import { HistoryTab, type HistoryEntry } from './HistoryTab';

const get = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get } }));

const entry = (over: Partial<HistoryEntry>): HistoryEntry => ({
  id: '1',
  action: 'updated',
  actor_id: 5,
  actor_name: null,
  changes: {},
  comment: '',
  created_at: '2026-09-27T20:30:00Z',
  ...over,
});

describe('HistoryTab', () => {
  it('строка журнала: когда, кто, действие, было/стало, комментарий', async () => {
    get.mockResolvedValue({
      data: [entry({
        action: 'updated',
        actor_name: 'Иванов А.',
        changes: { before: { amount: '100.00' }, after: { amount: '150.00' } },
        comment: 'Согласовано с ФД',
      })],
    });

    renderWithProviders(<HistoryTab objectType="bpp.purchaserequest" objectId="1" />);

    expect(await screen.findByText('28.09.2026 01:30')).toBeInTheDocument();
    expect(screen.getByText('Иванов А.')).toBeInTheDocument();
    expect(screen.getByText('Изменён')).toBeInTheDocument();
    expect(screen.getByText('100.00')).toBeInTheDocument();
    expect(screen.getByText('150.00')).toBeInTheDocument();
    expect(screen.getByText('Согласовано с ФД')).toBeInTheDocument();
  });

  it('без имени — «Пользователь №id»; без actor_id — «Система»', async () => {
    get.mockResolvedValue({
      data: [
        entry({ id: '1', actor_id: 7, actor_name: null }),
        entry({ id: '2', actor_id: null }),
      ],
    });

    renderWithProviders(<HistoryTab objectType="bpp.purchaserequest" objectId="1" />);

    expect(await screen.findByText('Пользователь №7')).toBeInTheDocument();
    expect(screen.getByText('Система')).toBeInTheDocument();
  });

  it('404 — «История недоступна»', async () => {
    get.mockRejectedValue({ response: { status: 404 } });
    renderWithProviders(<HistoryTab objectType="bpp.unregistered" objectId="1" />);
    expect(await screen.findByText('История недоступна')).toBeInTheDocument();
  });

  it('другая ошибка — общее сообщение, не «недоступна»', async () => {
    get.mockRejectedValue({ response: { status: 500 } });
    renderWithProviders(<HistoryTab objectType="bpp.purchaserequest" objectId="1" />);
    await waitFor(() =>
      expect(screen.getByText('Не удалось загрузить историю. Обновите страницу.')).toBeInTheDocument());
    expect(screen.queryByText('История недоступна')).not.toBeInTheDocument();
  });

  it('подписи полей и денежные поля — от экрана; прочее — как пришло', async () => {
    get.mockResolvedValue({
      data: [entry({
        changes: {
          before: { total_amount: '1250000.5', vat_rate: '12.00', note: 'а' },
          after: { total_amount: '99999999999999.99', vat_rate: '16.00', note: 'б' },
        },
      })],
    });

    renderWithProviders(
      <HistoryTab
        objectType="bpp.purchaserequest"
        objectId="1"
        fieldLabels={{ total_amount: 'Сумма', vat_rate: 'Ставка НДС' }}
        moneyFields={['total_amount']}
      />,
    );

    expect(await screen.findByText('Сумма')).toBeInTheDocument();
    expect(screen.getByText('1 250 000,50')).toBeInTheDocument();
    expect(screen.getByText('99 999 999 999 999,99')).toBeInTheDocument();
    // Не названное денежным не форматируется, даже если похоже на сумму.
    expect(screen.getByText('Ставка НДС')).toBeInTheDocument();
    expect(screen.getByText('16.00')).toBeInTheDocument();
    // Без подписи — имя поля.
    expect(screen.getByText('note')).toBeInTheDocument();
  });

  it('денежное поле в формате «[было, стало]» и пустое значение', async () => {
    get.mockResolvedValue({
      data: [entry({ changes: { amount: [null, '1000'] } })],
    });

    renderWithProviders(
      <HistoryTab objectType="bpp.purchaserequest" objectId="1" moneyFields={['amount']} />,
    );

    expect(await screen.findByText('1 000,00')).toBeInTheDocument();
    expect(screen.getByRole('listitem')).toHaveTextContent('amount: — → 1 000,00');
  });

  it('пустой журнал — «Изменений пока нет»', async () => {
    get.mockResolvedValue({ data: [] });
    renderWithProviders(<HistoryTab objectType="bpp.purchaserequest" objectId="1" />);
    expect(await screen.findByText('Изменений пока нет')).toBeInTheDocument();
  });
});
