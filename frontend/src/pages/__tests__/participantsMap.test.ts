/**
 * Разбор списка участников звонка.
 *
 * Гость и сотрудник на встрече выглядели одинаково: SFU отдавал пирам
 * только имя, а флаг гостя писал лишь в журнал. На встрече с внешним
 * человеком это ровно то, что нужно видеть.
 */
import { describe, expect, it } from 'vitest';

import { toParticipantsMap } from '../ConferencePage';

describe('toParticipantsMap', () => {
  it('сохраняет признак гостя', () => {
    const map = toParticipantsMap([
      { peerId: 'p1', displayName: 'Пётр', isGuest: false },
      { peerId: 'p2', displayName: 'Внешний', isGuest: true },
    ]);

    expect(map.get('p1')).toEqual({ name: 'Пётр', isGuest: false });
    expect(map.get('p2')).toEqual({ name: 'Внешний', isGuest: true });
  });

  it('без флага считает участника сотрудником', () => {
    const map = toParticipantsMap([{ peerId: 'p3', displayName: 'Аня' }]);

    expect(map.get('p3')).toEqual({ name: 'Аня', isGuest: false });
  });
});
