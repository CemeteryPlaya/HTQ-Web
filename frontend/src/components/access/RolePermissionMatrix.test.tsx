/**
 * Матрица прав роли (§4.2).
 *
 * Проверяется главное свойство редактора: наружу уходит ПОЛНЫЙ набор, а не
 * список правок. Иначе «снять уровень» и «не трогать модуль» стали бы
 * неразличимы, а `PUT` заменяет набор целиком — то есть неотправленный модуль
 * молча лишался бы прав.
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { RolePermissionMatrix } from './RolePermissionMatrix';

describe('RolePermissionMatrix', () => {
  it('показывает текущий уровень модуля', () => {
    render(
      <RolePermissionMatrix
        value={[{ module: 'hr', level: 'write' }]}
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByLabelText('Кадры: Запись')).toBeChecked();
    expect(screen.getByLabelText('Кадры: Чтение')).not.toBeChecked();
  });

  it('модуль без уровня показан как «нет доступа»', () => {
    render(<RolePermissionMatrix value={[]} onChange={vi.fn()} />);

    expect(screen.getByLabelText('Задачи и проекты: Нет')).toBeChecked();
  });

  it('отдаёт весь набор, а не одну правку', async () => {
    const onChange = vi.fn();
    render(
      <RolePermissionMatrix
        value={[{ module: 'hr', level: 'read' }, { module: 'tasks', level: 'write' }]}
        onChange={onChange}
      />,
    );

    await userEvent.click(screen.getByLabelText('Кадры: Администрирование'));

    expect(onChange).toHaveBeenCalledWith([
      { module: 'hr', level: 'admin' },
      { module: 'tasks', level: 'write' },
    ]);
  });

  it('снятый модуль исчезает из набора, а не остаётся с none', async () => {
    const onChange = vi.fn();
    render(
      <RolePermissionMatrix
        value={[{ module: 'hr', level: 'read' }, { module: 'tasks', level: 'write' }]}
        onChange={onChange}
      />,
    );

    await userEvent.click(screen.getByLabelText('Кадры: Нет'));

    expect(onChange).toHaveBeenCalledWith([{ module: 'tasks', level: 'write' }]);
  });

  it('в режиме просмотра переключатели заблокированы', () => {
    render(<RolePermissionMatrix value={[]} onChange={vi.fn()} disabled />);

    expect(screen.getByLabelText('Кадры: Запись')).toBeDisabled();
  });
});
