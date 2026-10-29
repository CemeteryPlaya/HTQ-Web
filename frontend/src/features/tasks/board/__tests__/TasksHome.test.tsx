/**
 * Раздел «Задачи» — доски (этап S6a, решения R-03, R-04): `/tasks` ведёт на
 * последнюю открытую доску (в первый раз — личную) и переносит параметры
 * адреса; «Доска | Таблица» ведёт на последнюю доску и на `/tasks/list`.
 */
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach, describe, expect, it } from 'vitest';

import { rememberBoard } from '../boardRoutes';
import TasksHome from '../TasksHome';
import { TasksViewToggle } from '../TasksViewToggle';

function Where() {
  const location = useLocation();
  return <p data-testid="where">{`${location.pathname}${location.search}`}</p>;
}

function openTasks(url: string) {
  render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/tasks" element={<TasksHome />} />
        <Route path="*" element={<Where />} />
      </Routes>
    </MemoryRouter>,
  );
  return screen.getByTestId('where').textContent;
}

afterEach(() => window.localStorage.clear());

describe('раздел «Задачи» — доски', () => {
  it('в первый раз /tasks — личная доска, ?card= переезжает с ней', () => {
    expect(openTasks('/tasks?card=5')).toBe('/tasks/board?card=5');
  });

  it('потом — последняя открытая доска', () => {
    rememberBoard({ kind: 'department', id: 2 });
    expect(openTasks('/tasks')).toBe('/tasks/board/department/2');
  });

  it('чужое значение в хранилище не уводит со страницы доски', () => {
    window.localStorage.setItem('tasks.board.last', 'https://example.com');
    expect(openTasks('/tasks')).toBe('/tasks/board');
  });

  it('«Доска | Таблица»: доска — последняя открытая, таблица — /tasks/list', () => {
    rememberBoard({ kind: 'project', id: 7 });
    render(<MemoryRouter><TasksViewToggle current="table" /></MemoryRouter>);
    expect(screen.getByRole('link', { name: /Доска/ })).toHaveAttribute('href', '/tasks/board/project/7');
    const table = screen.getByRole('link', { name: /Таблица/ });
    expect(table).toHaveAttribute('href', '/tasks/list');
    expect(table).toHaveAttribute('aria-current', 'page');
  });
});
