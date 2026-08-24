import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { renderWithProviders } from '@/test/renderWithProviders';

// ── моки ───────────────────────────────────────────────────────────────────
//
// HRLayout — сквозной враппер приложения, к предмету теста отношения не
// имеет (тот же приём, что HRPositions.test.tsx). useHRLevel мокаем, чтобы
// управлять правами напрямую, а не через ответ /employees/hr-level/.
// OrgChart мокается за пределами узнаваемой геометрии React Flow — jsdom не
// даёт @xyflow/react реальный layout, а этому тесту он и не нужен: важно
// только то, какой ПАНЕЛЬЮ (OrgEditPanel vs EmployeeDetailDrawer) страница
// отвечает на клик по узлу, и в каком режиме (editable) рисуется схема.

vi.mock('@/components/hr/HRLayout', () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

const hrLevel = { isSeniorOrAbove: true, isLoading: false };
vi.mock('@/hooks/useHRLevel', () => ({
  useHRLevel: () => hrLevel,
}));

vi.mock('@xyflow/react', () => ({
  ReactFlowProvider: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

vi.mock('@/components/hr/OrgChart', () => ({
  OrgChart: (props: { editable?: boolean; onNodeClick?: (node: unknown) => void }) => (
    <div>
      <span data-testid="org-chart-editable">{String(Boolean(props.editable))}</span>
      <button type="button" onClick={() => props.onNodeClick?.({ id: 'pos_1', label: 'Инженер', type: 'position' })}>
        node
      </button>
    </div>
  ),
}));

vi.mock('@/components/hr/OrgChart/OrgEditPanel', () => ({
  OrgEditPanel: ({ node }: { node: { id: string } | null }) => (
    node ? <div data-testid="org-edit-panel">{node.id}</div> : null
  ),
}));

vi.mock('@/components/hr/EmployeeDetailDrawer', () => ({
  EmployeeDetailDrawer: ({ node }: { node: { id: string } | null }) => (
    node ? <div data-testid="employee-detail-drawer">{node.id}</div> : null
  ),
}));

vi.mock('@/components/hr/ShareOrgDialog', () => ({
  ShareOrgDialog: () => null,
}));

vi.mock('@/api/client', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));

import api from '@/api/client';
import HROrgChart from '../HROrgChart';

const mockedApi = vi.mocked(api, true);

const TREE = { nodes: [{ id: 'pos_1', label: 'Инженер', type: 'position' }], edges: [] };

beforeEach(() => {
  vi.clearAllMocks();
  hrLevel.isSeniorOrAbove = true;
  hrLevel.isLoading = false;
  mockedApi.get.mockImplementation(((url: string) => {
    if (url.includes('departments')) return Promise.resolve({ data: [] });
    if (url.includes('org/tree')) return Promise.resolve({ data: TREE });
    return Promise.resolve({ data: [] });
  }) as never);
});

describe('HROrgChart — гейт правки', () => {
  it('не показывает тумблер «Редактировать» пользователю без прав senior/lead', async () => {
    hrLevel.isSeniorOrAbove = false;
    renderWithProviders(<HROrgChart />);
    await waitFor(() => expect(screen.getByTestId('org-chart-editable')).toBeInTheDocument());
    expect(screen.queryByText('Редактировать:')).not.toBeInTheDocument();
    expect(screen.getByTestId('org-chart-editable')).toHaveTextContent('false');
  });

  it('показывает тумблер senior/lead и по умолчанию схема остаётся read-only', async () => {
    renderWithProviders(<HROrgChart />);
    await waitFor(() => expect(screen.getByText('Редактировать:')).toBeInTheDocument());
    expect(screen.getByTestId('org-chart-editable')).toHaveTextContent('false');
  });

  it('клик по узлу без режима правки открывает EmployeeDetailDrawer', async () => {
    const user = userEvent.setup();
    renderWithProviders(<HROrgChart />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'node' })).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: 'node' }));
    expect(screen.getByTestId('employee-detail-drawer')).toHaveTextContent('pos_1');
    expect(screen.queryByTestId('org-edit-panel')).not.toBeInTheDocument();
  });

  it('включение режима правки переводит схему в editable и меняет панель на OrgEditPanel', async () => {
    const user = userEvent.setup();
    renderWithProviders(<HROrgChart />);
    await waitFor(() => expect(screen.getByRole('switch')).toBeInTheDocument());

    await user.click(screen.getByRole('switch'));
    expect(screen.getByTestId('org-chart-editable')).toHaveTextContent('true');

    await user.click(screen.getByRole('button', { name: 'node' }));
    expect(screen.getByTestId('org-edit-panel')).toHaveTextContent('pos_1');
    expect(screen.queryByTestId('employee-detail-drawer')).not.toBeInTheDocument();
  });
});
