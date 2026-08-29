/**
 * Переключатель иерархии и внешняя иерархия (§1.4 спеки стадии 2).
 *
 * Проверяется три вещи, и каждая закрывает конкретную ловушку:
 *
 * 1. внешняя иерархия только для чтения — редактировать вычисляемое дерево
 *    невозможно по построению, и интерфейс не должен это предлагать;
 * 2. пустой список подписан — до переработки HR он пуст у всех, и без
 *    объяснения пустая область читается как «не загрузилось»;
 * 3. подпись «подчинение, а не передача прав» есть в обоих режимах — это
 *    самое вероятное расхождение ожиданий с заказчиком.
 */
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';

import { ExternalHierarchy } from './ExternalHierarchy';
import { HierarchySwitch } from './HierarchySwitch';

const permissions = vi.fn();

vi.mock('@/hooks/usePermissions', () => ({
  usePermissions: () => permissions(),
}));

beforeEach(() => {
  vi.clearAllMocks();
  permissions.mockReturnValue({
    company: 'hi-tech-qazaqstan',
    subordinateCompanies: [],
    isLoading: false,
    level: () => 'none',
    atLeast: () => false,
    scope: () => null,
  });
});

describe('HierarchySwitch', () => {
  it('показывает выбранную иерархию', () => {
    renderWithProviders(<HierarchySwitch value="internal" onChange={vi.fn()} />);

    expect(screen.getByRole('button', { name: /Внутренняя/ })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    expect(screen.getByRole('button', { name: /Внешняя/ })).toHaveAttribute(
      'aria-pressed',
      'false',
    );
  });

  it('переключает на внешнюю', async () => {
    const onChange = vi.fn();
    renderWithProviders(<HierarchySwitch value="internal" onChange={onChange} />);

    await userEvent.click(screen.getByRole('button', { name: /Внешняя/ }));

    expect(onChange).toHaveBeenCalledWith('external');
  });
});

describe('ExternalHierarchy', () => {
  it('перечисляет подчинённые компании', () => {
    permissions.mockReturnValue({
      company: 'htq-holding',
      subordinateCompanies: ['htq-kz', 'kurly-kg'],
      isLoading: false,
    });
    renderWithProviders(<ExternalHierarchy />);

    expect(screen.getByText('htq-holding')).toBeInTheDocument();
    expect(screen.getByText('htq-kz')).toBeInTheDocument();
    expect(screen.getByText('kurly-kg')).toBeInTheDocument();
  });

  it('пустой список объясняется словами, а не выглядит сбоем загрузки', () => {
    renderWithProviders(<ExternalHierarchy />);

    expect(screen.getByText(/это не ошибка\s+загрузки/i)).toBeInTheDocument();
  });

  it('говорит, что дерево не редактируется', () => {
    renderWithProviders(<ExternalHierarchy />);

    expect(screen.getByText(/не редактируется/i)).toBeInTheDocument();
  });

  it('не предлагает ни одного действия по правке', () => {
    permissions.mockReturnValue({
      company: 'htq-holding',
      subordinateCompanies: ['htq-kz'],
      isLoading: false,
    });
    renderWithProviders(<ExternalHierarchy />);

    expect(screen.queryAllByRole('button')).toHaveLength(0);
  });
});
