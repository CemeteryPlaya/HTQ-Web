import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { renderWithProviders } from '@/test/renderWithProviders';

// ── моки ───────────────────────────────────────────────────────────────────
//
// Сайдбар тянет сеть (бейджи), реестр сервисов и звуковой модал — к предмету
// теста (раскрытие разделов) отношения не имеют.

vi.mock('@/api/client', () => ({
  default: { get: vi.fn(() => Promise.reject(new Error('offline'))) },
}));

vi.mock('@/hooks/useHRLevel', () => ({
  useHRLevel: () => ({ level: null, hasHrAccess: false }),
}));

// Предмет теста — раскрытие разделов, а не выдача прав, поэтому права
// подставляются напрямую. Со стадии 2 HR-раздел открывает уровень `hr:read`,
// а НЕ флаг `staff`: прежде `staff` входил в HR-ведро мёртвого словаря ролей
// и попадал в раздел даром.
const levels: Record<string, string> = { hr: 'read' };
const order = ['none', 'read', 'write', 'admin'];
vi.mock('@/hooks/usePermissions', () => ({
  usePermissions: () => ({
    company: 'demo',
    level: (m: string) => levels[m] ?? 'none',
    atLeast: (m: string, req: string) =>
      order.indexOf(levels[m] ?? 'none') >= order.indexOf(req),
    scope: () => null,
    subordinateCompanies: [],
    isLoading: false,
  }),
}));

vi.mock('@/hooks/useServiceStatus', () => ({
  useServiceStatus: () => ({ isDisabled: () => false }),
}));

vi.mock('@/components/sound/SoundSettingsModal', () => ({
  SoundSettingsModal: ({ trigger }: { trigger: React.ReactNode }) => <>{trigger}</>,
}));

import ProfileSidebar from '../ProfileSidebar';

const STORAGE_KEY = 'htq.profileSidebar.collapsedSections';

const renderSidebar = () =>
  renderWithProviders(<ProfileSidebar roles={['staff']} />, { route: '/myprofile' });

const hrHeader = () => screen.getByRole('button', { name: /^HR/ });

beforeEach(() => {
  window.localStorage.clear();
});

describe('ProfileSidebar — разделы меню', () => {
  it('HR-раздел раскрыт сразу: страницы видно без лишнего клика', () => {
    const { container } = renderSidebar();

    expect(hrHeader()).toHaveAttribute('aria-expanded', 'true');
    expect(container.querySelector('a[href="/hr/employees"]')).not.toBeNull();
    expect(container.querySelector('a[href="/hr/org-chart"]')).not.toBeNull();
  });

  it('состояние раздела переживает перемонтирование сайдбара', async () => {
    const user = userEvent.setup();
    const first = renderSidebar();

    await user.click(hrHeader());
    expect(hrHeader()).toHaveAttribute('aria-expanded', 'false');
    expect(first.container.querySelector('a[href="/hr/employees"]')).toBeNull();
    expect(JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? '{}')).toEqual({ hr: true });

    // Сайдбар живёт только на /myprofile и /settings, поэтому возврат на
    // профиль — это всегда новый монтаж компонента.
    first.unmount();
    const second = renderSidebar();

    expect(hrHeader()).toHaveAttribute('aria-expanded', 'false');
    // Свёрнут ровно тот раздел, который свернули: соседние не задеты.
    expect(second.container.querySelector('a[href="/myprofile"]')).not.toBeNull();

    await user.click(hrHeader());
    expect(hrHeader()).toHaveAttribute('aria-expanded', 'true');
    expect(second.container.querySelector('a[href="/hr/employees"]')).not.toBeNull();
    expect(JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? '{}')).toEqual({ hr: false });
  });

  it('битое значение в localStorage не ломает навигацию', () => {
    window.localStorage.setItem(STORAGE_KEY, 'не json');
    const { container } = renderSidebar();

    expect(hrHeader()).toHaveAttribute('aria-expanded', 'true');
    expect(container.querySelector('a[href="/hr/employees"]')).not.toBeNull();
  });
});
