import { describe, expect, it } from 'vitest';

import { canEditCalendarEvent, canEditProductionDay } from './calendarAccess';

const foreign = { creator_id: 5, creator: 5 };

describe('canEditCalendarEvent', () => {
  it('staff без узла календаря правит чужое событие', () => {
    expect(canEditCalendarEvent(foreign, 9, ['staff'])).toBe(true);
    expect(canEditCalendarEvent(foreign, 9, ['admin'])).toBe(true);
  });
  it('ОД без staff чужое событие не правит, своё — да', () => {
    expect(canEditCalendarEvent(foreign, 9, ['user'])).toBe(false);
    expect(canEditCalendarEvent(foreign, 5, ['user'])).toBe(true);
  });
});

describe('canEditProductionDay', () => {
  const day = (can_edit: boolean) => [{ date: '2026-01-05', day_type: 'working' as const, working_days_since_epoch: 1, can_edit }];
  it('кнопка дня — только при узле и в управляющей компании', () => {
    expect(canEditProductionDay(true, day(true))).toBe(true);
    expect(canEditProductionDay(true, day(false))).toBe(false); // дочерняя компания
    expect(canEditProductionDay(false, day(true))).toBe(false); // нет узла
    expect(canEditProductionDay(true, [])).toBe(false);
  });
});
