/**
 * Выбор контрагента в карточке партнёра (A6.1): ищет ручкой задач, отдаёт
 * строку поиска целиком (форма подтягивает из неё реквизиты), выбор
 * снимается крестиком, отказ сервера — его текстом, а не «ничего нет».
 */
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';

import { ContractorCounterpartyPicker } from './ContractorCounterpartyPicker';

const get = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get } }));

const toastError = vi.hoisted(() => vi.fn());
vi.mock('sonner', () => ({ toast: { error: toastError, success: vi.fn(), info: vi.fn() } }));

const ALPHA = {
  id: '6f1c2a5e-0000-4000-8000-000000000001', name: 'ТОО «Альфа»', short_name: 'Альфа',
  reg_number: '123456789012', status: 'active', country_code: 'KZ',
  contact_person: 'Иванов', phone: '+77010000000', email: 'a@alpha.kz', legal_address: 'Алматы',
};

let user: ReturnType<typeof userEvent.setup>;

beforeEach(() => {
  user = userEvent.setup({ pointerEventsCheck: 0 });
  get.mockReset();
  toastError.mockReset();
});

describe('ContractorCounterpartyPicker', () => {
  it('ищет ручкой задач и отдаёт строку поиска целиком', async () => {
    get.mockResolvedValue({ data: [ALPHA] });
    const onChange = vi.fn();
    renderWithProviders(<ContractorCounterpartyPicker value={null} onChange={onChange} />);

    await user.click(screen.getByRole('combobox'));
    await user.click(await screen.findByRole('option', { name: /Альфа» · 123456789012/ }));

    expect(get.mock.calls[0][0]).toMatch(/contractors\/counterparty-search$/);
    expect(onChange).toHaveBeenCalledWith(ALPHA);
  });

  it('выбранный показывается бейджем и снимается крестиком', async () => {
    const onChange = vi.fn();
    renderWithProviders(
      <ContractorCounterpartyPicker
        value={{ id: ALPHA.id, name: ALPHA.name, reg_number: ALPHA.reg_number, status: 'blocked' }}
        onChange={onChange}
      />,
    );
    expect(screen.getByRole('combobox')).toHaveTextContent('ТОО «Альфа» · 123456789012');

    await user.click(screen.getByRole('button', { name: 'Снять связь с контрагентом' }));
    expect(onChange).toHaveBeenCalledWith(null);
    expect(get).not.toHaveBeenCalled();
  });

  it('пусто без поиска — «действующих нет» с подсказкой, где их заводят', async () => {
    get.mockResolvedValue({ data: [] });
    renderWithProviders(<ContractorCounterpartyPicker value={null} onChange={() => {}} />);
    await user.click(screen.getByRole('combobox'));

    expect(await screen.findByRole('link', { name: 'заведите контрагента в «Закупках и оплатах»' }))
      .toHaveAttribute('href', '/bpp/counterparties/new');
  });

  it('отказ сервера — его текст сообщением, в списке «не удалось загрузить»', async () => {
    get.mockRejectedValue({
      response: { status: 503, data: { detail: 'Модуль «Бюджет, закупки и оплаты» выключен' } },
    });
    renderWithProviders(<ContractorCounterpartyPicker value={null} onChange={() => {}} />);
    await user.click(screen.getByRole('combobox'));

    expect(await screen.findByText('Не удалось загрузить контрагентов')).toBeInTheDocument();
    await waitFor(() => expect(toastError).toHaveBeenCalledWith(
      'Модуль «Бюджет, закупки и оплаты» выключен', undefined));
    expect(screen.queryByText(/Действующих контрагентов нет/)).toBeNull();
  });
});
