/**
 * Матрица прав роли: функция × глубина.
 *
 * Проверяется главным образом различие «наследует» и «нет доступа». Оно и есть
 * то, ради чего заведён третий уровень реестра: слив их в одно, мы либо лишаем
 * возможности закрыть зарплату внутри разрешённых кадров, либо заставляем
 * расписывать каждый узел руками.
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { AccessFunctionsResponse } from '@/types/access';

import { RolePermissionMatrix } from './RolePermissionMatrix';

const REGISTRY: AccessFunctionsResponse = {
  tree: [
    {
      path: 'hr',
      title: 'Кадры',
      kind: 'module',
      children: [
        {
          path: 'hr.employees',
          title: 'Сотрудники',
          kind: 'function',
          children: [
            { path: 'hr.employees.salary', title: 'Зарплата', kind: 'field', children: [] },
          ],
        },
      ],
    },
    { path: 'tasks', title: 'Задачи', kind: 'module', children: [] },
  ],
  flags: [
    { key: 'view', title: 'видит' },
    { key: 'create', title: 'вводит' },
    { key: 'edit', title: 'редактирует' },
    { key: 'delete', title: 'удаляет' },
  ],
  presets: [
    { key: 'none', title: 'нет доступа', flags: [] },
    { key: 'view', title: 'видит', flags: ['view'] },
    { key: 'create', title: 'может вводить', flags: ['view', 'create'] },
    { key: 'edit', title: 'может редактировать', flags: ['view', 'create', 'edit'] },
    { key: 'delete', title: 'может удалять', flags: ['view', 'delete'] },
    { key: 'full', title: 'полный доступ', flags: ['view', 'create', 'edit', 'delete'] },
  ],
};

const renderMatrix = (value: Parameters<typeof RolePermissionMatrix>[0]['value'],
                      onChange = vi.fn()) => {
  render(<RolePermissionMatrix registry={REGISTRY} value={value} onChange={onChange} />);
  return onChange;
};

describe('RolePermissionMatrix', () => {
  it('показывает все три уровня реестра', () => {
    renderMatrix([]);

    expect(screen.getByText('Кадры')).toBeInTheDocument();
    expect(screen.getByText('Сотрудники')).toBeInTheDocument();
    expect(screen.getByText('Зарплата')).toBeInTheDocument();
  });

  it('выбор глубины на модуле отдаёт узел с флагами пресета', async () => {
    const onChange = renderMatrix([]);

    await userEvent.selectOptions(screen.getByLabelText('Кадры: Глубина'), 'edit');

    expect(onChange).toHaveBeenCalledWith([
      { node: 'hr', flags: ['view', 'create', 'edit'], preset: 'edit' },
    ]);
  });

  it('узел без своей строки подписан унаследованным значением', () => {
    renderMatrix([{ node: 'hr', flags: ['view'], preset: 'view' }]);

    const select = screen.getByLabelText('Сотрудники: Глубина') as HTMLSelectElement;
    expect(select.value).toBe('');
    expect(select.options[0].text).toContain('наследует');
    expect(select.options[0].text).toContain('видит');
  });

  it('явный запрет на поле сохраняется строкой, а не отсутствием строки', async () => {
    const onChange = renderMatrix([{ node: 'hr', flags: ['view'], preset: 'view' }]);

    await userEvent.selectOptions(screen.getByLabelText('Зарплата: Глубина'), 'none');

    expect(onChange).toHaveBeenCalledWith([
      { node: 'hr', flags: ['view'], preset: 'view' },
      { node: 'hr.employees.salary', flags: [], preset: 'none' },
    ]);
  });

  it('возврат к «наследует» убирает строку узла', async () => {
    const onChange = renderMatrix([
      { node: 'hr', flags: ['view'], preset: 'view' },
      { node: 'hr.employees', flags: [], preset: 'none' },
    ]);

    await userEvent.selectOptions(screen.getByLabelText('Сотрудники: Глубина'), '');

    expect(onChange).toHaveBeenCalledWith([{ node: 'hr', flags: ['view'], preset: 'view' }]);
  });

  it('у модуля вместо «наследует» стоит «нет доступа» — наследовать ему не от кого', () => {
    renderMatrix([]);

    const select = screen.getByLabelText('Задачи: Глубина') as HTMLSelectElement;
    expect(select.options[0].text).toBe('нет доступа');
  });

  it('в режиме просмотра выбор заблокирован', () => {
    render(<RolePermissionMatrix registry={REGISTRY} value={[]} onChange={vi.fn()} disabled />);

    expect(screen.getByLabelText('Кадры: Глубина')).toBeDisabled();
  });
});
