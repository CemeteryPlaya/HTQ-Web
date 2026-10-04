/**
 * Манифест подмодуля «Выгрузки» (задача 6/8): маршрут документа по прямой
 * ссылке из уведомления, без пункта меню.
 */
import { describe, expect, it } from 'vitest';

import { bppModule } from './module';

describe('exports bppModule', () => {
  it('без пункта меню — сюда приходят только по прямой ссылке', () => {
    expect(bppModule.menu).toBeUndefined();
  });

  it('маршрут — exports/:id', () => {
    expect(bppModule.routes.map((r) => r.path)).toEqual(['exports/:id']);
  });
});
