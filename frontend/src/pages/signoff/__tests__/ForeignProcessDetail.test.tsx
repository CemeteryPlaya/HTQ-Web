/**
 * Карточка процесса дочерней компании, открытая из холдинга (B8.1): сводка
 * документа с позициями, решение уходит через холдинг, а этап, который
 * отсюда не решить, объясняет почему.
 */
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import type { ReactNode } from 'react';
import { Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';
import type { ForeignProcess } from '@/types/signoff';

import ForeignProcessDetail from '../ForeignProcessDetail';

vi.mock('@/components/signoff/SignoffShell', () => ({
  SignoffShell: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}));
const signoff = vi.hoisted(() => ({
  foreignProcess: vi.fn(), decideForeign: vi.fn(), getEnums: vi.fn(), listSubjects: vi.fn(),
}));
vi.mock('@/api/signoff', () => ({ signoffApi: signoff }));
const switchCompany = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth/companySwitch', () => ({ switchCompany }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const CHILD = { slug: 'beta', subdomain: null, name: 'Дочерняя', url: null, current: false };

const card = (over: Partial<ForeignProcess> = {}): ForeignProcess => ({
  id: 70, subject_type: 'bpp.invoice', subject_id: 'u1', scope: '', state: 'pending',
  initiator_id: 5, current_order: 1, created_at: '2026-10-02T10:00:00Z', finished_at: null,
  subject_facts: {}, subject_title: 'Счёт СЧ-2026-000001', subject_url: '/bpp/invoices/u1',
  initiator_name: 'Снабженец',
  stages: [{
    id: 1, order: 1, name: 'ФД', quorum: 'any', state: 'active', condition: [],
    matched_by: 'always', approver_kind: 'position', role_ids: [], user_ids: [],
    approver_key: '', requires_attachment: false, requires_comment: false,
    requirement_key: 'bpp:budget', requirement_label: null, decided_at: null,
    tasks: [{
      id: 700, user_id: 901, position_id: 12, full_name: 'Фин Директор', state: 'pending',
      comment: '', acted_at: null, file_id: null, file_url: null,
      position_label: 'Финансовый директор · Холдинг',
    }],
  }],
  company: CHILD,
  summary: {
    fields: [{ label: 'Контрагент', value: 'ТОО «Альфа»' }, { label: 'Сумма', value: '150 000,00 KZT' }],
    lines: {
      columns: [{ key: 'name', label: 'Позиция' }, { key: 'amount', label: 'Сумма', align: 'right' }],
      rows: [{ name: 'Цемент', amount: '150 000,00 KZT' }],
      total: { label: 'Итого', value: '150 000,00 KZT' },
    },
  },
  my_task_id: 700, direct_allowed: true, direct_blocker: null, can_enter: false,
  ...over,
});

function renderPage() {
  return renderWithProviders(
    <Routes>
      <Route path="/signoff/companies/:company/processes/:id" element={<ForeignProcessDetail />} />
    </Routes>,
    { route: '/signoff/companies/beta/processes/70' },
  );
}

describe('ForeignProcessDetail', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    signoff.getEnums.mockResolvedValue({
      data: { quorum: [], approver_kind: [], process_state: [], stage_state: [],
              task_state: [], approval_state: [] },
    });
    signoff.listSubjects.mockResolvedValue({ data: [] });
  });

  it('показывает сводку документа и решает через холдинг', async () => {
    signoff.foreignProcess.mockResolvedValue({ data: card() });
    signoff.decideForeign.mockResolvedValue({ data: card({ state: 'approved' }) });
    renderPage();

    expect(await screen.findByText('ТОО «Альфа»')).toBeInTheDocument();
    expect(screen.getByText('Цемент')).toBeInTheDocument();
    expect(screen.getByText('Итого')).toBeInTheDocument();
    expect(signoff.foreignProcess).toHaveBeenCalledWith('beta', 70);

    fireEvent.click(screen.getByRole('button', { name: 'Согласовать' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: /Согласовать/ }));

    await waitFor(() => expect(signoff.decideForeign).toHaveBeenCalledWith(
      'beta', 700, { decision: 'approve', comment: '' }));
  });

  it('этап, который отсюда не решить, объясняет почему — без кнопок решения', async () => {
    signoff.foreignProcess.mockResolvedValue({ data: card({
      direct_allowed: false,
      direct_blocker: 'Этап «ФД» требует приложить документ — решите на адресе компании',
    }) });
    renderPage();

    expect(await screen.findByText(/требует приложить документ/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Согласовать/ })).not.toBeInTheDocument();
  });

  it('с доступом к компании — переход к документу на её адресе', async () => {
    signoff.foreignProcess.mockResolvedValue({ data: card({ can_enter: true }) });
    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: /Открыть документ в Дочерняя/ }));

    expect(switchCompany).toHaveBeenCalledWith(CHILD, '/bpp/invoices/u1');
  });
});
