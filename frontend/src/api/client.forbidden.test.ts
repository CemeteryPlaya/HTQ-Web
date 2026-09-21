/**
 * Запрещённый эндпоинт не должен расшатывать сессию.
 *
 * История: карточка согласования дёргала `hr/v1/employees/`, на который у
 * согласующего прав нет. Каждый 403 запускал в перехватчике своё обновление
 * токена, react-query повторял запрос трижды — и один отказ превращался в
 * восемь обращений и восемь новых пар токенов поверх друг друга.
 *
 * Здесь проверяется нижний слой этой связки: сколько бы 403 ни пришло,
 * обновление токена уходит ОДНО, а отказ остаётся отказом.
 */

import axios, { AxiosError, type AxiosRequestConfig } from 'axios';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import api from './client';
import { REFRESH_TOKEN_KEY } from '@/lib/auth/profileStorage';

/** Транспорт, который всегда отвечает 403. */
const forbiddenAdapter = async (config: AxiosRequestConfig) => {
  throw new AxiosError('Forbidden', 'ERR_BAD_REQUEST', config as never, null, {
    status: 403,
    statusText: 'Forbidden',
    data: { detail: 'HR access denied' },
    headers: {},
    config: config as never,
  } as never);
};

describe('403 не превращается в поток обновлений токена', () => {
  let refreshSpy: ReturnType<typeof vi.spyOn>;
  const realAdapter = api.defaults.adapter;

  beforeEach(() => {
    window.localStorage.setItem(REFRESH_TOKEN_KEY, 'refresh-token');
    api.defaults.adapter = forbiddenAdapter as never;
    refreshSpy = vi
      .spyOn(axios, 'post')
      .mockResolvedValue({ data: { access: 'fresh-access' } } as never);
  });

  afterEach(() => {
    api.defaults.adapter = realAdapter;
    refreshSpy.mockRestore();
    window.localStorage.clear();
    document.cookie = `${REFRESH_TOKEN_KEY}=; Max-Age=0; Path=/`;
  });

  it('поток 403 даёт одно обновление токена, а дальше — просто отказ', async () => {
    const results = await Promise.allSettled(
      Array.from({ length: 10 }, (_, i) => api.get(`/probe-${i}`)),
    );

    // Каждый запрос закончился отказом — 403 остался 403.
    expect(results.every((r) => r.status === 'rejected')).toBe(true);
    // И на все десять — ровно один POST на token/refresh/.
    expect(refreshSpy).toHaveBeenCalledTimes(1);

    // Следующий такой же отказ уже не трогает токен: кулдаун держит ветку
    // закрытой, пока не пройдёт минута. Это и есть разница между «права
    // только что выдали» и «прав нет» — второе повторяется бесконечно.
    refreshSpy.mockClear();
    await api.get('/probe-again').catch(() => undefined);
    expect(refreshSpy).not.toHaveBeenCalled();
  });
});
