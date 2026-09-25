import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';

import { renderWithProviders } from '@/test/renderWithProviders';

// ── моки ───────────────────────────────────────────────────────────────────
//
// HRLayout тянет Header/Footer со всем окружением приложения — к предмету
// теста отношения не имеет (тот же приём, что в HRDepartments.test.tsx).
// usePermissions мокаем, чтобы управлять правами явно: четыре разрушающие
// кадровые ручки (закрытие вакансии, удаление отклика, записи учёта
// времени, документа) стоят на сервере под module="hr", level="admin", а
// не под старым companyWide (write + область «компания») — держатель
// именной роли с write на всю компанию, но без delete, видел бы кнопку и
// получал 403.

vi.mock('@/components/hr/HRLayout', () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

const access = { hr: 'admin' as 'none' | 'read' | 'write' | 'admin' };
const scope = { kind: 'company' as 'company' | 'department', id: null as number | null };
const ORDER = ['none', 'read', 'write', 'admin'];
vi.mock('@/hooks/usePermissions', () => ({
  usePermissions: () => ({
    company: null,
    level: (m: string) => (m === 'hr' ? access.hr : 'none'),
    atLeast: (m: string, req: string) =>
      ORDER.indexOf(m === 'hr' ? access.hr : 'none') >= ORDER.indexOf(req),
    scope: () => ({ kind: scope.kind, id: scope.id }),
    depth: () => [],
    can: () => false,
    pageHidden: () => false,
    subordinateCompanies: [],
    inheritedFrom: [],
    isLoading: false,
    isError: false,
    refetch: () => {},
  }),
}));

vi.mock('@/api/client', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

import api from '@/api/client';
import HRDocuments from '../HRDocuments';
import HRVacancies from '../HRVacancies';
import HRApplications from '../HRApplications';
import HRTimeTracking from '../HRTimeTracking';

const mockedApi = vi.mocked(api, true);

const DOCUMENTS = [
  {
    id: 1,
    employee_id: 1,
    title: 'Трудовой договор №1',
    doc_type: 'contract',
    file_path: '',
    file_size: 0,
    mime_type: 'application/pdf',
    metadata: {},
    uploaded_by: null,
    created_at: '2026-01-01',
    updated_at: '2026-01-01',
  },
];

const EMPLOYEES = [
  { id: 1, first_name: 'Иван', last_name: 'Иванов', middle_name: null, email: 'ivanov@htq.kz' },
];

const VACANCIES = [
  {
    id: 1,
    title: 'Инженер-строитель',
    department: null,
    department_name: '',
    status: 'open',
    created_by_name: '',
    applications_count: 0,
    salary_min: null,
    salary_max: null,
    created_at: '2026-01-01',
  },
];

const DEPARTMENTS: Array<{ id: number; name: string }> = [];

const APPLICATIONS = [
  {
    id: 1,
    vacancy: 1,
    first_name: 'Пётр',
    last_name: 'Петров',
    email: 'petrov@htq.kz',
    phone: '',
    vacancy_title: 'Инженер-строитель',
    status: 'new' as const,
    created_at: '2026-01-01',
  },
];

const TIME_ENTRIES = [
  {
    id: 1,
    employee_id: 1,
    date: '2026-01-05',
    start_time: '09:00:00',
    end_time: '18:00:00',
    break_minutes: 60,
    description: null,
    project: null,
    task: null,
    created_at: '2026-01-05',
    updated_at: '2026-01-05',
  },
];

beforeEach(() => {
  vi.clearAllMocks();
  access.hr = 'admin';
  scope.kind = 'company';
  scope.id = null;
  mockedApi.get.mockImplementation(((url: string) => {
    if (url === 'hr/v1/documents/') return Promise.resolve({ data: DOCUMENTS });
    if (url === 'hr/v1/employees/') return Promise.resolve({ data: EMPLOYEES });
    if (url === 'hr/v1/vacancies/') return Promise.resolve({ data: VACANCIES });
    if (url === 'hr/v1/departments/') return Promise.resolve({ data: DEPARTMENTS });
    if (url === 'hr/v1/applications/') return Promise.resolve({ data: APPLICATIONS });
    if (url === 'hr/v1/time-tracking/') return Promise.resolve({ data: TIME_ENTRIES });
    return Promise.resolve({ data: [] });
  }) as never);
});

describe('кнопки удаления кадровых экранов', () => {
  describe('HRDocuments — удаление документа', () => {
    it('не показывает удаление документа держателю write', async () => {
      access.hr = 'write';
      renderWithProviders(<HRDocuments />);
      expect(await screen.findByText('Трудовой договор №1')).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /удалить/i })).not.toBeInTheDocument();
    });

    it('показывает удаление документа держателю admin', async () => {
      access.hr = 'admin';
      renderWithProviders(<HRDocuments />);
      expect(await screen.findAllByRole('button', { name: /удалить/i })).not.toHaveLength(0);
    });

    it('показывает удаление документа держателю admin + область отдела', async () => {
      access.hr = 'admin';
      scope.kind = 'department';
      scope.id = 42;
      renderWithProviders(<HRDocuments />);
      expect(await screen.findByText('Трудовой договор №1')).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /удалить/i })).toBeInTheDocument();
    });
  });

  describe('HRVacancies — закрытие вакансии', () => {
    it('не показывает закрытие вакансии держателю write', async () => {
      access.hr = 'write';
      renderWithProviders(<HRVacancies />);
      expect(await screen.findByText('Инженер-строитель')).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /удалить/i })).not.toBeInTheDocument();
    });

    it('показывает закрытие вакансии держателю admin', async () => {
      access.hr = 'admin';
      renderWithProviders(<HRVacancies />);
      expect(await screen.findAllByRole('button', { name: /удалить/i })).not.toHaveLength(0);
    });
  });

  describe('HRApplications — удаление отклика', () => {
    it('не показывает удаление отклика держателю write', async () => {
      access.hr = 'write';
      renderWithProviders(<HRApplications />);
      expect(await screen.findByText('Пётр Петров')).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /удалить/i })).not.toBeInTheDocument();
    });

    it('показывает удаление отклика держателю admin', async () => {
      access.hr = 'admin';
      renderWithProviders(<HRApplications />);
      expect(await screen.findAllByRole('button', { name: /удалить/i })).not.toHaveLength(0);
    });
  });

  describe('HRTimeTracking — удаление записи учёта времени', () => {
    it('не показывает удаление записи держателю write', async () => {
      access.hr = 'write';
      renderWithProviders(<HRTimeTracking />);
      expect(await screen.findByText('Иванов Иван')).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /удалить/i })).not.toBeInTheDocument();
    });

    it('показывает удаление записи держателю admin', async () => {
      access.hr = 'admin';
      renderWithProviders(<HRTimeTracking />);
      expect(await screen.findAllByRole('button', { name: /удалить/i })).not.toHaveLength(0);
    });
  });
});
