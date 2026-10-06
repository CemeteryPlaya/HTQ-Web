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

// Предмет теста — раскрытие разделов, а не выдача прав, поэтому права
// подставляются напрямую. Со стадии 2 HR-раздел открывает уровень `hr:read`,
// а НЕ флаг `staff`: прежде `staff` входил в HR-ведро мёртвого словаря ролей
// и попадал в раздел даром. С задачи 10 блока I кадровые пункты тоже читают
// `usePermissions` (узлы через `can`, область через `scope`), а не
// `useHRLevel` — здесь их нет: `hr:read` без единого узла открывает ровно
// пункты «для любого кадрового доступа» (сотрудники, оргсхема, документы).
const levels: Record<string, string> = { hr: 'read' };
// Узлы реестра функций — для пунктов модуля «Закупки и оплаты» в блоке
// «Подтверждения» (их видимость — `moduleVisible` подмодуля: уровень `bpp`
// и узел). По умолчанию пусто: прежние тесты узлов не касаются.
const nodes: Record<string, string[]> = {};
const order = ['none', 'read', 'write', 'admin'];
vi.mock('@/hooks/usePermissions', () => ({
  usePermissions: () => ({
    company: 'demo',
    level: (m: string) => levels[m] ?? 'none',
    atLeast: (m: string, req: string) =>
      order.indexOf(levels[m] ?? 'none') >= order.indexOf(req),
    scope: () => null,
    depth: () => [],
    can: (node: string, flag: string) => (nodes[node] ?? []).includes(flag),
    subordinateCompanies: [],
    isLoading: false,
  }),
}));

// Заморозка «Договоров» (A6.2): подпись пункта /contracts — «Архив договоров»
// у замороженной компании, «Договоры» — пока раздел живой (как в шапке).
const freeze = { frozen: true };
vi.mock('@/hooks/useContractsFreeze', () => ({
  useContractsFreeze: () => ({
    frozen: freeze.frozen, frozenAt: null, comment: '', isLoading: false,
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

// Финальное ревью блока L, M-3: ссылки модерации чатов и ящиков — по уровню
// ИХ модулей (как маршруты /admin/chats и /admin/mailboxes), не по users:admin.
describe('ProfileSidebar — ссылки модерации сервисов', () => {
  const withLevels = (next: Record<string, string>) => {
    const saved = { ...levels };
    Object.keys(levels).forEach((k) => delete levels[k]);
    Object.assign(levels, next);
    return () => {
      Object.keys(levels).forEach((k) => delete levels[k]);
      Object.assign(levels, saved);
    };
  };

  it('держатель services-admin без users:admin видит чаты и ящики', () => {
    const restore = withLevels({ messenger: 'admin', mail: 'admin' });
    try {
      const { container } = renderSidebar();
      expect(container.querySelector('a[href="/admin/chats"]')).not.toBeNull();
      expect(container.querySelector('a[href="/admin/mailboxes"]')).not.toBeNull();
      expect(container.querySelector('a[href="/admin/users"]')).toBeNull();
      expect(container.querySelector('a[href="/holding"]')).toBeNull();
    } finally {
      restore();
    }
  });

  it('users:admin без messenger:admin/mail:admin ссылок модерации не видит', () => {
    const restore = withLevels({ users: 'admin', messenger: 'write', mail: 'read' });
    try {
      const { container } = renderSidebar();
      expect(container.querySelector('a[href="/admin/users"]')).not.toBeNull();
      expect(container.querySelector('a[href="/admin/chats"]')).toBeNull();
      expect(container.querySelector('a[href="/admin/mailboxes"]')).toBeNull();
    } finally {
      restore();
    }
  });
});

// Phase 10.1 (решение 05.10): документы модуля «Закупки и оплаты», общая
// очередь согласований и архив «Договоров» — один блок «Подтверждения», а не
// три разрозненных пункта в «Работе».
describe('ProfileSidebar — блок «Подтверждения»', () => {
  const setRights = (nextLevels: Record<string, string>, nextNodes: Record<string, string[]> = {}) => {
    const savedLevels = { ...levels };
    const savedNodes = { ...nodes };
    Object.keys(levels).forEach((k) => delete levels[k]);
    Object.assign(levels, nextLevels);
    Object.keys(nodes).forEach((k) => delete nodes[k]);
    Object.assign(nodes, nextNodes);
    return () => {
      Object.keys(levels).forEach((k) => delete levels[k]);
      Object.assign(levels, savedLevels);
      Object.keys(nodes).forEach((k) => delete nodes[k]);
      Object.assign(nodes, savedNodes);
      freeze.frozen = true;
    };
  };

  const FD_NODES = {
    'bpp.budgets': ['view'],
    'bpp.requests': ['view'],
    'bpp.routes': ['view', 'edit'],
  };

  const sectionHrefs = (container: HTMLElement, id: string) =>
    [...container.querySelectorAll(`#sidebar-section-${id} a`)].map((a) => a.getAttribute('href'));

  it('блок есть сразу после «Работы», с пунктами модуля по правам', () => {
    const restore = setRights({ bpp: 'read' }, FD_NODES);
    try {
      const { container } = renderSidebar();
      const header = screen.getByRole('button', { name: /^Подтверждения/ });
      expect(header).toHaveAttribute('aria-expanded', 'true');

      const sections = [...container.querySelectorAll('button[aria-controls^="sidebar-section-"]')]
        .map((b) => b.getAttribute('aria-controls'));
      expect(sections.indexOf('sidebar-section-approvals'))
        .toBe(sections.indexOf('sidebar-section-work') + 1);

      const hrefs = sectionHrefs(container, 'approvals');
      // Общая очередь — первой, архив — последним, между ними — меню модуля
      // в порядке `order` (обзор → бюджеты → заявки → маршруты).
      expect(hrefs).toEqual(['/signoff', '/bpp/overview', '/bpp/budgets', '/bpp/requests', '/bpp/routes', '/contracts']);
      // Модульные «Мои согласования» заменены общей очередью — дубля нет.
      expect(hrefs).not.toContain('/bpp/approvals');
      // Подписи — те же, что в меню раздела (`BppLayout`).
      expect(screen.getByRole('link', { name: 'Бюджеты' })).toHaveAttribute('href', '/bpp/budgets');
      expect(screen.getByRole('link', { name: 'Заявки на закупку' })).toHaveAttribute('href', '/bpp/requests');
      expect(screen.getByRole('link', { name: 'Маршруты согласования' })).toHaveAttribute('href', '/bpp/routes');
      expect(screen.getByRole('link', { name: 'Мои согласования' })).toHaveAttribute('href', '/signoff');
      expect(screen.getByRole('link', { name: 'Архив договоров' })).toHaveAttribute('href', '/contracts');
    } finally {
      restore();
    }
  });

  it('без bpp:read — только общая очередь и архив, даже при узлах', () => {
    const restore = setRights({ hr: 'read', project: 'read', refdata: 'read' }, FD_NODES);
    try {
      const { container } = renderSidebar();
      expect(sectionHrefs(container, 'approvals')).toEqual(['/signoff', '/contracts']);
    } finally {
      restore();
    }
  });

  it('незамороженные «Договоры» подписаны «Договоры», а не архивом', () => {
    const restore = setRights({ hr: 'read' });
    freeze.frozen = false;
    try {
      const { container } = renderSidebar();
      expect(sectionHrefs(container, 'approvals')).toEqual(['/signoff', '/contracts']);
      expect(screen.getByRole('link', { name: 'Договоры' })).toHaveAttribute('href', '/contracts');
      expect(screen.queryByRole('link', { name: 'Архив договоров' })).toBeNull();
    } finally {
      restore();
    }
  });

  it('незамороженные «Договоры» рядом с модулем — «Прежние договоры», без второго «Договоры»', () => {
    const restore = setRights({ bpp: 'read' }, FD_NODES);
    freeze.frozen = false;
    try {
      renderSidebar();
      expect(screen.getByRole('link', { name: 'Прежние договоры' })).toHaveAttribute('href', '/contracts');
      expect(screen.queryAllByRole('link', { name: 'Договоры' })).toHaveLength(0);
    } finally {
      restore();
    }
  });

  it('в «Работе» нет «Договоров» и «Согласований», «Запросы» остались', () => {
    const restore = setRights({ hr: 'read', bpp: 'read' }, FD_NODES);
    try {
      const { container } = renderSidebar();
      const work = sectionHrefs(container, 'work');
      expect(work).toContain('/requests');
      expect(work).not.toContain('/contracts');
      expect(work).not.toContain('/signoff');
    } finally {
      restore();
    }
  });

  it('поиск находит пункты блока и раскрывает его со счётчиком', async () => {
    const restore = setRights({ bpp: 'read' }, FD_NODES);
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ approvals: true }));
    try {
      const user = userEvent.setup();
      const { container } = renderSidebar();
      expect(screen.getByRole('button', { name: /^Подтверждения/ })).toHaveAttribute('aria-expanded', 'false');
      expect(container.querySelector('#sidebar-section-approvals')).toBeNull();

      await user.type(screen.getByRole('textbox'), 'бюдж');
      expect(sectionHrefs(container, 'approvals')).toEqual(['/bpp/budgets']);
      expect(screen.getByRole('button', { name: /^Подтверждения/ })).toHaveTextContent('1');
    } finally {
      restore();
    }
  });

  it('пункт модуля подсвечен и на вложенной странице раздела', () => {
    const restore = setRights({ bpp: 'read' }, FD_NODES);
    try {
      renderWithProviders(<ProfileSidebar roles={['staff']} />, { route: '/bpp/budgets/42' });
      expect(screen.getByRole('link', { name: 'Бюджеты' })).toHaveAttribute('aria-current', 'page');
      expect(screen.getByRole('link', { name: 'Заявки на закупку' })).not.toHaveAttribute('aria-current');
    } finally {
      restore();
    }
  });
});
