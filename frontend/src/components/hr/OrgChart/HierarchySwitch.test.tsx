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
const tree = vi.fn();

vi.mock('@/hooks/usePermissions', () => ({
  usePermissions: () => permissions(),
}));
vi.mock('@/api/companies', () => ({ companiesApi: { tree: () => tree() } }));

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
  // По умолчанию реестр компаний недоступен (403): часть тестов ниже
  // намеренно проверяет именно деградацию до списка слагов, а не дерево
  // из реестра. `ExternalHierarchy` теперь ждёт оседания этого запроса
  // (см. ExternalHierarchy.test.tsx), поэтому проверки в этом файле — async.
  tree.mockRejectedValue({ response: { status: 403 } });
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
  it('перечисляет подчинённые компании', async () => {
    permissions.mockReturnValue({
      company: 'htq-holding',
      subordinateCompanies: ['htq-kz', 'kurly-kg'],
      isLoading: false,
    });
    renderWithProviders(<ExternalHierarchy />);

    expect(await screen.findByText('htq-holding')).toBeInTheDocument();
    expect(screen.getByText('htq-kz')).toBeInTheDocument();
    expect(screen.getByText('kurly-kg')).toBeInTheDocument();
  });

  it('пустой список объясняется словами, а не выглядит сбоем загрузки', async () => {
    renderWithProviders(<ExternalHierarchy />);

    expect(await screen.findByText(/это не ошибка\s+загрузки/i)).toBeInTheDocument();
  });

  it('говорит, что дерево не редактируется', async () => {
    renderWithProviders(<ExternalHierarchy />);

    expect(await screen.findByText(/не редактируется/i)).toBeInTheDocument();
  });

  it('не предлагает ни одного действия по правке', async () => {
    permissions.mockReturnValue({
      company: 'htq-holding',
      subordinateCompanies: ['htq-kz'],
      isLoading: false,
    });
    renderWithProviders(<ExternalHierarchy />);

    expect(await screen.findByText('htq-kz')).toBeInTheDocument();
    expect(screen.queryAllByRole('button')).toHaveLength(0);
  });
});
