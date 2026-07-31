/**
 * Копия серверного правила `_report_for_write`. Тест сторожит именно то, что
 * копия остаётся копией: расхождение вернёт либо кнопку, дающую 403, либо
 * спрятанную кнопку у того, кто вправе.
 */
import { describe, expect, it } from 'vitest';

import { canEditDailyReport, canReportOnTask } from './dailyReport';

const base = { authorId: 5, supervisorId: 9, myId: 5, elevated: false };

describe('canEditDailyReport', () => {
  it('автор правит свой отчёт', () => {
    expect(canEditDailyReport(base)).toBe(true);
  });

  it('супервайзер задачи правит чужой', () => {
    expect(canEditDailyReport({ ...base, myId: 9 })).toBe(true);
  });

  it('посторонний участник задачи — нет', () => {
    // Заводить свой отчёт он вправе, править чужой — нет.
    expect(canEditDailyReport({ ...base, myId: 42 })).toBe(false);
  });

  it('админ правит любой', () => {
    expect(canEditDailyReport({ ...base, myId: 42, elevated: true })).toBe(true);
  });

  it('неизвестный супервайзер не даёт права', () => {
    // Страница роудмапа супервайзера задачи не знает. Выдать право по
    // отсутствующему значению значило бы показать кнопку, дающую 403.
    expect(canEditDailyReport({
      authorId: 5, myId: 42, elevated: false,
    })).toBe(false);
    expect(canEditDailyReport({
      authorId: 5, supervisorId: null, myId: 42, elevated: false,
    })).toBe(false);
  });

  it('незагруженный профиль не даёт права', () => {
    // `Number(undefined)` из useActiveProfile даёт NaN, и NaN === NaN ложно,
    // но полагаться на это нельзя: правило должно отказывать явно.
    expect(canEditDailyReport({ ...base, myId: NaN })).toBe(false);
    expect(canEditDailyReport({ ...base, myId: null })).toBe(false);
  });

  it('анонимный отчёт правит только админ', () => {
    // author_id nullable: отчёт мог приехать миграцией переноса факта из
    // TaskVolume.completed_quantity, у которого автора не было.
    expect(canEditDailyReport({
      authorId: null, supervisorId: 9, myId: 5, elevated: false,
    })).toBe(false);
    expect(canEditDailyReport({
      authorId: null, supervisorId: 9, myId: 5, elevated: true,
    })).toBe(true);
  });
});

describe('canReportOnTask', () => {
  const task = {
    reporter: 1, supervisor: 2, assignee: 3,
    assignees: [{ user_id: 3, role: 'primary' as const },
                { user_id: 4, role: 'collaborator' as const }],
    delegates: [{ user_id: 5 }],
  };

  it.each([
    ['автор задачи', 1],
    ['супервайзер', 2],
    ['основной исполнитель', 3],
    ['соисполнитель', 4],
    ['делегат супервайзера', 5],
  ])('%s вправе отчитаться', (_who, myId) => {
    expect(canReportOnTask(task, myId, false)).toBe(true);
  });

  it('наблюдатель — нет', () => {
    // Видеть задачу и отчитываться о ней — разные права: отчёт это заявление
    // о СВОЕЙ работе.
    expect(canReportOnTask(task, 42, false)).toBe(false);
  });

  it('админ — да, даже вне задачи', () => {
    expect(canReportOnTask(task, 42, true)).toBe(true);
  });

  it('незагруженная задача или профиль — нет', () => {
    expect(canReportOnTask(null, 3, false)).toBe(false);
    expect(canReportOnTask(task, NaN, false)).toBe(false);
  });

  it('пустые списки не ломают правило', () => {
    // `assignees`/`delegates` необязательны в ответе — отсутствие списка
    // должно читаться как «никого», а не падать.
    expect(canReportOnTask(
      { reporter: 1, supervisor: null, assignee: null, assignees: [] },
      1, false)).toBe(true);
    expect(canReportOnTask(
      { reporter: 1, supervisor: null, assignee: null, assignees: [] },
      9, false)).toBe(false);
  });
});
