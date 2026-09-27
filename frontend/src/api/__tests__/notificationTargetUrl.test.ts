import { describe, expect, it } from 'vitest';

import { notificationTargetUrl } from '../tasks';

const base = { target_type: null, target_id: null, task: null, verb: '', url: null } as const;

describe('notificationTargetUrl', () => {
  it('известная цель ведёт по карте маршрутов, а не по url', () => {
    expect(notificationTargetUrl({ ...base, target_type: 'task', target_id: '7', url: '/x' }))
      .toBe('/tasks/7');
  });

  it('цель без карты маршрутов ведёт по url писателя', () => {
    expect(notificationTargetUrl({ ...base, url: '/bpp/invoices/5' })).toBe('/bpp/invoices/5');
  });

  it('внешний адрес не открывается', () => {
    expect(notificationTargetUrl({ ...base, url: 'https://evil.example' })).toBeNull();
    expect(notificationTargetUrl({ ...base, url: '//evil.example/x' })).toBeNull();
  });
});
