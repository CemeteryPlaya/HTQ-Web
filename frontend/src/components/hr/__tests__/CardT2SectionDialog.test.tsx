/**
 * Тесты на правку Т-2 карточки — того самого блока «Финансы»/«Личные данные»,
 * который до этого нельзя было заполнить: во фронтенде не было ни одного
 * вызова на запись, только GET.
 *
 * Главное, что проверяем: сотруднику, заведённому БЕЗ карточки (бэкенд отдаёт
 * секцию со всеми null), форма открывается и сохраняется — строку `EmployeeCard`
 * создаёт `upsert` на бэкенде при первом же сохранении.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, fireEvent, act, waitFor } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import { CardT2SectionDialog } from '@/components/hr/CardT2SectionDialog';

vi.mock('@/api/hr', () => ({ updateCardT2: vi.fn() }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { updateCardT2 } from '@/api/hr';

const mockUpdate = vi.mocked(updateCardT2);

function renderDialog(
  section: 'financial' | 'personal' | 'certs',
  values: Record<string, string | null> | undefined,
  onClose = vi.fn(),
) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <CardT2SectionDialog
        employeeId={42}
        section={section}
        values={values}
        open
        onClose={onClose}
      />
    </QueryClientProvider>,
  );
  return { onClose };
}

const save = () => act(() => {
  fireEvent.click(screen.getByRole('button', { name: /Сохранить/ }));
});
const typeInto = (labelRe: RegExp, value: string) => act(() => {
  fireEvent.change(screen.getByLabelText(labelRe), { target: { value } });
});

beforeEach(() => {
  mockUpdate.mockReset();
  mockUpdate.mockResolvedValue({});
});

describe('CardT2SectionDialog', () => {
  it('заполняет «Финансы» у сотрудника БЕЗ карточки (все значения null)', async () => {
    renderDialog('financial', { salary: null, bonus: null, bank_account: null });

    typeInto(/Оклад/, '450000');
    typeInto(/Банковский счёт/, 'KZ123');
    save();

    await waitFor(() => expect(mockUpdate).toHaveBeenCalledTimes(1));
    expect(mockUpdate).toHaveBeenCalledWith(42, 'financial', {
      salary: '450000',
      bonus: null,        // пустое поле уходит null, а не '' — иначе 422 на бэкенде
      bank_account: 'KZ123',
    });
  });

  it('шлёт ТОЛЬКО свою секцию — правка «Личных данных» не трогает финансы', async () => {
    renderDialog('personal', undefined);

    typeInto(/Гражданство/, 'KZ');
    save();

    await waitFor(() => expect(mockUpdate).toHaveBeenCalledTimes(1));
    const [, section, payload] = mockUpdate.mock.calls[0]!;
    expect(section).toBe('personal');
    expect(Object.keys(payload).sort()).toEqual(
      ['birth_date', 'birth_place', 'citizenship', 'inn', 'passport_data'],
    );
  });

  it('нормализует запятую в сумме к точке', async () => {
    renderDialog('financial', undefined);

    typeInto(/Оклад/, '450000,50');
    save();

    await waitFor(() => expect(mockUpdate).toHaveBeenCalledTimes(1));
    expect(mockUpdate.mock.calls[0]![2].salary).toBe('450000.50');
  });

  it('не отправляет запрос при нечисловой сумме и показывает ошибку', () => {
    renderDialog('financial', undefined);

    typeInto(/Оклад/, 'много');
    save();

    expect(mockUpdate).not.toHaveBeenCalled();
    expect(screen.getByText(/Введите число/)).toBeInTheDocument();
  });

  it('подставляет уже сохранённые значения при открытии', () => {
    renderDialog('certs', {
      sro_permit_number: 'СРО-77',
      sro_permit_expiry: '2027-01-31',
      safety_cert_number: null,
      safety_cert_expiry: null,
    });

    expect(screen.getByLabelText(/Номер допуска СРО/)).toHaveValue('СРО-77');
    expect(screen.getByLabelText(/Срок действия допуска СРО/)).toHaveValue('2027-01-31');
  });

  it('закрывается после успешного сохранения', async () => {
    const { onClose } = renderDialog('financial', undefined);

    typeInto(/Оклад/, '1000');
    save();

    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });
});
