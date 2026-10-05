/**
 * Экран маршрутов согласования (Phase 10.2, решение 05.10): типы разложены
 * по разделам, технический код типа (`approvals.request`) на экран не
 * выводится — у старых «Договоров» и модуля БЗО названия типов совпадают
 * («Договор», «Счёт на оплату»), и различает их раздел, а не код.
 */
import { screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';
import type { ApprovalRoute, Subject } from '@/types/signoff';

import { RouteListPanel } from '../RouteListPanel';

const listSubjects = vi.hoisted(() => vi.fn());
const listRoutes = vi.hoisted(() => vi.fn());
vi.mock('@/api/signoff', () => ({ signoffApi: { listSubjects, listRoutes } }));

const subject = (subject_type: string, label: string): Subject => ({
  subject_type, label, has_active_route: false, fields: [], scopes: [],
  approver_fields: [], requirement_fields: [],
});

const route = (id: number, subject_type: string, name: string) => ({
  id, subject_type, name, scope: '', scope_label: null, is_active: true, stages: [],
}) as unknown as ApprovalRoute;

const ALL_TYPES = [
  subject('contracts.agreement', 'Договор'),
  subject('approvals.request', 'Запрос'),
  subject('hr.bonus', 'Премия'),
  subject('bpp.agreement', 'Договор'),
  subject('bpp.invoice', 'Счёт на оплату'),
  subject('misc.thing', 'Нечто'),
];

describe('RouteListPanel — разделы вместо кода типа', () => {
  it('раскладывает типы по разделам, архив «Договоров» — последним', async () => {
    listSubjects.mockResolvedValue({ data: ALL_TYPES });
    listRoutes.mockResolvedValue({
      data: [route(1, 'bpp.agreement', 'Новый договор'), route(2, 'contracts.agreement', 'Старый договор')],
    });
    renderWithProviders(<RouteListPanel />);

    await screen.findByText('Новый договор');
    const sections = screen.getAllByRole('region').map((region) => region.getAttribute('aria-label'));
    expect(sections).toEqual([
      'Закупки и оплаты', 'Кадры', 'Запросы', 'Прочее', 'Архив договоров (только чтение)',
    ]);

    const bpp = screen.getByRole('region', { name: 'Закупки и оплаты' });
    expect(within(bpp).getByText('Счёт на оплату')).toBeInTheDocument();
    expect(within(bpp).getByText('Новый договор')).toBeInTheDocument();
    expect(within(bpp).queryByText('Старый договор')).toBeNull();

    const archive = screen.getByRole('region', { name: 'Архив договоров (только чтение)' });
    expect(within(archive).getByText('Старый договор')).toBeInTheDocument();
    expect(within(screen.getByRole('region', { name: 'Запросы' }))
      .getByText('Запрос')).toBeInTheDocument();
    expect(within(screen.getByRole('region', { name: 'Кадры' })).getByText('Премия')).toBeInTheDocument();
    expect(within(screen.getByRole('region', { name: 'Прочее' })).getByText('Нечто')).toBeInTheDocument();
  });

  it('технический код типа на экран не выводится', async () => {
    listSubjects.mockResolvedValue({ data: ALL_TYPES });
    listRoutes.mockResolvedValue({ data: [] });
    renderWithProviders(<RouteListPanel />);

    await screen.findByText('Премия');
    for (const code of ALL_TYPES.map((item) => item.subject_type)) {
      expect(screen.queryByText(code)).not.toBeInTheDocument();
    }
  });

  it('единственный раздел (страница модуля) — без заголовка', async () => {
    listSubjects.mockResolvedValue({ data: ALL_TYPES });
    listRoutes.mockResolvedValue({ data: [] });
    renderWithProviders(
      <RouteListPanel subjectFilter={(type) => type.startsWith('bpp.')} />,
    );

    await screen.findByText('Счёт на оплату');
    expect(screen.queryByRole('region')).toBeNull();
    expect(screen.queryByText('Закупки и оплаты')).not.toBeInTheDocument();
    expect(screen.queryByText('Премия')).not.toBeInTheDocument();
  });
});
