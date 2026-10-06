/**
 * «Структура проекта» (спек 2026-10-06 §5): ярусы L1–L4, фильтр «Офис/Объект»,
 * «вакансия» и «уволен», свёрнутое место с планом больше трёх, кнопки правки —
 * только при `can_edit` от сервера.
 */
import { fireEvent, render, screen, within } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { createTestQueryClient } from '@/test/renderWithProviders';

import { ProjectStructureSection } from './ProjectStructureSection';
import type { ProjectStructure, StructureSlot } from './structureApi';

const get = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get, post: vi.fn(), patch: vi.fn(), delete: vi.fn() } }));

const ID = 'p-1';

const slot = (over: Partial<StructureSlot> & { id: string }): StructureSlot => ({
  role: { id: 1, name: 'Руководитель проекта (ГД)', level: 1 },
  part: 'office', title: '', parent_id: null, planned_headcount: 1, actual_headcount: 0,
  closed_on: null, assignments: [], ...over,
});

const person = (id: string, name: string, dismissed = false) => ({
  id, employee_id: Number(id.replace(/\D/g, '')) || 1, full_name: name, position_title: 'Инженер',
  date_from: '2026-01-01', date_to: null, dismissed,
});

const workers = Array.from({ length: 5 }, (_, i) => person(`w${i}`, `Рабочий ${i + 1}`));

const STRUCTURE: StructureSlot[] = [
  slot({ id: 'gd', actual_headcount: 1, assignments: [person('a1', 'Иванов Иван')] }),
  slot({ id: 'td', role: { id: 3, name: 'Технический директор', level: 2 }, parent_id: 'gd' }),
  slot({
    id: 'sp', role: { id: 4, name: 'Специалист', level: 3 }, parent_id: 'td', title: 'сметчик',
    actual_headcount: 1, assignments: [person('a2', 'Петров Пётр', true)],
  }),
  slot({
    id: 'rb', role: { id: 5, name: 'Рабочий', level: 4 }, parent_id: 'sp', part: 'site',
    planned_headcount: 6, actual_headcount: 5, assignments: workers,
  }),
];

function serve(canEdit: boolean, slots: StructureSlot[] = STRUCTURE) {
  get.mockImplementation((url: string) => {
    if (url === `project/v1/projects/${ID}/structure`) {
      const body: ProjectStructure = { project_id: ID, on: '2026-02-01', can_edit: canEdit, slots };
      return Promise.resolve({ data: body });
    }
    return Promise.reject(new Error(`unexpected GET ${url}`));
  });
}

function renderSection() {
  return render(
    <QueryClientProvider client={createTestQueryClient()}>
      <ProjectStructureSection projectId={ID} />
    </QueryClientProvider>,
  );
}

describe('ProjectStructureSection', () => {
  beforeEach(() => { get.mockReset(); });

  it('рисует ярусы L1–L4 с руководителем, вакансией и уволенным', async () => {
    serve(false);
    renderSection();
    const top = await screen.findByTestId('level-1');
    expect(within(top).getByText('Иванов Иван')).toBeInTheDocument();
    const second = screen.getByTestId('level-2');
    expect(within(second).getByText('вакансия')).toBeInTheDocument();
    expect(within(second).getByText('↑ Руководитель проекта (ГД)')).toBeInTheDocument();
    const third = screen.getByTestId('level-3');
    expect(within(third).getByText('Специалист — сметчик')).toBeInTheDocument();
    expect(within(third).getByText('уволен')).toBeInTheDocument();
    expect(within(screen.getByTestId('level-4')).getByText('план 6 / факт 5')).toBeInTheDocument();
  });

  it('место с планом больше трёх свёрнуто и раскрывается по клику', async () => {
    serve(false);
    renderSection();
    const button = await screen.findByRole('button', { name: /Рабочий × 5/ });
    expect(screen.queryByText('Рабочий 1')).not.toBeInTheDocument();
    fireEvent.click(button);
    expect(screen.getByText('Рабочий 1')).toBeInTheDocument();
    expect(screen.getByText('Рабочий 5')).toBeInTheDocument();
  });

  it('фильтр «Объект» оставляет только места на объекте', async () => {
    serve(false);
    renderSection();
    await screen.findByTestId('level-1');
    fireEvent.click(screen.getByRole('button', { name: 'Объект' }));
    expect(screen.queryByTestId('level-1')).not.toBeInTheDocument();
    expect(screen.getByTestId('level-4')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Офис' }));
    expect(screen.queryByTestId('level-4')).not.toBeInTheDocument();
  });

  it('без can_edit кнопок правки нет', async () => {
    serve(false);
    renderSection();
    await screen.findByTestId('level-1');
    expect(screen.queryByRole('button', { name: /Добавить место/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Изменить' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Снять' })).not.toBeInTheDocument();
  });

  it('с can_edit — кнопки места и людей', async () => {
    serve(true);
    renderSection();
    await screen.findByTestId('level-1');
    expect(screen.getByRole('button', { name: /Добавить место/ })).toBeInTheDocument();
    const td = screen.getByTestId('slot-td');
    expect(within(td).getByRole('button', { name: /Назначить/ })).toBeInTheDocument();
    expect(within(td).getByRole('button', { name: 'Закрыть' })).toBeInTheDocument();
    // У ГД людей по плану — полный набор: «Назначить» нет, «Снять» есть.
    const gd = screen.getByTestId('slot-gd');
    expect(within(gd).queryByRole('button', { name: /Назначить/ })).not.toBeInTheDocument();
    expect(within(gd).getByRole('button', { name: 'Снять' })).toBeInTheDocument();
    // Рабочему L4 подчинённых мест не заводят.
    expect(within(screen.getByTestId('slot-rb'))
      .queryByRole('button', { name: /подчинённое/ })).not.toBeInTheDocument();
  });

  it('пустая структура — подсказка', async () => {
    serve(true, []);
    renderSection();
    expect(await screen.findByText('Структура проекта ещё не заведена')).toBeInTheDocument();
  });
});
