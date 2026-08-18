import { describe, expect, it } from 'vitest';

import {
  activeSegmentIndex,
  daysUntilExpiry,
  formatDuration,
  formatTimecode,
  recordingBadge,
  timecodeToSeconds,
} from './history';

describe('formatTimecode', () => {
  it('показывает часы только когда они есть', () => {
    expect(formatTimecode(0)).toBe('00:00');
    expect(formatTimecode(7_000)).toBe('00:07');
    expect(formatTimecode(432_000)).toBe('07:12');
    expect(formatTimecode(4_032_000)).toBe('1:07:12');
  });

  it('не ломается на отрицательном значении', () => {
    expect(formatTimecode(-5_000)).toBe('00:00');
  });
});

describe('переход к реплике', () => {
  it('переводит миллисекунды в секунды плеера', () => {
    // Ошибка в 1000 раз здесь ничего не уронит — просто перемотает не туда.
    expect(timecodeToSeconds(432_500)).toBe(432.5);
    expect(timecodeToSeconds(-1)).toBe(0);
  });
});

describe('activeSegmentIndex', () => {
  const segments = [
    { start_ms: 0 },
    { start_ms: 10_000 },
    { start_ms: 30_000 },
  ];

  it('находит последнюю начавшуюся реплику', () => {
    expect(activeSegmentIndex(segments, 0)).toBe(0);
    expect(activeSegmentIndex(segments, 9.9)).toBe(0);
    expect(activeSegmentIndex(segments, 10)).toBe(1);
    expect(activeSegmentIndex(segments, 120)).toBe(2);
  });

  it('в паузе держит подсветку на последнем сказанном', () => {
    // 20-я секунда — между репликами. Гасить подсветку нельзя: глаз
    // потеряет место в тексте ровно тогда, когда за ним следит.
    expect(activeSegmentIndex(segments, 20)).toBe(1);
  });

  it('до первой реплики не подсвечивает ничего', () => {
    expect(activeSegmentIndex([{ start_ms: 5_000 }], 1)).toBe(-1);
    expect(activeSegmentIndex([], 42)).toBe(-1);
  });
});

describe('formatDuration', () => {
  it.each([
    [null, '—'],
    [42, '42 сек'],
    [420, '7 мин'],
    [3_600, '1 ч'],
    [5_040, '1 ч 24 мин'],
  ])('%p → %s', (input, expected) => {
    expect(formatDuration(input as number | null)).toBe(expected);
  });
});

describe('daysUntilExpiry', () => {
  const now = new Date('2026-08-18T12:00:00Z');

  it('считает остаток срока хранения', () => {
    expect(daysUntilExpiry('2026-08-28T12:00:00Z', now)).toBe(10);
  });

  it('может быть отрицательным: уборщик ходит раз в сутки', () => {
    expect(daysUntilExpiry('2026-08-17T12:00:00Z', now)).toBe(-1);
  });
});

describe('recordingBadge', () => {
  it('различает «не писали» и «удалено по сроку»', () => {
    // Слить их в одну подпись значило бы отправить человека искать файл,
    // которого никогда не было, — или наоборот.
    expect(recordingBadge('none').fallback).toBe('Без записи');
    expect(recordingBadge('purged').fallback).toBe('Удалена по сроку');
    expect(recordingBadge('none').i18nKey)
      .not.toBe(recordingBadge('purged').i18nKey);
  });
});
