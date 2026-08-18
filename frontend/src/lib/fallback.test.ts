/**
 * Механизм громких подмен на фронте.
 *
 * Стерегут то же, что и backend'ные тесты (apps/core/tests/test_fallback.py),
 * плюс специфику браузера: троттлинг отправки — без него подмена внутри
 * рендера отправила бы сотню запросов на первом же кадре.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { FallbackNotAllowedError, fallback, fallbackMode, resetFallbackThrottle } from './fallback';
import { logUserAction } from './telemetry';

vi.mock('./telemetry', () => ({ logUserAction: vi.fn() }));

beforeEach(() => {
  resetFallbackThrottle();
  vi.mocked(logUserAction).mockClear();
  vi.spyOn(console, 'warn').mockImplementation(() => {});
  vi.spyOn(console, 'debug').mockImplementation(() => {});
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe('строгий режим (разработчик)', () => {
  beforeEach(() => vi.stubEnv('VITE_HTQ_ENV', 'development'));

  it('не подменяет, а падает', () => {
    expect(() => fallback('tests.strict', 'подменённое', { reason: 'нет данных' }))
      .toThrow(FallbackNotAllowedError);
  });

  it('сохраняет исходную ошибку в cause', () => {
    const original = new Error('реальная причина');
    try {
      fallback('tests.cause', null, { reason: 'сбой', cause: original });
      expect.unreachable('подмена должна была упасть');
    } catch (err) {
      expect((err as FallbackNotAllowedError).cause).toBe(original);
    }
  });

  it('пропускает предусмотренную деградацию', () => {
    expect(fallback('tests.expected', [], { reason: 'камеры нет', expected: true })).toEqual([]);
  });

  it('уступает явному VITE_FALLBACK_MODE', () => {
    vi.stubEnv('VITE_FALLBACK_MODE', 'log');
    expect(fallbackMode()).toBe('log');
    expect(fallback('tests.override', 7, { reason: 'ослаблено локально' })).toBe(7);
  });
});

describe('прод-режим (пользователь ничего не замечает)', () => {
  beforeEach(() => vi.stubEnv('VITE_HTQ_ENV', 'production'));

  it('возвращает подставленное значение', () => {
    expect(fallback('tests.log', 42, { reason: 'нет данных' })).toBe(42);
  });

  it('пишет строку, по которой ищут', () => {
    fallback('tests.line', null, { reason: 'источник не ответил' });
    expect(console.warn).toHaveBeenCalledWith(
      'FALLBACK site=tests.line reason=источник не ответил',
      expect.anything(),
    );
  });

  it('предусмотренную деградацию логирует тише', () => {
    fallback('tests.quiet', null, { reason: 'камеры нет', expected: true });
    expect(console.debug).toHaveBeenCalled();
    expect(console.warn).not.toHaveBeenCalled();
  });

  it('отправляет событие в телеметрию', () => {
    fallback('tests.telemetry', null, { reason: 'источник не ответил', context: { status: 500 } });
    expect(logUserAction).toHaveBeenCalledWith({
      action: 'fallback',
      resource: 'tests.telemetry',
      meta: { reason: 'источник не ответил', expected: false, status: 500 },
    });
  });

  it('отправляет не чаще раза в минуту на site', () => {
    for (let i = 0; i < 5; i += 1) {
      fallback('tests.throttle', null, { reason: 'подряд' });
    }
    expect(logUserAction).toHaveBeenCalledTimes(1);
    // Другое место — своё окно: троттлинг не должен глушить соседей.
    fallback('tests.throttle-other', null, { reason: 'подряд' });
    expect(logUserAction).toHaveBeenCalledTimes(2);
  });
});

describe('режим выводится из среды', () => {
  it.each([
    ['production', 'log'],
    ['staging', 'log'],
    ['development', 'strict'],
  ])('%s → %s', (env, mode) => {
    vi.stubEnv('VITE_HTQ_ENV', env);
    expect(fallbackMode()).toBe(mode);
  });
});
