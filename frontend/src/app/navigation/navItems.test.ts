/**
 * Охраняет то, ради чего заведён единый список навигации: шапка и мобильная
 * нижняя панель больше не могут разойтись по составу разделов, а выросшее
 * число вкладок гарантированно уезжает в меню «Ещё», а не переполняет ряд.
 */
import { describe, expect, it } from 'vitest';

import {
  NAV_ITEMS,
  bottomNavItems,
  splitForHeader,
  visibleNavItems,
  type NavAbilities,
} from './navItems';

const FULL: NavAbilities = { isEditor: true, isHr: true, hasTasks: true, hasDepartment: true };
const PLAIN: NavAbilities = { isEditor: false, isHr: false, hasTasks: false, hasDepartment: false };

describe('navItems', () => {
  it('идентификаторы уникальны', () => {
    const ids = NAV_ITEMS.map((i) => i.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('пути уникальны', () => {
    const hrefs = NAV_ITEMS.map((i) => i.href);
    expect(new Set(hrefs).size).toBe(hrefs.length);
  });

  it('рядовой сотрудник видит общие разделы и не видит ролевые', () => {
    const ids = visibleNavItems(PLAIN).map((i) => i.id);
    expect(ids).toContain('calendar');
    expect(ids).toContain('messenger');
    expect(ids).toContain('email');
    expect(ids).toContain('contracts');
    expect(ids).toContain('signoff');
    expect(ids).not.toContain('employees');    // требует hr
    expect(ids).not.toContain('manage-news');  // требует editor
    expect(ids).not.toContain('tasks');        // требует tasks
    expect(ids).not.toContain('files');        // требует отдела
  });

  it('мобильная панель — подмножество разделов шапки (наборы не расходятся)', () => {
    for (const abilities of [FULL, PLAIN]) {
      const headerIds = new Set(visibleNavItems(abilities).map((i) => i.id));
      for (const item of bottomNavItems(abilities)) {
        expect(headerIds.has(item.id)).toBe(true);
      }
    }
  });

  it('при полном наборе прав лишние вкладки уезжают в «Ещё»', () => {
    const items = visibleNavItems(FULL);
    expect(items.length).toBeGreaterThan(5);

    const { primary, overflow } = splitForHeader(items, 4);
    expect(primary).toHaveLength(4);
    expect(overflow.length).toBeGreaterThan(0);
    // Ничего не потеряли и не продублировали.
    expect([...primary, ...overflow].map((i) => i.id)).toEqual(items.map((i) => i.id));
  });

  it('ради одного лишнего пункта меню не заводится', () => {
    const five = NAV_ITEMS.slice(0, 5);
    expect(splitForHeader(five, 4)).toEqual({ primary: five, overflow: [] });

    const six = NAV_ITEMS.slice(0, 6);
    expect(splitForHeader(six, 4).overflow).toHaveLength(2);
  });

  it('каждый раздел ведёт на абсолютный внутренний путь', () => {
    for (const item of NAV_ITEMS) {
      expect(item.href.startsWith('/')).toBe(true);
    }
  });
});
