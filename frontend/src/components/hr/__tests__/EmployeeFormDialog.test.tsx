/**
 * Форма сотрудника со встроенными секциями Т-2.
 *
 * Главное, что проверяем: секции гейтуются посекционным RBAC, а в payload
 * уходят ТОЛЬКО изменённые секции — иначе «открыл и сохранил» затирало бы
 * чужие данные.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, fireEvent, act, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import { EmployeeFormDialog } from '@/components/hr/EmployeeFormDialog';

const hasPerm = vi.fn();

vi.mock('@/hooks/useHRLevel', () => ({
  useHRLevel: () => ({
    level: 'lead',
    hasHrAccess: true,
    canWriteBasic: true,
    canCreateEmployee: true,
    canTransferEmployee: true,
    canDeleteEmployee: true,
    canListUserOptions: true,
    canManageUserOptions: true,
    permissions: [],
    hasPerm,
    isLoading: false,
  }),
}));

vi.mock('@/api/hr', () => ({
  fetchDepartments: vi.fn(async () => [{ id: 1, name: 'ИТ' }]),
  fetchPositions: vi.fn(async () => [{ id: 2, title: 'Инженер', department_id: 1 }]),
  fetchEmployeeUsers: vi.fn(async () => [
    { id: 7, full_name: 'Иванов Иван', email: 'ivanov@htq.test', first_name: 'Иван', last_name: 'Иванов' },
  ]),
  fetchCardT2: vi.fn(async () => ({
    financial: { salary: '450000.00', bonus: null, bank_account: null },
    personal: { passport_data: null, inn: null, birth_date: null, birth_place: null, citizenship: 'KZ' },
    certs: { sro_permit_number: null, sro_permit_expiry: null, safety_cert_number: null, safety_cert_expiry: null },
  })),
  createEmployeeWithCard: vi.fn(async () => ({ id: 99 })),
  updateEmployeeWithCard: vi.fn(async () => ({ id: 42 })),
  createDepartment: vi.fn(),
  createPosition: vi.fn(),
  createEmployeeUser: vi.fn(),
}));

vi.mock('@/components/hr/ShareEmployeeDialog', () => ({
  ShareEmployeeDialog: () => null,
}));

import { createEmployeeWithCard, updateEmployeeWithCard } from '@/api/hr';

const mockCreate = vi.mocked(createEmployeeWithCard);
const mockUpdate = vi.mocked(updateEmployeeWithCard);

const EMPLOYEE = {
  id: 42,
  user_id: 7,
  first_name: 'Иван',
  last_name: 'Иванов',
  email: 'ivanov@htq.test',
  position_id: 2,
  department_id: 1,
  phone: '+77010000000',
  hire_date: '2024-01-09',
  status: 'active',
};

function renderDialog(employee: typeof EMPLOYEE | null) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <MemoryRouter>
      <QueryClientProvider client={client}>
        <EmployeeFormDialog open employee={employee as never} onOpenChange={vi.fn()} />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

const save = () => act(() => {
  fireEvent.click(screen.getByRole('button', { name: /^Сохранить$/ }));
});

beforeEach(() => {
  vi.clearAllMocks();
  hasPerm.mockImplementation(() => true);
});

describe('EmployeeFormDialog — секции Т-2', () => {
  it('не показывает секцию без права view', async () => {
    hasPerm.mockImplementation(
      (key: string) => key !== 'hr.card.financial.view' && key !== 'hr.card.financial.edit',
    );
    renderDialog(EMPLOYEE);

    await waitFor(() => expect(screen.getByText(/Личные данные/)).toBeInTheDocument());
    expect(screen.queryByText(/Финансовые данные/)).not.toBeInTheDocument();
  });

  it('скрывает секцию, на которую есть edit, но нет view — иначе сохранение затёрло бы её null-ами', async () => {
    // edit есть, view нет: показывать нечего, а показать пустую форму значит
    // предложить пользователю затереть данные, которых он не видит.
    hasPerm.mockImplementation((key: string) => key !== 'hr.card.financial.view');
    renderDialog(EMPLOYEE);

    await waitFor(() => expect(screen.getByText(/Личные данные/)).toBeInTheDocument());
    expect(screen.queryByText(/Финансовые данные/)).not.toBeInTheDocument();
  });

  it('делает поля read-only при view без edit', async () => {
    hasPerm.mockImplementation((key: string) => key !== 'hr.card.financial.edit');
    renderDialog(EMPLOYEE);

    fireEvent.click(await screen.findByText(/Финансовые данные/));
    expect(await screen.findByLabelText(/Оклад/)).toHaveAttribute('readonly');
  });

  it('шлёт только изменённые секции', async () => {
    renderDialog(EMPLOYEE);

    fireEvent.click(await screen.findByText(/Личные данные/));
    await act(async () => {
      fireEvent.change(await screen.findByLabelText(/Гражданство/), { target: { value: 'RU' } });
    });
    save();

    await waitFor(() => expect(mockUpdate).toHaveBeenCalledTimes(1));
    const [, payload] = mockUpdate.mock.calls[0]!;
    expect(Object.keys(payload.card_t2 as object)).toEqual(['personal']);
    expect((payload.card_t2 as Record<string, Record<string, unknown>>).personal!.citizenship).toBe('RU');
  });

  it('не кладёт card_t2 в тело, если Т-2 не трогали', async () => {
    renderDialog(EMPLOYEE);

    await waitFor(() => expect(screen.getByText(/Личные данные/)).toBeInTheDocument());
    save();

    await waitFor(() => expect(mockUpdate).toHaveBeenCalledTimes(1));
    expect(mockUpdate.mock.calls[0]![1]).not.toHaveProperty('card_t2');
  });

  it('не отправляет запрос при нечисловом окладе', async () => {
    renderDialog(EMPLOYEE);

    fireEvent.click(await screen.findByText(/Финансовые данные/));
    await act(async () => {
      fireEvent.change(await screen.findByLabelText(/Оклад/), { target: { value: 'много' } });
    });
    save();

    expect(mockUpdate).not.toHaveBeenCalled();
    expect(screen.getByText(/Введите число/)).toBeInTheDocument();
  });

  it('в режиме создания нет кнопок «Открыть карточку» и «Поделиться»', () => {
    renderDialog(null);

    expect(screen.queryByRole('button', { name: /Открыть карточку/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Поделиться/ })).not.toBeInTheDocument();
  });

  it('в режиме редактирования обе кнопки есть', async () => {
    renderDialog(EMPLOYEE);

    expect(await screen.findByRole('button', { name: /Открыть карточку/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Поделиться/ })).toBeInTheDocument();
  });
});
