/**
 * Окно подтверждения заявки на изменение профиля.
 *
 * Проверяем два инварианта, которые легко потерять при правках вёрстки:
 * нельзя применить решение с нерешёнными строками, и «аккаунт уехал» видно
 * отдельной колонкой — иначе подтверждающий вслепую откатит чужую свежую
 * правку.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import { IdentityRequestDialog } from '@/components/hr/IdentityRequestDialog';

const REQUEST = {
  id: 1,
  employee_id: 5,
  employee_name: 'Иванов Иван',
  department_id: 1,
  user_id: 7,
  status: 'pending' as const,
  source: 'hr_form' as const,
  created_by: 42,
  created_at: '2026-08-25T00:00:00Z',
  decided_by: null,
  decided_at: null,
  decision_note: null,
  fields: [
    {
      field: 'first_name',
      proposed_value: 'Иннокентий',
      account_value_at_request: 'Иван',
      account_value_now: 'Иван',
      is_stale: false,
      decision: null,
    },
    {
      field: 'phone',
      proposed_value: '+7 777 000-00-00',
      account_value_at_request: '+7 705 111-22-33',
      account_value_now: '+7 705 111-22-33',
      is_stale: false,
      decision: null,
    },
  ],
};

vi.mock('@/api/identity', () => ({
  fetchIdentityRequest: vi.fn(async () => REQUEST),
  decideIdentityRequest: vi.fn(async () => REQUEST),
}));

const renderDialog = () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <IdentityRequestDialog requestId={1} onOpenChange={vi.fn()} />
    </QueryClientProvider>,
  );
};

beforeEach(() => {
  vi.clearAllMocks();
  REQUEST.fields[0].is_stale = false;
  REQUEST.fields[0].account_value_now = 'Иван';
});

describe('IdentityRequestDialog', () => {
  it('не даёт применить, пока решены не все строки', async () => {
    renderDialog();
    await screen.findByText('Имя');

    const submit = screen.getByRole('button', { name: /Применить решение/ });
    expect(submit).toBeDisabled();

    // решили только первую строку из двух
    fireEvent.click(screen.getAllByRole('button', { name: /Перенести в аккаунт/ })[0]);
    expect(submit).toBeDisabled();

    fireEvent.click(screen.getAllByRole('button', { name: /Оставить как есть/ })[1]);
    await waitFor(() => expect(submit).toBeEnabled());
  });

  it('показывает колонку «было при подаче», если аккаунт уехал', async () => {
    REQUEST.fields[0].is_stale = true;
    REQUEST.fields[0].account_value_now = 'Совсем другое';

    renderDialog();

    await screen.findByText('Было при подаче');
    expect(screen.getByText('Аккаунт изменился')).toBeInTheDocument();
    expect(screen.getByText('Совсем другое')).toBeInTheDocument();
  });

  it('без расхождения третьей колонки нет', async () => {
    renderDialog();
    await screen.findByText('Имя');

    expect(screen.queryByText('Было при подаче')).not.toBeInTheDocument();
  });
});
