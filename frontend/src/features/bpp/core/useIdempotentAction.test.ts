/**
 * Двойной клик и повтор (Review Focus 5 плана этапа 2 A, ТЗ §26.2):
 * второй клик во время запроса не шлёт второй запрос; повтор после 5xx или
 * обрыва сети идёт с тем же `Idempotency-Key`; после успеха или 4xx — новый.
 */
import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { useIdempotentAction } from './useIdempotentAction';

/** Промис, который тест завершает сам. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

/** Свёрнутая 5xx из `api/client.ts` — `Error` с `status`/`isServerError`. */
const serverError = (status: number) =>
  Object.assign(new Error('Ошибка сервера'), { status, isServerError: true });

/** 4xx — объект axios с `response`. */
const clientError = (status: number) =>
  Object.assign(new Error('Отказ'), { response: { status, data: { detail: 'нет' } } });

/** Обрыв сети — у axios нет ни `response`, ни свёрнутого статуса. */
const networkError = () => Object.assign(new Error('Network Error'), { code: 'ERR_NETWORK' });

describe('useIdempotentAction', () => {
  it('второй клик во время запроса не шлёт второй запрос', async () => {
    const pendingCall = deferred<string>();
    const fn = vi.fn(() => pendingCall.promise);
    const { result } = renderHook(() => useIdempotentAction(fn));

    let first!: Promise<string>;
    let second!: Promise<string>;
    act(() => {
      first = result.current.run();
      second = result.current.run();
    });
    // Замок держится и после перерисовки.
    await waitFor(() => expect(result.current.pending).toBe(true));
    act(() => { void result.current.run(); });

    await waitFor(() => expect(fn).toHaveBeenCalledTimes(1));
    expect(second).toBe(first);

    await act(async () => {
      pendingCall.resolve('ok');
      await first;
    });
    expect(result.current.pending).toBe(false);
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it('после 5xx повтор идёт тем же ключом', async () => {
    const fn = vi.fn<(key: string) => Promise<string>>()
      .mockRejectedValueOnce(serverError(502))
      .mockResolvedValueOnce('ok');
    const { result } = renderHook(() => useIdempotentAction(fn));

    await act(async () => {
      await expect(result.current.run()).rejects.toThrow('Ошибка сервера');
    });
    await act(async () => {
      await expect(result.current.run()).resolves.toBe('ok');
    });

    const [firstKey] = fn.mock.calls[0];
    const [secondKey] = fn.mock.calls[1];
    expect(firstKey).toMatch(/^[0-9a-f-]{36}$/);
    expect(secondKey).toBe(firstKey);
  });

  it('после обрыва сети повтор идёт тем же ключом', async () => {
    const fn = vi.fn<(key: string) => Promise<string>>()
      .mockRejectedValueOnce(networkError())
      .mockResolvedValueOnce('ok');
    const { result } = renderHook(() => useIdempotentAction(fn));

    await act(async () => {
      await expect(result.current.run()).rejects.toThrow('Network Error');
    });
    await act(async () => {
      await result.current.run();
    });
    expect(fn.mock.calls[1][0]).toBe(fn.mock.calls[0][0]);
  });

  it('после 4xx следующий запуск — новый ключ', async () => {
    const fn = vi.fn<(key: string) => Promise<string>>()
      .mockRejectedValueOnce(clientError(422))
      .mockResolvedValueOnce('ok');
    const { result } = renderHook(() => useIdempotentAction(fn));

    await act(async () => {
      await expect(result.current.run()).rejects.toThrow('Отказ');
    });
    await act(async () => {
      await result.current.run();
    });
    expect(fn.mock.calls[1][0]).not.toBe(fn.mock.calls[0][0]);
  });

  it('после успеха следующий запуск — новый ключ', async () => {
    const fn = vi.fn<(key: string) => Promise<string>>().mockResolvedValue('ok');
    const { result } = renderHook(() => useIdempotentAction(fn));

    await act(async () => { await result.current.run(); });
    await act(async () => { await result.current.run(); });
    expect(fn).toHaveBeenCalledTimes(2);
    expect(fn.mock.calls[1][0]).not.toBe(fn.mock.calls[0][0]);
  });

  it('синхронный throw в fn не оставляет замок висеть', async () => {
    const fn = vi.fn<(key: string) => Promise<string>>()
      .mockImplementationOnce(() => { throw clientError(400); })
      .mockResolvedValueOnce('ok');
    const { result } = renderHook(() => useIdempotentAction(fn));

    await act(async () => {
      await expect(result.current.run()).rejects.toThrow('Отказ');
    });
    await act(async () => {
      await expect(result.current.run()).resolves.toBe('ok');
    });
    expect(result.current.pending).toBe(false);
  });

  it('без crypto.randomUUID ключ собирается из getRandomValues', async () => {
    const original = crypto.randomUUID;
    Object.defineProperty(crypto, 'randomUUID', { value: undefined, configurable: true });
    try {
      const fn = vi.fn<(key: string) => Promise<string>>().mockResolvedValue('ok');
      const { result } = renderHook(() => useIdempotentAction(fn));
      await act(async () => { await result.current.run(); });
      expect(fn.mock.calls[0][0]).toMatch(
        /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
      );
    } finally {
      Object.defineProperty(crypto, 'randomUUID', { value: original, configurable: true });
    }
  });
});
